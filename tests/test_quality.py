from pathlib import Path

from empi.config import DUPLICATE_COUNT, GENDER_RAW_TOKENS, PERSON_COUNT, SQL_DIR, VARIANT_WEIGHTS
from empi.generate import allocate_variants
from empi.load import connect, insert_records
from empi.models import RawRecord
from empi.quality import run_issue_queries
from empi.sqlutil import load_named_sql
from empi.standardize import clean_record


def _raw(**overrides) -> RawRecord:
    base = dict(
        source_record_id="REG-000001",
        source_system="registration",
        mrn="R0000001",
        name_use="official",
        first_name="William",
        middle_name="A",
        last_name="Smith",
        birth_date="1980-04-15",
        sex="M",
        ssn="123-45-6789",
        phone="(415) 555-0134",
        email="william.smith@example.com",
        address="123 Main Street",
        city="Austin",
        state="Texas",
        zip="78701",
        active="Y",
        received_date="2025-03-01",
    )
    base.update(overrides)
    return RawRecord(**base)


def test_variant_weights_and_default_duplicate_rate():
    assert sum(weight for _, weight in VARIANT_WEIGHTS) == DUPLICATE_COUNT
    allocated = allocate_variants(DUPLICATE_COUNT)
    assert len(allocated) == DUPLICATE_COUNT
    assert allocated.count("name_dob_only") == 10
    rate = DUPLICATE_COUNT / (PERSON_COUNT + DUPLICATE_COUNT)
    assert 0.018 <= rate <= 0.025


def test_sql_issue_names_match_the_catalog_and_gender_tokens():
    queries = load_named_sql(SQL_DIR / "data_quality_queries.sql")
    issue_queries = [query for query in queries if query.kind == "issue"]
    assert issue_queries
    from empi.issues import ISSUE_CATALOG

    for query in issue_queries:
        assert query.name in ISSUE_CATALOG
        assert f"'{query.name}'" in query.sql
    gender_sql = next(query.sql for query in issue_queries if query.name == "unrecognized_gender")
    for token in GENDER_RAW_TOKENS:
        assert f"'{token}'" in gender_sql


def test_issue_queries_flag_planted_defects(tmp_path: Path):
    records = [
        clean_record(_raw()),
        clean_record(
            _raw(
                source_record_id="LAB-000001",
                source_system="lab",
                mrn="L0000001",
                last_name="",
                ssn="000-00-0000",
                phone="CALL OFFICE",
                birth_date="02/31/1980",
                sex="N/A",
            )
        ),
        clean_record(
            _raw(
                source_record_id="BIL-000001",
                source_system="billing",
                mrn="B0000001",
                first_name="Helen",
                last_name="Garcia",
                birth_date="1972-01-09",
                ssn="123-45-6789",
                phone="(212) 555-0199",
            )
        ),
        clean_record(
            _raw(
                source_record_id="REG-000002",
                source_system="registration",
                mrn="",
                first_name="Helen",
                last_name="Garcia",
                birth_date="1972-01-09",
                ssn="",
                phone="",
            )
        ),
    ]
    connection = connect(tmp_path / "empi.db")
    try:
        with connection:
            insert_records(connection, records)
            inserted = run_issue_queries(connection)
        assert inserted > 0
        types = {
            row["issue_type"]
            for row in connection.execute("SELECT DISTINCT issue_type FROM data_quality_issue")
        }
        assert "missing_family_name" in types
        assert "invalid_ssn" in types
        assert "invalid_phone" in types
        assert "invalid_birth_date" in types
        assert "unrecognized_gender" in types
        assert "missing_mrn" in types
        assert "shared_ssn" in types
        assert "exact_name_and_dob" in types
        columns = [row[1] for row in connection.execute("PRAGMA table_info(patient)")]
        assert "golden_person_id" not in columns
        assert "fhir_logical_id" in columns
    finally:
        connection.close()


def test_matcher_does_not_read_the_answer_key():
    text = Path("empi/match.py").read_text(encoding="utf-8")
    assert "ground_truth" not in text
    assert "golden_person" not in text
