"""Create the SQLite database and load cleaned charts."""

import sqlite3
from pathlib import Path

from empi.config import SOURCES, SQL_DIR, SSN_SYSTEM
from empi.models import CleanedRecord, LinkRow, MatchFeatures, PairScore, TruthRow


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def connect(db_path: Path) -> sqlite3.Connection:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    return connection


def insert_scenarios(connection: sqlite3.Connection, rows: list[dict]) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO scenario (
            scenario_key, scenario_name, scenario_sort, description, seed
        ) VALUES (
            :scenario_key, :scenario_name, :scenario_sort, :description, :seed
        )
        """,
        rows,
    )


def insert_records(connection: sqlite3.Connection, records: list[CleanedRecord]) -> None:
    insert_scenarios(
        connection,
        [
            {
                "scenario_key": key,
                "scenario_name": key.replace("_", " ").title(),
                "scenario_sort": 0,
                "description": "",
                "seed": 0,
            }
            for key in sorted({record.scenario_key for record in records})
        ],
    )
    connection.executemany(
        """
        INSERT INTO source_system (source_system_key, system_uri, system_name, description)
        VALUES (:source_system_key, :system_uri, :system_name, :description)
        """,
        [
            {"source_system_key": key, **meta}
            for key, meta in SOURCES.items()
        ],
    )
    connection.executemany(
        """
        INSERT INTO patient (
            record_id, fhir_logical_id, scenario_key, source_system_key, active, gender, gender_raw,
            birth_date, birth_date_raw, received_date, given_name_raw, family_name_raw,
            middle_name_raw, given_name_norm, family_name_norm, middle_name_norm, name_use,
            phone_raw, phone_norm, email_raw, ssn_raw, ssn_norm, address_line_raw,
            address_line_norm, city_raw, city_norm, state_raw, state_norm,
            postal_code_raw, postal_code_norm, completeness_score
        ) VALUES (
            :record_id, :fhir_logical_id, :scenario_key, :source_system_key, :active, :gender, :gender_raw,
            :birth_date, :birth_date_raw, :received_date, :given_name_raw, :family_name_raw,
            :middle_name_raw, :given_name_norm, :family_name_norm, :middle_name_norm, :name_use,
            :phone_raw, :phone_norm, :email_raw, :ssn_raw, :ssn_norm, :address_line_raw,
            :address_line_norm, :city_raw, :city_norm, :state_raw, :state_norm,
            :postal_code_raw, :postal_code_norm, :completeness_score
        )
        """,
        [_patient_params(record) for record in records],
    )
    identifiers = []
    names = []
    telecoms = []
    addresses = []
    for record in records:
        system_uri = SOURCES[record.source_system_key]["system_uri"]
        if record.mrn:
            identifiers.append(
                {
                    "record_id": record.record_id,
                    "system_uri": system_uri,
                    "value": record.mrn,
                    "type_code": "MR",
                }
            )
        if record.ssn_norm:
            identifiers.append(
                {
                    "record_id": record.record_id,
                    "system_uri": SSN_SYSTEM,
                    "value": record.ssn_norm,
                    "type_code": "SS",
                }
            )
        names.append(
            {
                "record_id": record.record_id,
                "use_code": record.name_use,
                "family_raw": _text(record.family_name_raw),
                "given_raw": _text(record.given_name_raw),
                "middle_raw": _text(record.middle_name_raw),
                "family_norm": _text(record.family_name_norm),
                "given_norm": _text(record.given_name_norm),
            }
        )
        if record.phone_raw or record.phone_norm:
            telecoms.append(
                {
                    "record_id": record.record_id,
                    "system_code": "phone",
                    "value_raw": _text(record.phone_raw),
                    "value_norm": record.phone_norm,
                    "use_code": "home",
                }
            )
        if record.email_raw:
            telecoms.append(
                {
                    "record_id": record.record_id,
                    "system_code": "email",
                    "value_raw": record.email_raw,
                    "value_norm": record.email_raw.lower(),
                    "use_code": "home",
                }
            )
        addresses.append(
            {
                "record_id": record.record_id,
                "use_code": "home",
                "line_raw": _text(record.address_line_raw),
                "line_norm": _text(record.address_line_norm),
                "city_raw": _text(record.city_raw),
                "city_norm": _text(record.city_norm),
                "state_raw": _text(record.state_raw),
                "state_norm": _text(record.state_norm),
                "postal_code_raw": _text(record.postal_code_raw),
                "postal_code_norm": record.postal_code_norm,
            }
        )
    connection.executemany(
        """
        INSERT INTO patient_identifier (record_id, system_uri, value, type_code)
        VALUES (:record_id, :system_uri, :value, :type_code)
        """,
        identifiers,
    )
    connection.executemany(
        """
        INSERT INTO patient_name (
            record_id, use_code, family_raw, given_raw, middle_raw, family_norm, given_norm
        ) VALUES (
            :record_id, :use_code, :family_raw, :given_raw, :middle_raw, :family_norm, :given_norm
        )
        """,
        names,
    )
    connection.executemany(
        """
        INSERT INTO patient_telecom (record_id, system_code, value_raw, value_norm, use_code)
        VALUES (:record_id, :system_code, :value_raw, :value_norm, :use_code)
        """,
        telecoms,
    )
    connection.executemany(
        """
        INSERT INTO patient_address (
            record_id, use_code, line_raw, line_norm, city_raw, city_norm,
            state_raw, state_norm, postal_code_raw, postal_code_norm
        ) VALUES (
            :record_id, :use_code, :line_raw, :line_norm, :city_raw, :city_norm,
            :state_raw, :state_norm, :postal_code_raw, :postal_code_norm
        )
        """,
        addresses,
    )


def _patient_params(record: CleanedRecord) -> dict:
    return {
        "record_id": record.record_id,
        "fhir_logical_id": record.fhir_logical_id,
        "scenario_key": record.scenario_key,
        "source_system_key": record.source_system_key,
        "active": record.active,
        "gender": record.gender,
        "gender_raw": _text(record.gender_raw),
        "birth_date": record.birth_date,
        "birth_date_raw": _text(record.birth_date_raw),
        "received_date": record.received_date,
        "given_name_raw": _text(record.given_name_raw),
        "family_name_raw": _text(record.family_name_raw),
        "middle_name_raw": _text(record.middle_name_raw),
        "given_name_norm": _text(record.given_name_norm),
        "family_name_norm": _text(record.family_name_norm),
        "middle_name_norm": _text(record.middle_name_norm),
        "name_use": record.name_use,
        "phone_raw": _text(record.phone_raw),
        "phone_norm": record.phone_norm,
        "email_raw": _text(record.email_raw),
        "ssn_raw": _text(record.ssn_raw),
        "ssn_norm": record.ssn_norm,
        "address_line_raw": _text(record.address_line_raw),
        "address_line_norm": _text(record.address_line_norm),
        "city_raw": _text(record.city_raw),
        "city_norm": _text(record.city_norm),
        "state_raw": _text(record.state_raw),
        "state_norm": _text(record.state_norm),
        "postal_code_raw": _text(record.postal_code_raw),
        "postal_code_norm": record.postal_code_norm,
        "completeness_score": record.completeness_score,
    }


def load_features(connection: sqlite3.Connection) -> list[MatchFeatures]:
    rows = connection.execute(
        """
        SELECT record_id, scenario_key, source_system_key, given_name_norm, family_name_norm,
               birth_date, ssn_norm, phone_norm, address_line_norm, postal_code_norm,
               gender, received_date, completeness_score, active
        FROM patient
        """
    ).fetchall()
    features = []
    for row in rows:
        birth = row["birth_date"]
        features.append(
            MatchFeatures(
                record_id=row["record_id"],
                source_system_key=row["source_system_key"],
                given_norm=row["given_name_norm"] or "",
                family_norm=row["family_name_norm"] or "",
                birth_date=birth,
                birth_year=birth[:4] if birth else None,
                ssn_norm=row["ssn_norm"],
                phone_norm=row["phone_norm"],
                street_norm=row["address_line_norm"] or "",
                postal_norm=row["postal_code_norm"],
                gender=row["gender"],
                received_date=row["received_date"],
                completeness=row["completeness_score"],
                active=row["active"],
                scenario_key=row["scenario_key"],
            )
        )
    return features


def insert_pairs(connection: sqlite3.Connection, pairs: list[PairScore]) -> None:
    kept = [pair for pair in pairs if pair.decision != "non_match"]
    connection.executemany(
        """
        INSERT INTO match_pair (
            record_id_1, record_id_2, score, weight_total, match_grade, decision,
            decision_reason, alignment, blocked_by, agreed_fields
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                pair.record_id_1,
                pair.record_id_2,
                round(pair.score, 6),
                round(pair.weight, 4),
                pair.match_grade,
                pair.decision,
                pair.decision_reason,
                pair.alignment,
                pair.blocked_by,
                pair.agreed_fields,
            )
            for pair in kept
        ],
    )


def insert_links(connection: sqlite3.Connection, links: list[LinkRow]) -> None:
    connection.executemany(
        """
        INSERT INTO patient_link (
            record_id, other_record_id, link_type, score, match_grade
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                link.record_id,
                link.other_record_id,
                link.link_type,
                round(link.score, 6),
                link.match_grade,
            )
            for link in links
        ],
    )


def retire_records(connection: sqlite3.Connection, record_ids: list[str]) -> None:
    connection.executemany(
        "UPDATE patient SET active = 0 WHERE record_id = ?",
        [(record_id,) for record_id in record_ids],
    )


def insert_ground_truth(connection: sqlite3.Connection, rows: list[TruthRow]) -> None:
    connection.executemany(
        """
        INSERT INTO eval_ground_truth (
            record_id, golden_person_id, is_injected_duplicate, variant,
            parent_record_id, source_system_key
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.source_record_id,
                row.golden_person_id,
                row.is_injected_duplicate,
                row.variant or None,
                row.parent_record_id or None,
                row.source_system,
            )
            for row in rows
        ],
    )
