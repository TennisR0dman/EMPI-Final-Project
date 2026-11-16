"""Dataclasses shared across generate, clean, match, and export."""

from dataclasses import dataclass, field


@dataclass
class RawRecord:
    source_record_id: str
    source_system: str
    mrn: str
    name_use: str
    first_name: str
    middle_name: str
    last_name: str
    birth_date: str
    sex: str
    ssn: str
    phone: str
    email: str
    address: str
    city: str
    state: str
    zip: str
    active: str
    received_date: str


RAW_COLUMNS = (
    "source_record_id",
    "source_system",
    "mrn",
    "name_use",
    "first_name",
    "middle_name",
    "last_name",
    "birth_date",
    "sex",
    "ssn",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "zip",
    "active",
    "received_date",
)


@dataclass
class TruthRow:
    source_record_id: str
    golden_person_id: str
    is_injected_duplicate: int
    variant: str
    parent_record_id: str
    source_system: str
    scenario_key: str = "baseline"


TRUTH_COLUMNS = (
    "source_record_id",
    "golden_person_id",
    "is_injected_duplicate",
    "variant",
    "parent_record_id",
    "source_system",
    "scenario_key",
)


@dataclass
class CleanedRecord:
    record_id: str
    fhir_logical_id: str
    source_system_key: str
    mrn: str
    active: int
    gender: str
    gender_raw: str
    birth_date: str | None
    birth_date_raw: str
    received_date: str
    given_name_raw: str
    family_name_raw: str
    middle_name_raw: str
    given_name_norm: str
    family_name_norm: str
    middle_name_norm: str
    name_use: str
    phone_raw: str
    phone_norm: str | None
    email_raw: str
    ssn_raw: str
    ssn_norm: str | None
    address_line_raw: str
    address_line_norm: str
    city_raw: str
    city_norm: str
    state_raw: str
    state_norm: str
    postal_code_raw: str
    postal_code_norm: str | None
    completeness_score: float
    scenario_key: str = "baseline"
    field_flags: dict[str, int] = field(default_factory=dict)


@dataclass
class MatchFeatures:
    record_id: str
    source_system_key: str
    given_norm: str
    family_norm: str
    birth_date: str | None
    birth_year: str | None
    ssn_norm: str | None
    phone_norm: str | None
    street_norm: str
    postal_norm: str | None
    gender: str
    received_date: str
    completeness: float
    active: int
    scenario_key: str = "baseline"


@dataclass
class FieldComparison:
    field: str
    status: str
    weight: float


@dataclass
class LinkRow:
    record_id: str
    other_record_id: str
    link_type: str
    score: float
    match_grade: str


@dataclass
class PairScore:
    record_id_1: str
    record_id_2: str
    weight: float
    score: float
    match_grade: str
    decision: str
    decision_reason: str
    alignment: str
    blocked_by: str
    fields: list[FieldComparison]

    @property
    def agreed_fields(self) -> str:
        parts = [f"{item.field}:{item.status}" for item in self.fields]
        parts.append(f"alignment:{self.alignment}")
        return "|".join(parts)
