"""Named synthetic populations for the EMPI dashboard.

Each scenario is a seeded fictional extract. They are not hospital files.
`baseline` is the original ~2% duplicate set. The others change one thing a
reviewer would want to see on a slicer: more duplicates, dirtier fields, lookalike
people, or a source system that arrived broken.
"""

from dataclasses import dataclass, replace

from empi.config import DUPLICATE_COUNT, PERSON_COUNT, SEED, VARIANT_WEIGHTS


@dataclass(frozen=True)
class NoiseRates:
    """Upper bounds for the independent data-quality rolls in the generator.

    Phone and SSN use a cumulative bound: values below the first cut are missing,
    values below the second cut are invalid. The other fields are single rolls.
    """

    phone_missing: float = 0.05
    phone_invalid: float = 0.062
    ssn_missing: float = 0.12
    ssn_invalid: float = 0.128
    address_missing: float = 0.012
    postal_invalid: float = 0.008
    dob_invalid: float = 0.004
    gender_blank: float = 0.012
    gender_bad: float = 0.016
    family_missing: float = 0.0015
    given_missing: float = 0.001
    mrn_missing: float = 0.0015
    inactive: float = 0.008
    name_typo: float = 0.0


DEFAULT_NOISE = NoiseRates()

MESSY_NOISE = NoiseRates(
    phone_missing=0.22,
    phone_invalid=0.30,
    ssn_missing=0.40,
    ssn_invalid=0.48,
    address_missing=0.08,
    postal_invalid=0.06,
    dob_invalid=0.03,
    gender_blank=0.05,
    gender_bad=0.08,
    family_missing=0.015,
    given_missing=0.01,
    mrn_missing=0.01,
    inactive=0.01,
    name_typo=0.18,
)

# Relative weights. allocate_variants scales them to the scenario's duplicate count.
MESSY_VARIANT_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("typo_family", 30),
    ("typo_given", 20),
    ("nickname", 8),
    ("transposed_dob", 18),
    ("swapped_names", 6),
    ("missing_ssn", 22),
    ("missing_phone", 20),
    ("address_format", 18),
    ("maiden_name", 6),
    ("phone_format", 4),
    ("combined", 8),
    ("name_dob_only", 10),
)


@dataclass(frozen=True)
class ScenarioSpec:
    key: str
    name: str
    sort: int
    description: str
    seed: int
    persons: int
    duplicates: int
    variant_weights: tuple[tuple[str, int], ...] = tuple(VARIANT_WEIGHTS)
    noise: NoiseRates = DEFAULT_NOISE
    source_weights: tuple[int, int, int] = (72, 16, 12)
    cross_source_duplicate_rate: float = 0.7
    common_name_rate: float = 0.0
    twin_pairs_blank_ssn: int = 0
    twin_pairs_conflict_ssn: int = 0
    household_pairs: int = 0
    damage_lab: bool = False

    @property
    def injected_rate(self) -> float:
        return self.duplicates / (self.persons + self.duplicates)


def baseline_spec() -> ScenarioSpec:
    return ScenarioSpec(
        key="baseline",
        name="Baseline",
        sort=1,
        description=(
            "Current registration load. About 2% of charts are injected extra charts "
            "with the usual mix of typos, nicknames, transposed dates, and missing identifiers."
        ),
        seed=SEED,
        persons=PERSON_COUNT,
        duplicates=DUPLICATE_COUNT,
    )


def all_scenarios() -> list[ScenarioSpec]:
    """The five populations the dashboard compares. Order is the slicer order."""
    baseline = baseline_spec()
    return [
        baseline,
        ScenarioSpec(
            key="merger",
            name="Hospital merger",
            sort=2,
            description=(
                "Two fictional hospitals combined their registration files. "
                "About 9% of charts are extra charts, mostly in a different source system from the original."
            ),
            seed=43,
            persons=4000,
            duplicates=400,
            source_weights=(45, 30, 25),
            cross_source_duplicate_rate=0.9,
        ),
        ScenarioSpec(
            key="messy_entry",
            name="Messy data entry",
            sort=3,
            description=(
                "The same duplicate rate ballpark as baseline, with much more missing SSN and phone, "
                "invalid formats, and name typos on charts that are not duplicates."
            ),
            seed=44,
            persons=3000,
            duplicates=80,
            variant_weights=MESSY_VARIANT_WEIGHTS,
            noise=MESSY_NOISE,
        ),
        ScenarioSpec(
            key="hard_cases",
            name="Hard cases",
            sort=4,
            description=(
                "Twins who share a last name, birth date, address, and phone; households that share a "
                "phone and address; and a pile of common names such as John Smith. "
                "These are different people. Precision should fall because some of them look like duplicates."
            ),
            seed=45,
            persons=2500,
            duplicates=70,
            common_name_rate=0.22,
            twin_pairs_blank_ssn=20,
            twin_pairs_conflict_ssn=12,
            household_pairs=15,
        ),
        ScenarioSpec(
            key="lab_migration",
            name="Lab migration",
            sort=5,
            description=(
                "The laboratory feed was loaded from a legacy system. Lab charts systematically drop SSN, "
                "often drop or garble the phone, and sometimes send an unusable birth date or address. "
                "Registration and billing are unchanged."
            ),
            seed=46,
            persons=3000,
            duplicates=90,
            damage_lab=True,
            cross_source_duplicate_rate=0.85,
        ),
    ]


SCENARIO_BY_KEY = {spec.key: spec for spec in all_scenarios()}


def resolve_scenarios(
    *,
    scenario: str | None,
    all_scenarios_flag: bool,
    persons: int | None,
    duplicates: int | None,
    seed: int | None,
) -> list[ScenarioSpec]:
    """Turn CLI flags into the list of scenarios to build.

    `python -m empi` and `--all-scenarios` build every scenario at its own size and seed.
    `--scenario` builds one. `--persons`, `--duplicates`, and `--seed` override that one scenario
    and are only valid with `--scenario`.
    """
    if scenario and all_scenarios_flag:
        raise ValueError("Pass either --scenario or --all-scenarios, not both.")
    if not scenario and not all_scenarios_flag:
        raise ValueError("Pass --scenario or --all-scenarios.")
    overrides = any(value is not None for value in (persons, duplicates, seed))
    if all_scenarios_flag:
        if overrides:
            raise ValueError(
                "--persons, --duplicates, and --seed apply to one scenario. "
                "Pass --scenario with them."
            )
        return list(all_scenarios())
    if scenario not in SCENARIO_BY_KEY:
        known = ", ".join(SCENARIO_BY_KEY)
        raise ValueError(f"Unknown scenario {scenario!r}. Known scenarios: {known}.")
    spec = SCENARIO_BY_KEY[scenario]
    changes = {}
    if persons is not None:
        changes["persons"] = persons
    if duplicates is not None:
        changes["duplicates"] = duplicates
    if seed is not None:
        changes["seed"] = seed
    if changes:
        spec = replace(spec, **changes)
    if spec.duplicates >= spec.persons:
        raise ValueError("duplicates must be smaller than the person count")
    return [spec]
