from pathlib import Path

from empi.csvio import read_csv
from empi.generate import generate_dataset
from empi.pipeline import run_pipeline


def test_generation_is_deterministic(tmp_path: Path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    generate_dataset(first, persons=40, duplicates=4, seed=7)
    generate_dataset(second, persons=40, duplicates=4, seed=7)
    for name in ("registration.csv", "lab.csv", "billing.csv", "ground_truth.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_small_pipeline_exports_a_consistent_star_schema(tmp_path: Path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "outputs"
    metrics = run_pipeline(
        persons=360,
        duplicates=12,
        seed=42,
        data_dir=data_dir,
        output_dir=output_dir,
        db_path=tmp_path / "empi.db",
    )
    header = (data_dir / "registration.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "golden" not in header
    assert "variant" not in header

    auto = metrics["auto_link"]
    flagged = metrics["flagged"]
    assert auto["precision"] >= 0.9
    assert flagged["recall"] >= 0.85
    assert metrics["true_pairs"] == 12
    assert metrics["injected_duplicate_records"] == 12

    patients = read_csv(output_dir / "dim_patient.csv")
    sources = {row["source_system_key"] for row in read_csv(output_dir / "dim_source_system.csv")}
    dates = {row["date_key"] for row in read_csv(output_dir / "dim_date.csv")}
    grades = {row["match_grade"] for row in read_csv(output_dir / "dim_match_grade.csv")}
    issue_types = {row["issue_type"] for row in read_csv(output_dir / "dim_issue_type.csv")}
    fields = {row["field_key"] for row in read_csv(output_dir / "dim_field.csv")}
    patient_ids = {row["record_id"] for row in patients}
    assert len(patient_ids) == len(read_csv(output_dir / "fact_patient.csv"))
    for row in patients:
        assert row["fhir_logical_id"].startswith("pat-")
        assert row["fhir_logical_id"] != row["mrn"]
        if row["mrn"]:
            assert row["mrn"] not in row["fhir_logical_id"]

    for row in read_csv(output_dir / "fact_patient.csv"):
        assert row["record_id"] in patient_ids
        assert row["source_system_key"] in sources
        assert row["date_key"] in dates
    for row in read_csv(output_dir / "fact_match_pair.csv"):
        assert row["record_id_1"] in patient_ids
        assert row["record_id_2"] in patient_ids
        assert row["match_grade"] in grades
        assert row["date_key"] in dates
        assert row["later_source_system_key"] in sources
    for row in read_csv(output_dir / "fact_data_quality_issue.csv"):
        assert row["issue_type"] in issue_types
        assert row["record_id"] in patient_ids
    for row in read_csv(output_dir / "fact_field_completeness.csv"):
        assert row["field_key"] in fields
        assert row["record_id"] in patient_ids

    summary = read_csv(output_dir / "eval_summary.csv")
    assert len(summary) == 1
    assert summary[0]["scenario_key"] == "baseline"
    assert summary[0]["auto_link_tp"] == str(auto["tp"])
    scenarios = read_csv(output_dir / "dim_scenario.csv")
    assert [row["scenario_key"] for row in scenarios] == ["baseline"]
    metrics_table = read_csv(output_dir / "scenario_metrics.csv")
    assert metrics_table[0]["scenario_key"] == "baseline"
    assert "auto_link_precision" in metrics_table[0]
    assert "mean_completeness" in metrics_table[0]
    assert all(row["scenario_key"] == "baseline" for row in read_csv(output_dir / "fact_patient.csv"))
    assert (output_dir / "match_examples.json").exists()
    assert (output_dir / "query_results" / "records_per_source.csv").exists()
    assert (output_dir / "metrics.json").exists()
