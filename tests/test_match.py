from empi.match import (
    blocking_keys,
    choose_survivor,
    score_pair,
)
from empi.models import MatchFeatures


def features(**overrides) -> MatchFeatures:
    base = dict(
        record_id="REG-000001",
        source_system_key="registration",
        given_norm="WILLIAM",
        family_norm="SMITH",
        birth_date="1980-04-15",
        birth_year="1980",
        ssn_norm="123456789",
        phone_norm="4155550134",
        street_norm="123 MAIN ST",
        postal_norm="78701",
        gender="male",
        received_date="2025-03-01",
        completeness=1.0,
        active=1,
    )
    base.update(overrides)
    return MatchFeatures(**base)


def test_exact_demographics_auto_link():
    pair = score_pair(features(), features(record_id="LAB-000009"))
    assert pair.decision == "auto_link"
    assert pair.match_grade == "certain"
    assert pair.record_id_1 < pair.record_id_2


def test_nickname_and_transposed_dob_and_swap_and_maiden_auto_link():
    nickname = score_pair(
        features(),
        features(record_id="LAB-000002", given_norm="BILL"),
    )
    transposed = score_pair(
        features(birth_date="1980-04-11", birth_year="1980"),
        features(record_id="LAB-000003", birth_date="1980-11-04", birth_year="1980"),
    )
    swapped = score_pair(
        features(),
        features(record_id="BIL-000004", given_norm="SMITH", family_norm="WILLIAM"),
    )
    maiden = score_pair(
        features(),
        features(record_id="BIL-000005", family_norm="GARCIA"),
    )
    assert nickname.decision == "auto_link"
    assert transposed.decision == "auto_link"
    assert transposed.alignment == "direct"
    assert swapped.decision == "auto_link"
    assert swapped.alignment == "swapped"
    assert maiden.decision == "auto_link"


def test_name_and_dob_without_a_second_identifier_stay_in_review():
    pair = score_pair(
        features(),
        features(
            record_id="LAB-000008",
            ssn_norm=None,
            phone_norm=None,
            street_norm="500 OTHER RD",
            postal_norm="82999",
        ),
    )
    assert pair.decision == "manual_review"
    assert pair.match_grade == "probable"
    assert pair.decision_reason in {
        "high_score_without_corroboration",
        "probable_band",
    }


def test_conflicts_are_not_auto_linked():
    gender = score_pair(features(), features(record_id="LAB-000006", gender="female"))
    ssn = score_pair(
        features(),
        features(record_id="LAB-000007", ssn_norm="321456780"),
    )
    assert gender.decision == "manual_review"
    assert gender.decision_reason == "identity_conflict"
    assert ssn.decision != "auto_link"


def test_unrelated_people_are_non_matches():
    pair = score_pair(
        features(),
        features(
            record_id="LAB-000010",
            given_norm="HELEN",
            family_norm="GARCIA",
            birth_date="1971-02-02",
            birth_year="1971",
            ssn_norm="234567890",
            phone_norm="2125550199",
            street_norm="9 OAK AVE",
            postal_norm="10001",
            gender="female",
        ),
    )
    assert pair.decision == "non_match"
    assert pair.score < 0.55


def test_blocking_keys_cover_nickname_and_maiden_cases():
    original = features()
    nickname = features(record_id="LAB-000002", given_norm="BILL")
    maiden = features(
        record_id="BIL-000005",
        family_norm="GARCIA",
        birth_date="1980-04-15",
    )
    assert set(blocking_keys(original)) & set(blocking_keys(nickname))
    shared = set(blocking_keys(original)) & set(blocking_keys(maiden))
    assert any(key.startswith("gdb:") or key.startswith("ssn:") or key.startswith("ph:") for key in shared)


def test_later_equally_complete_chart_survives():
    earlier = features(record_id="REG-000001", received_date="2025-01-01")
    later = features(record_id="LAB-000009", received_date="2025-08-01", source_system_key="lab")
    assert choose_survivor([earlier, later]).record_id == "LAB-000009"
    thinner = features(
        record_id="BIL-000003",
        received_date="2025-09-01",
        completeness=0.5,
    )
    assert choose_survivor([earlier, thinner]).record_id == "REG-000001"


def test_more_agreement_scores_higher_than_less():
    strong = score_pair(features(), features(record_id="LAB-000002"))
    weak = score_pair(
        features(),
        features(record_id="LAB-000002", phone_norm=None, ssn_norm=None, street_norm=""),
    )
    assert strong.score > weak.score
