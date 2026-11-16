"""Star-schema CSV extracts for Power BI and the metrics file."""

import json
from datetime import date, timedelta
from pathlib import Path

import sqlite3

from empi.config import AS_OF, WINDOW_END, WINDOW_START
from empi.csvio import write_csv
from empi.issues import ISSUE_CATALOG
from empi.standardize import display_name

FIELD_CATALOG = (
    ("given_name", 1, "core", "Given name is present after standardization."),
    ("family_name", 2, "core", "Family name is present after standardization."),
    ("birth_date", 3, "core", "Birth date parsed to an ISO date."),
    ("known_gender", 4, "core", "Administrative gender is male, female, or other. Unknown does not count."),
    ("street", 5, "core", "Street line is present after standardization."),
    ("postal_code", 6, "core", "Postal code normalized to 5 digits."),
    ("phone", 7, "contact", "Phone normalized to 10 digits. Not part of the headline completeness score."),
    ("ssn", 8, "identifier", "SSN passed the structural check. Not part of the headline completeness score."),
    ("mrn", 9, "identifier", "An MR identifier was loaded. Not part of the headline completeness score."),
)

GRADE_CATALOG = (
    (
        "certain",
        "Certain",
        1,
        "Score and corroboration are high enough to link without a reviewer.",
    ),
    (
        "probable",
        "Probable",
        2,
        "Close match. A person reviews it before any chart is retired.",
    ),
    (
        "possible",
        "Possible",
        3,
        "Weak match. A person should review it before it is used.",
    ),
    (
        "certainly-not",
        "Certainly not",
        4,
        "Not a match. These pairs are omitted from the fact table.",
    ),
)


def _rate(value: float) -> str:
    return f"{float(value):.6f}"


def _date_key(iso_date: str) -> str:
    return iso_date.replace("-", "")


def _flags(row: sqlite3.Row, has_mrn: bool) -> dict[str, int]:
    return {
        "given_name": 1 if row["given_name_norm"] else 0,
        "family_name": 1 if row["family_name_norm"] else 0,
        "birth_date": 1 if row["birth_date"] else 0,
        "known_gender": 1 if row["gender"] in {"male", "female", "other"} else 0,
        "street": 1 if row["address_line_norm"] else 0,
        "postal_code": 1 if row["postal_code_norm"] else 0,
        "phone": 1 if row["phone_norm"] else 0,
        "ssn": 1 if row["ssn_norm"] else 0,
        "mrn": 1 if has_mrn else 0,
    }


def _age(iso_date: str | None) -> str:
    if not iso_date:
        return ""
    born = date.fromisoformat(iso_date)
    years = AS_OF.year - born.year
    if (AS_OF.month, AS_OF.day) < (born.month, born.day):
        years -= 1
    return str(years)


def _label(row: sqlite3.Row) -> str:
    given = display_name(row["given_name_raw"])
    family = display_name(row["family_name_raw"])
    return " ".join(part for part in (given, family) if part)


def _dim_date_rows() -> list[dict]:
    rows = []
    cursor = WINDOW_START
    while cursor <= WINDOW_END:
        quarter = (cursor.month - 1) // 3 + 1
        rows.append(
            {
                "date_key": _date_key(cursor.isoformat()),
                "full_date": cursor.isoformat(),
                "year": cursor.year,
                "quarter": quarter,
                "year_quarter": f"{cursor.year} Q{quarter}",
                "year_quarter_sort": cursor.year * 10 + quarter,
                "month": cursor.month,
                "month_name": cursor.strftime("%B"),
                "year_month": cursor.strftime("%Y-%m"),
                "year_month_sort": cursor.year * 100 + cursor.month,
                "day": cursor.day,
                "day_name": cursor.strftime("%A"),
                "weekday_number": cursor.weekday() + 1,
            }
        )
        cursor += timedelta(days=1)
    return rows


def export_outputs(
    connection: sqlite3.Connection,
    output_dir: Path,
    metrics: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    patients = list(connection.execute("SELECT * FROM patient ORDER BY record_id"))
    mrn_rows = connection.execute(
        """
        SELECT record_id, system_uri, value
        FROM patient_identifier
        WHERE type_code = 'MR'
        """
    ).fetchall()
    mrn_by_id = {row["record_id"]: row for row in mrn_rows}
    sources = list(connection.execute("SELECT * FROM source_system ORDER BY source_system_key"))
    source_name = {row["source_system_key"]: row["system_name"] for row in sources}

    auto_ids: set[str] = set()
    review_ids: set[str] = set()
    for row in connection.execute("SELECT record_id_1, record_id_2, decision FROM match_pair"):
        target = auto_ids if row["decision"] == "auto_link" else review_ids
        target.add(row["record_id_1"])
        target.add(row["record_id_2"])

    patient_rows = []
    fact_rows = []
    field_rows = []
    by_id = {row["record_id"]: row for row in patients}
    for row in patients:
        mrn = mrn_by_id.get(row["record_id"])
        flags = _flags(row, mrn is not None)
        record_id = row["record_id"]
        in_auto = 1 if record_id in auto_ids else 0
        needs_review = 1 if record_id in review_ids and record_id not in auto_ids else 0
        patient_rows.append(
            {
                "record_id": record_id,
                "fhir_logical_id": row["fhir_logical_id"],
                "mrn_system": "" if mrn is None else mrn["system_uri"],
                "mrn": "" if mrn is None else mrn["value"],
                "scenario_key": row["scenario_key"],
                "source_system_key": row["source_system_key"],
                "source_system_name": source_name[row["source_system_key"]],
                "active": row["active"],
                "gender": row["gender"],
                "birth_date": row["birth_date"] or "",
                "age_years": _age(row["birth_date"]),
                "given_name": display_name(row["given_name_raw"]),
                "family_name": display_name(row["family_name_raw"]),
                "city": display_name(row["city_raw"]),
                "state": row["state_norm"] or "",
                "postal_code": row["postal_code_norm"] or "",
            }
        )
        fact_rows.append(
            {
                "record_id": record_id,
                "scenario_key": row["scenario_key"],
                "source_system_key": row["source_system_key"],
                "date_key": _date_key(row["received_date"]),
                "in_auto_link": in_auto,
                "needs_review": needs_review,
                "active": row["active"],
                "completeness_score": f"{row['completeness_score']:.4f}",
                **{f"has_{name}": flags[name] for name, *_rest in FIELD_CATALOG},
            }
        )
        for field_name, _sort, _group, _description in FIELD_CATALOG:
            field_rows.append(
                {
                    "record_id": record_id,
                    "scenario_key": row["scenario_key"],
                    "source_system_key": row["source_system_key"],
                    "date_key": _date_key(row["received_date"]),
                    "field_key": field_name,
                    "is_present": flags[field_name],
                }
            )

    pair_outcome: dict[tuple[str, str], tuple[str, str]] = {}
    for row in connection.execute(
        "SELECT record_id, other_record_id FROM patient_link WHERE link_type = 'replaces'"
    ):
        survivor = row["record_id"]
        retired = row["other_record_id"]
        pair_outcome[tuple(sorted((survivor, retired)))] = (survivor, retired)

    match_rows = []
    for row in connection.execute("SELECT * FROM match_pair ORDER BY pair_id"):
        left = by_id[row["record_id_1"]]
        right = by_id[row["record_id_2"]]
        later = right if right["received_date"] >= left["received_date"] else left
        outcome = pair_outcome.get((row["record_id_1"], row["record_id_2"]), ("", ""))
        match_rows.append(
            {
                "pair_id": row["pair_id"],
                "scenario_key": left["scenario_key"],
                "record_id_1": row["record_id_1"],
                "record_id_2": row["record_id_2"],
                "date_key": _date_key(later["received_date"]),
                "later_source_system_key": later["source_system_key"],
                "match_grade": row["match_grade"],
                "decision": row["decision"],
                "decision_reason": row["decision_reason"],
                "score": _rate(row["score"]),
                "weight_total": f"{row['weight_total']:.4f}",
                "alignment": row["alignment"],
                "blocked_by": row["blocked_by"],
                "agreed_fields": row["agreed_fields"],
                "record_1_source": source_name[left["source_system_key"]],
                "record_2_source": source_name[right["source_system_key"]],
                "record_1_name": _label(left),
                "record_2_name": _label(right),
                "record_1_mrn": "" if row["record_id_1"] not in mrn_by_id else mrn_by_id[row["record_id_1"]]["value"],
                "record_2_mrn": "" if row["record_id_2"] not in mrn_by_id else mrn_by_id[row["record_id_2"]]["value"],
                "survivor_record_id": outcome[0],
                "retired_record_id": outcome[1],
            }
        )

    issue_rows = []
    for row in connection.execute(
        """
        SELECT i.issue_id, i.record_id, i.issue_type, i.severity,
               p.scenario_key, p.source_system_key, p.received_date
        FROM data_quality_issue i
        JOIN patient p ON p.record_id = i.record_id
        ORDER BY i.issue_id
        """
    ):
        issue_rows.append(
            {
                "issue_id": row["issue_id"],
                "scenario_key": row["scenario_key"],
                "record_id": row["record_id"],
                "source_system_key": row["source_system_key"],
                "date_key": _date_key(row["received_date"]),
                "issue_type": row["issue_type"],
                "severity": row["severity"],
            }
        )

    write_csv(
        output_dir / "dim_patient.csv",
        patient_rows,
        (
            "record_id",
            "fhir_logical_id",
            "mrn_system",
            "mrn",
            "scenario_key",
            "source_system_key",
            "source_system_name",
            "active",
            "gender",
            "birth_date",
            "age_years",
            "given_name",
            "family_name",
            "city",
            "state",
            "postal_code",
        ),
    )
    scenario_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT scenario_key, scenario_name, scenario_sort, description, seed
            FROM scenario
            ORDER BY scenario_sort, scenario_key
            """
        )
    ]
    write_csv(
        output_dir / "dim_scenario.csv",
        scenario_rows,
        ("scenario_key", "scenario_name", "scenario_sort", "description", "seed"),
    )
    write_csv(
        output_dir / "dim_source_system.csv",
        [
            {
                "source_system_key": row["source_system_key"],
                "system_name": row["system_name"],
                "system_uri": row["system_uri"],
                "description": row["description"],
            }
            for row in sources
        ],
        ("source_system_key", "system_name", "system_uri", "description"),
    )
    write_csv(
        output_dir / "dim_date.csv",
        _dim_date_rows(),
        (
            "date_key",
            "full_date",
            "year",
            "quarter",
            "year_quarter",
            "year_quarter_sort",
            "month",
            "month_name",
            "year_month",
            "year_month_sort",
            "day",
            "day_name",
            "weekday_number",
        ),
    )
    write_csv(
        output_dir / "dim_issue_type.csv",
        [
            {
                "issue_type": item.issue_type,
                "severity": item.severity,
                "field_name": item.field_name,
                "cross_record": int(item.cross_record),
                "description": item.description,
            }
            for item in ISSUE_CATALOG.values()
        ],
        ("issue_type", "severity", "field_name", "cross_record", "description"),
    )
    write_csv(
        output_dir / "dim_match_grade.csv",
        [
            {
                "match_grade": grade,
                "grade_name": name,
                "grade_sort": sort,
                "description": description,
            }
            for grade, name, sort, description in GRADE_CATALOG
        ],
        ("match_grade", "grade_name", "grade_sort", "description"),
    )
    write_csv(
        output_dir / "dim_field.csv",
        [
            {
                "field_key": name,
                "field_name": name.replace("_", " ").title(),
                "field_sort": sort,
                "field_group": group,
                "in_core_score": 1 if group == "core" else 0,
                "description": description,
            }
            for name, sort, group, description in FIELD_CATALOG
        ],
        ("field_key", "field_name", "field_sort", "field_group", "in_core_score", "description"),
    )
    fact_columns = (
        "record_id",
        "scenario_key",
        "source_system_key",
        "date_key",
        "in_auto_link",
        "needs_review",
        "active",
        "completeness_score",
        *[f"has_{name}" for name, *_rest in FIELD_CATALOG],
    )
    write_csv(output_dir / "fact_patient.csv", fact_rows, fact_columns)
    write_csv(
        output_dir / "fact_field_completeness.csv",
        field_rows,
        ("record_id", "scenario_key", "source_system_key", "date_key", "field_key", "is_present"),
    )
    write_csv(
        output_dir / "fact_match_pair.csv",
        match_rows,
        (
            "pair_id",
            "scenario_key",
            "record_id_1",
            "record_id_2",
            "date_key",
            "later_source_system_key",
            "match_grade",
            "decision",
            "decision_reason",
            "score",
            "weight_total",
            "alignment",
            "blocked_by",
            "agreed_fields",
            "record_1_source",
            "record_2_source",
            "record_1_name",
            "record_2_name",
            "record_1_mrn",
            "record_2_mrn",
            "survivor_record_id",
            "retired_record_id",
        ),
    )
    write_csv(
        output_dir / "fact_data_quality_issue.csv",
        issue_rows,
        (
            "issue_id",
            "scenario_key",
            "record_id",
            "source_system_key",
            "date_key",
            "issue_type",
            "severity",
        ),
    )

    truth_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT record_id, golden_person_id, is_injected_duplicate, variant,
                   parent_record_id, source_system_key
            FROM eval_ground_truth
            ORDER BY record_id
            """
        )
    ]
    for row in truth_rows:
        row["variant"] = row["variant"] or ""
        row["parent_record_id"] = row["parent_record_id"] or ""
        row["scenario_key"] = by_id[row["record_id"]]["scenario_key"]
    write_csv(
        output_dir / "eval_record.csv",
        truth_rows,
        (
            "scenario_key",
            "record_id",
            "golden_person_id",
            "is_injected_duplicate",
            "variant",
            "parent_record_id",
            "source_system_key",
        ),
    )

    completeness_by_scenario: dict[str, list[float]] = {}
    linked_by_scenario: dict[str, int] = {}
    for row in fact_rows:
        completeness_by_scenario.setdefault(row["scenario_key"], []).append(
            float(row["completeness_score"])
        )
        linked_by_scenario[row["scenario_key"]] = linked_by_scenario.get(
            row["scenario_key"], 0
        ) + int(row["in_auto_link"])

    summaries = []
    curve_rows = []
    variant_rows = []
    histogram_rows = []
    for scenario_result in metrics["scenarios"]:
        auto = scenario_result["auto_link"]
        flagged = scenario_result["flagged"]
        key = scenario_result["scenario_key"]
        scores = completeness_by_scenario.get(key, [])
        mean_completeness = sum(scores) / len(scores) if scores else 0.0
        linked = linked_by_scenario.get(key, 0)
        record_count = scenario_result["total_records"]
        summaries.append(
            {
                "scenario_key": key,
                "total_records": record_count,
                "injected_duplicate_records": scenario_result["injected_duplicate_records"],
                "injected_duplicate_rate": _rate(scenario_result["injected_duplicate_rate"]),
                "true_pairs": scenario_result["true_pairs"],
                "true_pairs_blocked": scenario_result["true_pairs_blocked"],
                "true_pairs_unblocked": scenario_result["true_pairs_unblocked"],
                "auto_link_tp": auto["tp"],
                "auto_link_fp": auto["fp"],
                "auto_link_fn": auto["fn"],
                "auto_link_precision": _rate(auto["precision"]),
                "auto_link_recall": _rate(auto["recall"]),
                "auto_link_f1": _rate(auto["f1"]),
                "flagged_tp": flagged["tp"],
                "flagged_fp": flagged["fp"],
                "flagged_fn": flagged["fn"],
                "flagged_precision": _rate(flagged["precision"]),
                "flagged_recall": _rate(flagged["recall"]),
                "flagged_f1": _rate(flagged["f1"]),
                "auto_link_pairs": scenario_result["auto_link_pairs"],
                "review_pairs": scenario_result["review_pairs"],
                "candidate_pairs": scenario_result["candidate_pairs"],
                "mean_completeness": _rate(mean_completeness),
                "suspected_duplicate_record_rate": _rate(linked / record_count if record_count else 0.0),
            }
        )
        for row in scenario_result["threshold_curve"]:
            curve_rows.append(
                {
                    "scenario_key": key,
                    **row,
                    "threshold": f"{row['threshold']:.2f}",
                    "precision": _rate(row["precision"]),
                    "recall": _rate(row["recall"]),
                    "f1": _rate(row["f1"]),
                }
            )
        for row in scenario_result["by_variant"]:
            variant_rows.append(
                {
                    "scenario_key": key,
                    **row,
                    "auto_link_recall": _rate(row["auto_link_recall"]),
                    "flagged_recall": _rate(row["flagged_recall"]),
                }
            )
        for row in scenario_result["histogram"]:
            histogram_rows.append(
                {
                    "scenario_key": key,
                    **row,
                    "bucket_floor": _rate(row["bucket_floor"]),
                    "bucket_ceiling": _rate(row["bucket_ceiling"]),
                }
            )
    summary_columns = tuple(summaries[0].keys())
    write_csv(output_dir / "scenario_metrics.csv", summaries, summary_columns)
    write_csv(output_dir / "eval_summary.csv", summaries, summary_columns)
    write_csv(
        output_dir / "eval_threshold_metrics.csv",
        curve_rows,
        (
            "scenario_key",
            "threshold",
            "predicted_pairs",
            "true_positives",
            "false_positives",
            "false_negatives",
            "precision",
            "recall",
            "f1",
        ),
    )
    write_csv(
        output_dir / "eval_recall_by_variant.csv",
        variant_rows,
        (
            "scenario_key",
            "variant",
            "true_pairs",
            "auto_link_tp",
            "flagged_tp",
            "auto_link_recall",
            "flagged_recall",
        ),
    )
    write_csv(
        output_dir / "eval_score_histogram.csv",
        histogram_rows,
        (
            "scenario_key",
            "bucket_floor",
            "bucket_ceiling",
            "true_pair_count",
            "false_pair_count",
        ),
    )

    slim_scenarios = []
    for scenario_result in metrics["scenarios"]:
        slim_scenarios.append(
            {
                key: value
                for key, value in scenario_result.items()
                if key not in {"threshold_curve", "histogram", "by_variant"}
            }
        )
    serializable = {
        key: value
        for key, value in metrics.items()
        if key not in {"threshold_curve", "histogram", "scenarios"}
    }
    serializable["scenarios"] = slim_scenarios
    (output_dir / "metrics.json").write_text(
        json.dumps(serializable, indent=2) + "\n",
        encoding="utf-8",
    )
