from dataclasses import replace
from pathlib import Path

import pytest

from empi.match import blocking_keys
from empi.models import MatchFeatures
from empi.pipeline import run_pipeline
from empi.scenarios import all_scenarios, resolve_scenarios
from tests.test_match import features


def test_catalog_rates_match_the_dashboard_story():
    specs = {spec.key: spec for spec in all_scenarios()}
    assert set(specs) == {"baseline", "merger", "messy_entry", "hard_cases", "lab_migration"}
    assert 0.018 <= specs["baseline"].injected_rate <= 0.025
    assert 0.08 <= specs["merger"].injected_rate <= 0.10
    assert specs["messy_entry"].noise.ssn_missing > specs["baseline"].noise.ssn_missing
    assert specs["hard_cases"].household_pairs > 0
    assert specs["hard_cases"].twin_pairs_blank_ssn > 0
    assert specs["lab_migration"].damage_lab
    assert [spec.sort for spec in all_scenarios()] == [1, 2, 3, 4, 5]


def test_size_overrides_require_one_scenario():
    with pytest.raises(ValueError):
        resolve_scenarios(
            scenario=None,
            all_scenarios_flag=True,
            persons=100,
            duplicates=None,
            seed=None,
        )
    with pytest.raises(ValueError):
        resolve_scenarios(
            scenario="baseline",
            all_scenarios_flag=True,
            persons=None,
            duplicates=None,
            seed=None,
        )


def test_blocking_keys_do_not_cross_scenarios():
    left = features(scenario_key="baseline")
    right = features(record_id="LAB-000009", scenario_key="hard_cases")
    assert set(blocking_keys(left)).isdisjoint(blocking_keys(right))


def test_two_scenarios_stay_separate_and_lookalikes_create_false_links(tmp_path: Path):
    hard = replace(
        next(spec for spec in all_scenarios() if spec.key == "hard_cases"),
        persons=120,
        duplicates=6,
        twin_pairs_blank_ssn=2,
        twin_pairs_conflict_ssn=1,
        household_pairs=2,
        common_name_rate=0.3,
        seed=5,
    )
    baseline = replace(
        next(spec for spec in all_scenarios() if spec.key == "baseline"),
        persons=80,
        duplicates=4,
        seed=6,
    )
    metrics = run_pipeline(
        scenarios=[baseline, hard],
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "empi.db",
    )
    by_key = {row["scenario_key"]: row for row in metrics["scenarios"]}
    assert by_key["hard_cases"]["auto_link"]["fp"] >= 1
    assert by_key["baseline"]["auto_link"]["fp"] == 0
    from empi.csvio import read_csv

    pairs = read_csv(tmp_path / "outputs" / "fact_match_pair.csv")
    patients = {row["record_id"]: row["scenario_key"] for row in read_csv(tmp_path / "outputs" / "dim_patient.csv")}
    for pair in pairs:
        assert patients[pair["record_id_1"]] == patients[pair["record_id_2"]] == pair["scenario_key"]
    assert {row["scenario_key"] for row in read_csv(tmp_path / "outputs" / "dim_scenario.csv")} == {
        "baseline",
        "hard_cases",
    }


def test_features_default_scenario_is_baseline():
    assert MatchFeatures(
        record_id="A",
        source_system_key="registration",
        given_norm="ANN",
        family_norm="LEE",
        birth_date="1980-01-02",
        birth_year="1980",
        ssn_norm=None,
        phone_norm=None,
        street_norm="",
        postal_norm=None,
        gender="female",
        received_date="2025-01-01",
        completeness=1,
        active=1,
    ).scenario_key == "baseline"
