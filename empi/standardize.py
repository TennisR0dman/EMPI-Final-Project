"""Standardize raw source fields into comparison values.

Rules are deliberately explicit. Tests cover each one. Display values keep the
source text; norms are what matching and the SQL quality checks use.
"""

import re
import unicodedata
from datetime import date, datetime

from empi.config import AS_OF, CORE_FIELDS, GENDER_RAW_TOKENS
from empi.models import CleanedRecord, RawRecord
from empi.nicknames import canonical_given

_MISSING = {"", "NA", "N/A", "NONE", "NULL", "UNKNOWN", "UNK", "-", "--"}
_PREFIXES = {"MR", "MRS", "MS", "DR", "MISS"}
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}

_GENDER_MAP = {
    "M": "male",
    "MALE": "male",
    "F": "female",
    "FEMALE": "female",
    "O": "other",
    "OTHER": "other",
    "X": "other",
    "NONBINARY": "other",
    "NON-BINARY": "other",
    "U": "unknown",
    "UNK": "unknown",
    "UNKNOWN": "unknown",
}

_ADDRESS_TOKENS = {
    "STREET": "ST",
    "STR": "ST",
    "AVENUE": "AVE",
    "ROAD": "RD",
    "DRIVE": "DR",
    "BOULEVARD": "BLVD",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
    "TERRACE": "TER",
    "CIRCLE": "CIR",
    "APARTMENT": "APT",
    "APT": "APT",
    "SUITE": "STE",
    "UNIT": "UNIT",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    "NUMBER": "APT",
}

_STATE_NAMES = {
    "ALABAMA": "AL",
    "ALASKA": "AK",
    "ARIZONA": "AZ",
    "ARKANSAS": "AR",
    "CALIFORNIA": "CA",
    "COLORADO": "CO",
    "CONNECTICUT": "CT",
    "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL",
    "GEORGIA": "GA",
    "HAWAII": "HI",
    "IDAHO": "ID",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "IOWA": "IA",
    "KANSAS": "KS",
    "KENTUCKY": "KY",
    "LOUISIANA": "LA",
    "MAINE": "ME",
    "MARYLAND": "MD",
    "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI",
    "MINNESOTA": "MN",
    "MISSISSIPPI": "MS",
    "MISSOURI": "MO",
    "MONTANA": "MT",
    "NEBRASKA": "NE",
    "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND",
    "OHIO": "OH",
    "OKLAHOMA": "OK",
    "OREGON": "OR",
    "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN",
    "TEXAS": "TX",
    "UTAH": "UT",
    "VERMONT": "VT",
    "VIRGINIA": "VA",
    "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI",
    "WYOMING": "WY",
}
USPS_STATES = set(_STATE_NAMES.values())

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d")


def is_blank_token(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().upper() in _MISSING


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_person_name(value: str | None) -> str:
    """Uppercase comparison form. Drops prefixes, suffixes, and punctuation."""
    if is_blank_token(value):
        return ""
    text = strip_accents(value or "").upper()
    text = text.replace("'", "").replace("’", "").replace("-", " ")
    text = re.sub(r"[^A-Z\s]", " ", text)
    tokens = _collapse(text).split()
    if len(tokens) > 1 and tokens[0] in _PREFIXES:
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def first_token(value: str) -> str:
    parts = value.split()
    return parts[0] if parts else ""


def given_comparison_key(given_norm: str) -> str:
    return canonical_given(first_token(given_norm))


def display_name(value: str | None) -> str:
    if is_blank_token(value):
        return ""
    text = _collapse(strip_accents(value or ""))
    text = text.replace(".", "")
    return text.title()


def clean_phone(value: str | None) -> tuple[str | None, str]:
    """Return (normalized 10 digits or None, status).

    Status is missing, invalid, or ok. A leading country code 1 is removed.
    """
    if is_blank_token(value):
        return None, "missing"
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None, "invalid"
    if digits[0] in "01" or digits[3] in "01":
        return None, "invalid"
    if len(set(digits)) == 1:
        return None, "invalid"
    return digits, "ok"


def clean_ssn(value: str | None) -> tuple[str | None, str]:
    """Structural SSN check only. It does not mean the number was issued."""
    if is_blank_token(value):
        return None, "missing"
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 9:
        return None, "invalid"
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in {"000", "666"} or area.startswith("9"):
        return None, "invalid"
    if group == "00" or serial == "0000":
        return None, "invalid"
    if len(set(digits)) == 1:
        return None, "invalid"
    return digits, "ok"


def clean_birth_date(value: str | None, as_of: date = AS_OF) -> tuple[str | None, str]:
    """Parse US-oriented date text to ISO. Month comes before day."""
    if is_blank_token(value):
        return None, "missing"
    text = _collapse(value or "")
    parsed: date | None = None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        return None, "invalid"
    if parsed.year < 1900 or parsed > as_of:
        return None, "invalid"
    return parsed.isoformat(), "ok"


def is_transposed_dob(left: str, right: str) -> bool:
    """True when month and day are swapped, or two adjacent digits are swapped."""
    if not left or not right or left == right:
        return False
    try:
        ly, lm, ld = (int(part) for part in left.split("-"))
        ry, rm, rd = (int(part) for part in right.split("-"))
    except ValueError:
        return False
    if (ly, lm, ld) == (ry, rd, rm) and ld <= 12 and rd <= 12 and lm != ld:
        return True
    a = left.replace("-", "")
    b = right.replace("-", "")
    if len(a) != 8 or len(b) != 8:
        return False
    diffs = [i for i in range(8) if a[i] != b[i]]
    if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
        return a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    return False


def clean_address_line(value: str | None) -> str:
    if is_blank_token(value):
        return ""
    text = strip_accents(value or "").upper().replace("#", " APT ")
    text = text.replace(".", " ").replace(",", " ").replace("-", " ")
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    tokens = [_ADDRESS_TOKENS.get(token, token) for token in text.split()]
    collapsed: list[str] = []
    for token in tokens:
        if collapsed and token == collapsed[-1] and token in {"APT", "STE", "UNIT"}:
            continue
        collapsed.append(token)
    return " ".join(collapsed)


def clean_city(value: str | None) -> str:
    if is_blank_token(value):
        return ""
    text = strip_accents(value or "").upper()
    text = re.sub(r"[^A-Z\s]", " ", text)
    return _collapse(text)


def clean_state(value: str | None) -> tuple[str, str]:
    if is_blank_token(value):
        return "", "missing"
    text = _collapse(strip_accents(value or "").upper())
    text = _STATE_NAMES.get(text, text)
    if text in USPS_STATES:
        return text, "ok"
    return "", "invalid"


def clean_postal(value: str | None) -> tuple[str | None, str]:
    if is_blank_token(value):
        return None, "missing"
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 5:
        digits = digits[:5]
    if len(digits) == 5 and digits != "00000":
        return digits, "ok"
    return None, "invalid"


def clean_gender(value: str | None) -> tuple[str, str]:
    """Return a FHIR administrative gender and a status.

    Status is ok, missing, or unrecognized. Unrecognized values are stored as
    unknown so the column stays inside the FHIR value set.
    """
    if is_blank_token(value):
        return "unknown", "missing"
    token = _collapse(value or "").upper()
    if token not in _GENDER_MAP:
        return "unknown", "unrecognized"
    return _GENDER_MAP[token], "ok"


def clean_active(value: str | None) -> int:
    if is_blank_token(value):
        return 1
    token = (value or "").strip().upper()
    if token in {"N", "NO", "FALSE", "0", "INACTIVE"}:
        return 0
    return 1


def _flag(condition: bool) -> int:
    return 1 if condition else 0


def completeness_score(flags: dict[str, int]) -> float:
    present = sum(flags[name] for name in CORE_FIELDS)
    return round(present / len(CORE_FIELDS), 4)


def clean_record(raw: RawRecord) -> CleanedRecord:
    given_norm = clean_person_name(raw.first_name)
    family_norm = clean_person_name(raw.last_name)
    middle_norm = clean_person_name(raw.middle_name)
    phone_norm, _phone_status = clean_phone(raw.phone)
    ssn_norm, _ssn_status = clean_ssn(raw.ssn)
    birth_date, _dob_status = clean_birth_date(raw.birth_date)
    gender, _gender_status = clean_gender(raw.sex)
    state_norm, _state_status = clean_state(raw.state)
    postal_norm, _postal_status = clean_postal(raw.zip)
    address_norm = clean_address_line(raw.address)
    city_norm = clean_city(raw.city)
    flags = {
        "given_name": _flag(bool(given_norm)),
        "family_name": _flag(bool(family_norm)),
        "birth_date": _flag(birth_date is not None),
        "known_gender": _flag(gender in {"male", "female", "other"}),
        "street": _flag(bool(address_norm)),
        "postal_code": _flag(postal_norm is not None),
        "phone": _flag(phone_norm is not None),
        "ssn": _flag(ssn_norm is not None),
        "mrn": _flag(not is_blank_token(raw.mrn)),
    }
    name_use = raw.name_use.strip().lower() if raw.name_use else "official"
    if name_use not in {"official", "maiden", "nickname", "usual"}:
        name_use = "official"
    return CleanedRecord(
        record_id=raw.source_record_id.strip(),
        fhir_logical_id=f"pat-{raw.source_record_id.strip()}",
        source_system_key=raw.source_system.strip(),
        mrn="" if is_blank_token(raw.mrn) else raw.mrn.strip(),
        active=clean_active(raw.active),
        gender=gender,
        gender_raw="" if raw.sex is None else raw.sex.strip(),
        birth_date=birth_date,
        birth_date_raw="" if is_blank_token(raw.birth_date) else raw.birth_date.strip(),
        received_date=raw.received_date.strip(),
        given_name_raw="" if is_blank_token(raw.first_name) else raw.first_name.strip(),
        family_name_raw="" if is_blank_token(raw.last_name) else raw.last_name.strip(),
        middle_name_raw="" if is_blank_token(raw.middle_name) else raw.middle_name.strip(),
        given_name_norm=given_norm,
        family_name_norm=family_norm,
        middle_name_norm=middle_norm,
        name_use=name_use,
        phone_raw="" if is_blank_token(raw.phone) else raw.phone.strip(),
        phone_norm=phone_norm,
        email_raw="" if is_blank_token(raw.email) else raw.email.strip(),
        ssn_raw="" if is_blank_token(raw.ssn) else raw.ssn.strip(),
        ssn_norm=ssn_norm,
        address_line_raw="" if is_blank_token(raw.address) else raw.address.strip(),
        address_line_norm=address_norm,
        city_raw="" if is_blank_token(raw.city) else raw.city.strip(),
        city_norm=city_norm,
        state_raw="" if is_blank_token(raw.state) else raw.state.strip(),
        state_norm=state_norm,
        postal_code_raw="" if is_blank_token(raw.zip) else raw.zip.strip(),
        postal_code_norm=postal_norm,
        completeness_score=completeness_score(flags),
        field_flags=flags,
    )


def assert_gender_tokens_match_map() -> None:
    """Guard so the SQL IN-list and the Python map stay on the same tokens."""
    if set(GENDER_RAW_TOKENS) != set(_GENDER_MAP):
        raise RuntimeError("Gender token list and gender map have drifted.")
