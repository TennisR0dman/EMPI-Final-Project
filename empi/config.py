"""Run settings for the synthetic Lakeside Health EMPI project.

Lakeside Health is fictional. Every default below is a modeling choice for this
portfolio dataset, not a hospital policy.
"""

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "synthetic"
OUTPUT_DIR = ROOT / "outputs"
DB_PATH = ROOT / "data" / "empi.db"
SQL_DIR = ROOT / "sql"

SEED = 42
PERSON_COUNT = 8000
DUPLICATE_COUNT = 170

# Fixed "today" so age and future-date checks do not drift between runs.
AS_OF = date(2026, 11, 15)
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 10, 31)

# Prior probability that a blocked pair is a true match. Used only to turn a
# log-likelihood ratio into a 0-1 score. It is not estimated from production data.
PRIOR = 0.02

SCORE_CERTAIN = 0.95
SCORE_PROBABLE = 0.78
SCORE_POSSIBLE = 0.55

BLOCK_CAP = 50
IDENTIFIER_BLOCK_CAP = 8

# m = P(field agrees | true match), u = P(field agrees | non-match)
# among blocked candidate pairs, not in the general population.
# These are stated parameters, not an EM fit.
FIELD_M_U: dict[str, tuple[float, float]] = {
    "given": (0.94, 0.10),
    "family": (0.92, 0.12),
    "dob": (0.90, 0.02),
    "ssn": (0.70, 0.0002),
    "phone": (0.72, 0.004),
    "street": (0.78, 0.03),
    "postal": (0.84, 0.10),
    "gender": (0.98, 0.50),
}

SOURCE_PRIORITY = {"registration": 0, "billing": 1, "lab": 2}

SOURCES: dict[str, dict[str, str]] = {
    "registration": {
        "system_name": "Registration",
        "system_uri": "http://lakeside.example.org/identifier/mrn-registration",
        "description": "Fictional hospital registration demographic extract.",
        "file_name": "registration.csv",
        "prefix": "REG",
        "mrn_prefix": "R",
    },
    "lab": {
        "system_name": "Laboratory",
        "system_uri": "http://lakeside.example.org/identifier/mrn-lab",
        "description": "Fictional laboratory patient-demographic extract.",
        "file_name": "lab.csv",
        "prefix": "LAB",
        "mrn_prefix": "L",
    },
    "billing": {
        "system_name": "Billing",
        "system_uri": "http://lakeside.example.org/identifier/mrn-billing",
        "description": "Fictional billing-account demographic extract.",
        "file_name": "billing.csv",
        "prefix": "BIL",
        "mrn_prefix": "B",
    },
}

SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
IDENTIFIER_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
MATCH_GRADE_SYSTEM = "http://terminology.hl7.org/CodeSystem/match-grade"
MATCH_GRADE_EXTENSION = "http://hl7.org/fhir/StructureDefinition/match-grade"

# Weights sum to DUPLICATE_COUNT. Largest-remainder allocation scales them.
VARIANT_WEIGHTS: list[tuple[str, int]] = [
    ("typo_family", 20),
    ("typo_given", 14),
    ("nickname", 20),
    ("transposed_dob", 20),
    ("swapped_names", 14),
    ("missing_ssn", 14),
    ("missing_phone", 14),
    ("address_format", 15),
    ("maiden_name", 14),
    ("phone_format", 8),
    ("combined", 7),
    # Name and birth date agree, but phone, SSN, and address do not.
    # The policy should queue these instead of auto-linking them.
    ("name_dob_only", 10),
]

CORE_FIELDS = (
    "given_name",
    "family_name",
    "birth_date",
    "known_gender",
    "street",
    "postal_code",
)
EXTRA_FIELDS = ("phone", "ssn", "mrn")

GENDER_RAW_TOKENS = (
    "M",
    "MALE",
    "F",
    "FEMALE",
    "O",
    "OTHER",
    "X",
    "NONBINARY",
    "NON-BINARY",
    "U",
    "UNK",
    "UNKNOWN",
)
