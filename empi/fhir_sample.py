"""Write a few FHIR R4 Patient/$match examples from real pipeline pairs.

The JSON follows the shape of a Parameters request and a searchset Bundle.
It is a sample file, not a response from a FHIR server. Scores and grades come
from this project's matcher.
"""

import json
import sqlite3
from pathlib import Path

from empi.config import (
    IDENTIFIER_TYPE_SYSTEM,
    MATCH_GRADE_EXTENSION,
    SSN_SYSTEM,
    SOURCES,
)
from empi.models import PairScore
from empi.standardize import display_name


def _coding(code: str) -> dict:
    return {
        "coding": [
            {
                "system": IDENTIFIER_TYPE_SYSTEM,
                "code": code,
            }
        ]
    }


def patient_resource(connection: sqlite3.Connection, record_id: str) -> dict:
    row = connection.execute(
        "SELECT * FROM patient WHERE record_id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        raise KeyError(record_id)
    resource: dict = {
        "resourceType": "Patient",
        "id": row["fhir_logical_id"],
        "active": bool(row["active"]),
        "gender": row["gender"],
    }
    identifiers = []
    for identifier in connection.execute(
        """
        SELECT system_uri, value, type_code
        FROM patient_identifier
        WHERE record_id = ?
        ORDER BY type_code
        """,
        (record_id,),
    ):
        entry = {
            "system": identifier["system_uri"],
            "value": identifier["value"],
            "type": _coding(identifier["type_code"]),
        }
        if identifier["type_code"] == "MR":
            entry["assigner"] = {"display": "Lakeside Health (fictional)"}
        identifiers.append(entry)
    if identifiers:
        resource["identifier"] = identifiers
    given = [part for part in (display_name(row["given_name_raw"]), display_name(row["middle_name_raw"])) if part]
    family = display_name(row["family_name_raw"])
    if given or family:
        name = {"use": row["name_use"]}
        if family:
            name["family"] = family
        if given:
            name["given"] = given
        resource["name"] = [name]
    telecom = []
    for contact in connection.execute(
        """
        SELECT system_code, value_raw, use_code
        FROM patient_telecom
        WHERE record_id = ?
        ORDER BY system_code
        """,
        (record_id,),
    ):
        if contact["value_raw"]:
            telecom.append(
                {
                    "system": contact["system_code"],
                    "value": contact["value_raw"],
                    "use": contact["use_code"],
                }
            )
    if telecom:
        resource["telecom"] = telecom
    if row["birth_date"]:
        resource["birthDate"] = row["birth_date"]
    if row["address_line_raw"] or row["city_raw"] or row["postal_code_norm"]:
        address: dict = {"use": "home"}
        if row["address_line_raw"]:
            address["line"] = [row["address_line_raw"]]
        if row["city_raw"]:
            address["city"] = row["city_raw"]
        if row["state_norm"]:
            address["state"] = row["state_norm"]
        if row["postal_code_norm"]:
            address["postalCode"] = row["postal_code_norm"]
        resource["address"] = [address]
    links = []
    for link in connection.execute(
        """
        SELECT l.link_type, o.fhir_logical_id
        FROM patient_link l
        JOIN patient o ON o.record_id = l.other_record_id
        WHERE l.record_id = ?
        ORDER BY l.link_type, o.fhir_logical_id
        """,
        (record_id,),
    ):
        links.append(
            {
                "other": {"reference": f"Patient/{link['fhir_logical_id']}"},
                "type": link["link_type"],
            }
        )
    if links:
        resource["link"] = links
    return resource


def _parameters(resource: dict) -> dict:
    return {
        "resourceType": "Parameters",
        "parameter": [
            {"name": "resource", "resource": resource},
            {"name": "onlyCertainMatches", "valueBoolean": False},
            {"name": "count", "valueInteger": 5},
        ],
    }


def _bundle(candidate: dict, score: float, grade: str) -> dict:
    bounded = max(0.0, min(1.0, round(score, 4)))
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [
            {
                "fullUrl": f"http://lakeside.example.org/fhir/Patient/{candidate['id']}",
                "resource": candidate,
                "search": {
                    "mode": "match",
                    "score": bounded,
                    "extension": [
                        {
                            "url": MATCH_GRADE_EXTENSION,
                            "valueCode": grade,
                        }
                    ],
                },
            }
        ],
    }


def _submitted_id(connection: sqlite3.Connection, pair: PairScore) -> str:
    row = connection.execute(
        """
        SELECT record_id
        FROM patient_link
        WHERE record_id IN (?, ?)
          AND link_type = 'replaced-by'
        """,
        (pair.record_id_1, pair.record_id_2),
    ).fetchone()
    if row:
        return row["record_id"]
    return pair.record_id_2


def write_match_examples(
    connection: sqlite3.Connection,
    pairs: list[PairScore],
    path: Path,
) -> None:
    auto = [pair for pair in pairs if pair.decision == "auto_link"]
    review = [pair for pair in pairs if pair.decision == "manual_review"]
    chosen: list[tuple[str, PairScore]] = []
    if auto:
        chosen.append(("Auto-link. Match grade certain.", max(auto, key=lambda pair: pair.score)))
    if review:
        chosen.append(
            (
                "Manual review. No Patient.link is written until a person confirms the pair.",
                max(review, key=lambda pair: pair.score),
            )
        )
    examples = []
    for label, pair in chosen:
        submitted_id = _submitted_id(connection, pair)
        other_id = pair.record_id_1 if submitted_id == pair.record_id_2 else pair.record_id_2
        submitted = patient_resource(connection, submitted_id)
        # The request illustrates the inbound chart before the server assigns links.
        request_patient = {key: value for key, value in submitted.items() if key != "link"}
        candidate = patient_resource(connection, other_id)
        candidate.pop("link", None)
        example = {
            "label": label,
            "decision": pair.decision,
            "decision_reason": pair.decision_reason,
            "agreed_fields": pair.agreed_fields,
            "request": _parameters(request_patient),
            "response": _bundle(candidate, pair.score, pair.match_grade),
        }
        if pair.decision == "auto_link":
            example["patients_after_link"] = [
                patient_resource(connection, submitted_id),
                patient_resource(connection, other_id),
            ]
        examples.append(example)
    document = {
        "note": (
            "Synthetic data. These objects follow the shape of a FHIR R4 "
            "Patient/$match request and searchset response. They were written "
            "by this project. They are not a live server response. "
            f"MRN systems look like {next(iter(SOURCES.values()))['system_uri']}. "
            f"SSN identifiers use {SSN_SYSTEM} and the values are fabricated."
        ),
        "examples": examples,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
