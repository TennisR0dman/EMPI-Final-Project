"""Catalog of data-quality issue types written by the SQL checks.

Severity and description live here so the Power BI dimension can list every
check, including checks that fired zero times on a given run. The SQL file is
still what decides which rows are flagged.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IssueType:
    issue_type: str
    severity: str
    field_name: str
    description: str
    cross_record: bool


ISSUE_CATALOG: dict[str, IssueType] = {
    item.issue_type: item
    for item in (
        IssueType(
            "missing_family_name",
            "error",
            "family_name",
            "Family name is blank. A chart without a family name is unsafe to match automatically.",
            False,
        ),
        IssueType(
            "missing_given_name",
            "error",
            "given_name",
            "Given name is blank.",
            False,
        ),
        IssueType(
            "missing_birth_date",
            "error",
            "birth_date",
            "Birth date was not sent. This is separate from a value that was sent but could not be parsed.",
            False,
        ),
        IssueType(
            "invalid_birth_date",
            "error",
            "birth_date",
            "Birth date text could not be parsed as a real date on or before the project as-of date and on or after 1900-01-01.",
            False,
        ),
        IssueType(
            "missing_phone",
            "warning",
            "phone",
            "No phone number was sent. Phone is often legitimately absent, so this is a warning.",
            False,
        ),
        IssueType(
            "invalid_phone",
            "error",
            "phone",
            "Phone text was present but did not normalize to a 10-digit NANP number.",
            False,
        ),
        IssueType(
            "missing_ssn",
            "warning",
            "ssn",
            "No SSN was sent. Many real registrations do not collect an SSN, so this is a warning, not an error.",
            False,
        ),
        IssueType(
            "invalid_ssn",
            "error",
            "ssn",
            "SSN text was present but failed the structural check (9 digits, area not 000/666/9xx, group not 00, serial not 0000).",
            False,
        ),
        IssueType(
            "missing_address",
            "warning",
            "address",
            "Street address is blank.",
            False,
        ),
        IssueType(
            "missing_postal_code",
            "warning",
            "postal_code",
            "Postal code is blank.",
            False,
        ),
        IssueType(
            "invalid_postal_code",
            "error",
            "postal_code",
            "Postal code text was present but did not contain a 5-digit ZIP.",
            False,
        ),
        IssueType(
            "invalid_state",
            "error",
            "state",
            "State text was present but did not map to a USPS abbreviation.",
            False,
        ),
        IssueType(
            "gender_unknown",
            "warning",
            "gender",
            "Administrative gender is unknown. FHIR allows the code unknown; it still counts against known-gender completeness.",
            False,
        ),
        IssueType(
            "unrecognized_gender",
            "warning",
            "gender",
            "Sex value was not in the source map, so it was stored as FHIR gender unknown.",
            False,
        ),
        IssueType(
            "missing_mrn",
            "error",
            "mrn",
            "No medical record number was sent for this source system.",
            False,
        ),
        IssueType(
            "shared_ssn",
            "warning",
            "ssn",
            "Another record has the same normalized SSN and a different record id. This is a deterministic duplicate signal, not proof.",
            True,
        ),
        IssueType(
            "exact_name_and_dob",
            "warning",
            "demographic",
            "Another record shares normalized given name, family name, and birth date. MRNs may still differ.",
            True,
        ),
        IssueType(
            "shared_phone_and_dob",
            "warning",
            "phone",
            "Another record shares the normalized phone number and birth date.",
            True,
        ),
    )
}
