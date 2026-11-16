"""End-to-end synthetic EMPI pipeline.

    python -m empi

reads nothing but the seed, writes source extracts, loads SQLite, runs the SQL
quality checks, scores duplicate candidates, and exports the Power BI tables.
"""

import argparse
import importlib.metadata
import logging
import time
from pathlib import Path

from empi.config import DATA_DIR, DB_PATH, OUTPUT_DIR, SOURCES
from empi.csvio import read_csv
from empi.evaluate import evaluate
from empi.export import export_outputs
from empi.fhir_sample import write_match_examples
from empi.generate import generate_dataset
from empi.load import (
    connect,
    insert_ground_truth,
    insert_links,
    insert_pairs,
    insert_records,
    insert_scenarios,
    load_features,
    retire_records,
)
from empi.match import build_links, score_candidates
from empi.models import RAW_COLUMNS, TRUTH_COLUMNS, RawRecord, TruthRow
from empi.quality import export_reports, run_issue_queries, sql_confusion
from empi.scenarios import SCENARIO_BY_KEY, ScenarioSpec, baseline_spec, resolve_scenarios
from empi.standardize import assert_gender_tokens_match_map, clean_record

logger = logging.getLogger("empi")


def _raw_records(data_dir: Path) -> list[RawRecord]:
    rows: list[RawRecord] = []
    for meta in SOURCES.values():
        for record in read_csv(data_dir / meta["file_name"]):
            rows.append(RawRecord(**{column: record.get(column, "") for column in RAW_COLUMNS}))
    return rows


def _truth(data_dir: Path, scenario_key: str) -> list[TruthRow]:
    rows = []
    for record in read_csv(data_dir / "ground_truth.csv"):
        rows.append(
            TruthRow(
                source_record_id=record["source_record_id"],
                golden_person_id=record["golden_person_id"],
                is_injected_duplicate=int(record["is_injected_duplicate"]),
                variant=record.get("variant", ""),
                parent_record_id=record.get("parent_record_id", ""),
                source_system=record["source_system"],
                scenario_key=record.get("scenario_key") or scenario_key,
            )
        )
    return rows


def _check_sql(connection, metrics: dict) -> None:
    expected = {
        "auto_link_confusion": metrics["auto_link"],
        "flagged_confusion": metrics["flagged"],
    }
    for name, result in expected.items():
        sql_counts = sql_confusion(connection, name)
        if sql_counts["true_pairs"] != metrics["true_pairs"]:
            raise RuntimeError(f"{name} true_pairs disagree with Python")
        if sql_counts["true_positives"] != result["tp"]:
            raise RuntimeError(
                f"{name} true positives SQL={sql_counts['true_positives']} Python={result['tp']}"
            )
        if sql_counts["predicted_pairs"] != result["predicted"]:
            raise RuntimeError(
                f"{name} predicted SQL={sql_counts['predicted_pairs']} Python={result['predicted']}"
            )


def _scenario_folder(data_dir: Path, spec: ScenarioSpec, separate_folders: bool) -> Path:
    return data_dir / spec.key if separate_folders else data_dir


def run_pipeline(
    *,
    scenarios: list[ScenarioSpec] | None = None,
    persons: int | None = None,
    duplicates: int | None = None,
    seed: int | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    db_path: Path = DB_PATH,
) -> dict:
    """Build one or more scenarios into a single database and star schema.

    Passing persons, duplicates, or seed without `scenarios` runs baseline at that size.
    That keeps the small test runs on the original population.
    """
    started = time.perf_counter()
    assert_gender_tokens_match_map()
    if scenarios is None:
        spec = baseline_spec()
        from dataclasses import replace

        scenarios = [
            replace(
                spec,
                persons=spec.persons if persons is None else persons,
                duplicates=spec.duplicates if duplicates is None else duplicates,
                seed=spec.seed if seed is None else seed,
            )
        ]
    separate_folders = len(scenarios) > 1
    cleaned = []
    truth: list[TruthRow] = []
    for spec in scenarios:
        folder = _scenario_folder(data_dir, spec, separate_folders)
        logger.info(
            "Generating scenario %s: %s persons, %s duplicate charts, seed %s",
            spec.key,
            spec.persons,
            spec.duplicates,
            spec.seed,
        )
        generate_dataset(folder, scenario=spec)
        for raw in _raw_records(folder):
            record = clean_record(raw)
            record.scenario_key = spec.key
            cleaned.append(record)
        truth.extend(_truth(folder, spec.key))
    if separate_folders:
        for stale in data_dir.glob("*.csv"):
            stale.unlink()
    logger.info("Loading %s standardized charts across %s scenarios", len(cleaned), len(scenarios))
    connection = connect(db_path)
    try:
        with connection:
            insert_scenarios(
                connection,
                [
                    {
                        "scenario_key": spec.key,
                        "scenario_name": spec.name,
                        "scenario_sort": spec.sort,
                        "description": spec.description,
                        "seed": spec.seed,
                    }
                    for spec in scenarios
                ],
            )
            insert_records(connection, cleaned)
            issue_count = run_issue_queries(connection)
        features = load_features(connection)
        logger.info("Scoring candidate pairs")
        pairs, block_stats = score_candidates(features)
        links, retired = build_links(features, pairs)
        with connection:
            insert_pairs(connection, pairs)
            insert_links(connection, links)
            retire_records(connection, retired)
            insert_ground_truth(connection, truth)
        truth_rows = [
            {
                "source_record_id": row.source_record_id,
                "golden_person_id": row.golden_person_id,
                "is_injected_duplicate": str(row.is_injected_duplicate),
                "variant": row.variant,
                "scenario_key": row.scenario_key,
            }
            for row in truth
        ]
        for column in ("source_record_id", "golden_person_id", "is_injected_duplicate", "scenario_key"):
            if column not in truth_rows[0]:
                raise RuntimeError(f"ground truth is missing {column}")
        if TRUTH_COLUMNS[-1] != "scenario_key":
            raise RuntimeError("truth columns drifted")
        metrics = evaluate(pairs, truth_rows, block_stats)
        by_record = {row.source_record_id: row.scenario_key for row in truth}
        scenario_metrics = []
        for spec in scenarios:
            subset_pairs = [
                pair
                for pair in pairs
                if by_record[pair.record_id_1] == spec.key
                and by_record[pair.record_id_2] == spec.key
            ]
            crossed = [
                pair
                for pair in pairs
                if by_record[pair.record_id_1] != by_record[pair.record_id_2]
            ]
            if crossed:
                raise RuntimeError("matcher compared charts from different scenarios")
            subset_truth = [row for row in truth_rows if row["scenario_key"] == spec.key]
            subset_stats = {
                "candidate_pairs": len(subset_pairs),
                "blocks_used": 0,
                "blocks_skipped": 0,
                "max_block_size": 0,
            }
            scenario_result = evaluate(subset_pairs, subset_truth, subset_stats)
            scenario_result["scenario_key"] = spec.key
            scenario_result["seed"] = spec.seed
            scenario_result["person_count"] = spec.persons
            scenario_result["duplicate_count"] = spec.duplicates
            scenario_metrics.append(scenario_result)
        _check_sql(connection, metrics)
        metrics["issue_count"] = issue_count
        metrics["links_written"] = len(links)
        metrics["charts_retired"] = len(retired)
        metrics["seed"] = scenarios[0].seed
        metrics["person_count"] = sum(spec.persons for spec in scenarios)
        metrics["duplicate_count"] = sum(spec.duplicates for spec in scenarios)
        metrics["faker_version"] = importlib.metadata.version("faker")
        metrics["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        metrics["scenarios"] = scenario_metrics
        export_outputs(connection, output_dir, metrics)
        example_key = scenarios[0].key
        example_pairs = [
            pair for pair in pairs if by_record[pair.record_id_1] == example_key
        ]
        write_match_examples(connection, example_pairs, output_dir / "match_examples.json")
        export_reports(connection, output_dir)
        kept = [pair for pair in pairs if pair.decision != "non_match"]
        stored = connection.execute("SELECT COUNT(*) AS n FROM match_pair").fetchone()["n"]
        if len(kept) != stored:
            raise RuntimeError("stored pair count does not match scored decisions")
    finally:
        connection.close()
    for scenario_result in metrics["scenarios"]:
        auto = scenario_result["auto_link"]
        flagged = scenario_result["flagged"]
        logger.info(
            "%s duplicate rate %.2f%%. Auto-link P %.3f R %.3f F1 %.3f. "
            "Flagged P %.3f R %.3f F1 %.3f.",
            scenario_result["scenario_key"],
            scenario_result["injected_duplicate_rate"] * 100,
            auto["precision"],
            auto["recall"],
            auto["f1"],
            flagged["precision"],
            flagged["recall"],
            flagged["f1"],
        )
    logger.info("Elapsed %.1fs.", metrics["elapsed_seconds"])
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic EMPI pipeline")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIO_BY_KEY),
        help="Build one named scenario. Combine with --persons to change its size.",
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Build every named scenario. This is also the default when --scenario is omitted.",
    )
    parser.add_argument("--persons", type=int, default=None)
    parser.add_argument("--duplicates", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    all_flag = args.all_scenarios or args.scenario is None
    specs = resolve_scenarios(
        scenario=args.scenario,
        all_scenarios_flag=all_flag,
        persons=args.persons,
        duplicates=args.duplicates,
        seed=args.seed,
    )
    metrics = run_pipeline(
        scenarios=specs,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        db_path=args.db_path,
    )
    for scenario_result in metrics["scenarios"]:
        auto = scenario_result["auto_link"]
        flagged = scenario_result["flagged"]
        print(
            f"{scenario_result['scenario_key']}: "
            f"records={scenario_result['total_records']} "
            f"injected_duplicate_rate={scenario_result['injected_duplicate_rate']:.4f} "
            f"auto_link_precision={auto['precision']:.4f} "
            f"auto_link_recall={auto['recall']:.4f} "
            f"auto_link_f1={auto['f1']:.4f} "
            f"auto_link_fp={auto['fp']} "
            f"review_pairs={scenario_result['review_pairs']} "
            f"flagged_precision={flagged['precision']:.4f} "
            f"flagged_recall={flagged['recall']:.4f} "
            f"flagged_f1={flagged['f1']:.4f}"
        )
    return 0
