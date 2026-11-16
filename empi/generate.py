"""Seeded synthetic patient extracts.

Faker supplies given names, family names, and street names. Every decision
(who is duplicated, which fields break, which source system) comes from
random.Random(seed) so a second run with the same seed rewrites the same files.

The source CSVs do not contain the golden person id. That label lives only in
ground_truth.csv and is an evaluation key, not an ETL input.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from empi.config import (
    AS_OF,
    DATA_DIR,
    DUPLICATE_COUNT,
    PERSON_COUNT,
    SEED,
    SOURCES,
    VARIANT_WEIGHTS,
    WINDOW_END,
    WINDOW_START,
)
from empi.csvio import write_csv
from empi.models import RAW_COLUMNS, TRUTH_COLUMNS, RawRecord, TruthRow
from empi.nicknames import (
    CANONICAL_TO_NICKNAMES,
    FEMALE_CANONICAL,
    MALE_CANONICAL,
)
from empi.scenarios import DEFAULT_NOISE, NoiseRates, ScenarioSpec, baseline_spec
from empi.standardize import clean_person_name

COMMON_NAMES = (
    ("JOHN", "SMITH", "male"),
    ("JAMES", "WILLIAMS", "male"),
    ("ROBERT", "BROWN", "male"),
    ("MARIA", "GARCIA", "female"),
    ("MARY", "JOHNSON", "female"),
)

PLACES = (
    ("AUSTIN", "TX", "787", "Texas"),
    ("DALLAS", "TX", "752", "Texas"),
    ("HOUSTON", "TX", "770", "Texas"),
    ("ATLANTA", "GA", "303", "Georgia"),
    ("CHICAGO", "IL", "606", "Illinois"),
    ("SEATTLE", "WA", "981", "Washington"),
    ("DENVER", "CO", "802", "Colorado"),
    ("PHOENIX", "AZ", "850", "Arizona"),
    ("MIAMI", "FL", "331", "Florida"),
    ("BOSTON", "MA", "021", "Massachusetts"),
    ("MINNEAPOLIS", "MN", "554", "Minnesota"),
    ("PORTLAND", "OR", "972", "Oregon"),
    ("NASHVILLE", "TN", "372", "Tennessee"),
    ("CHARLOTTE", "NC", "282", "North Carolina"),
    ("COLUMBUS", "OH", "432", "Ohio"),
    ("DETROIT", "MI", "482", "Michigan"),
    ("BALTIMORE", "MD", "212", "Maryland"),
    ("PHILADELPHIA", "PA", "191", "Pennsylvania"),
    ("NEWARK", "NJ", "071", "New Jersey"),
    ("SACRAMENTO", "CA", "958", "California"),
    ("SAN DIEGO", "CA", "921", "California"),
    ("TUCSON", "AZ", "857", "Arizona"),
    ("OMAHA", "NE", "681", "Nebraska"),
    ("MADISON", "WI", "537", "Wisconsin"),
    ("BOISE", "ID", "837", "Idaho"),
)
STREET_SUFFIXES = ("ST", "AVE", "RD", "DR", "LN", "CT", "BLVD")
SUFFIX_LONG = {
    "ST": "Street",
    "AVE": "Avenue",
    "RD": "Road",
    "DR": "Drive",
    "LN": "Lane",
    "CT": "Court",
    "BLVD": "Boulevard",
}


@dataclass
class Person:
    golden_id: str
    given: str
    middle: str
    family: str
    gender: str
    birth: date
    ssn: str
    phone: str
    email: str
    number: int
    street: str
    suffix: str
    unit: str
    city: str
    state: str
    postal: str


def allocate_variants(count: int, weights: list[tuple[str, int]] | None = None) -> list[str]:
    """Spread `count` duplicate slots across variants by largest remainder."""
    spec = weights or VARIANT_WEIGHTS
    total = sum(weight for _, weight in spec)
    if count < 1:
        raise ValueError("duplicate count must be at least 1")
    if total <= 0:
        raise ValueError("variant weights must sum to a positive number")
    exact = [count * weight / total for _, weight in spec]
    floors = [math.floor(value) for value in exact]
    leftover = count - sum(floors)
    order = sorted(
        range(len(spec)),
        key=lambda index: (exact[index] - floors[index], -index),
        reverse=True,
    )
    for index in order[:leftover]:
        floors[index] += 1
    variants: list[str] = []
    for (name, _), slots in zip(spec, floors):
        variants.extend([name] * slots)
    return variants


def _span_days() -> int:
    return (WINDOW_END - WINDOW_START).days


def _random_date(rng: random.Random) -> date:
    return WINDOW_START + timedelta(days=rng.randrange(_span_days() + 1))


def _phone(rng: random.Random, used: set[str]) -> str:
    while True:
        area = rng.randint(200, 999)
        exchange = rng.randint(200, 999)
        if area % 100 == 11 or exchange % 100 == 11:
            continue
        number = f"{area}{exchange}{rng.randint(0, 9999):04d}"
        if number not in used:
            used.add(number)
            return number


def _ssn(rng: random.Random, used: set[str]) -> str:
    while True:
        area = rng.randint(1, 899)
        if area == 666:
            continue
        group = rng.randint(1, 99)
        serial = rng.randint(1, 9999)
        number = f"{area:03d}{group:02d}{serial:04d}"
        if number not in used:
            used.add(number)
            return number


def _street_base(value: str) -> str:
    cleaned = clean_person_name(value)
    return cleaned or "MAIN"


def _typo(text: str, rng: random.Random) -> str:
    chars = list(text)
    if len(chars) < 4:
        return text + "X"
    index = rng.randrange(1, len(chars) - 1)
    operation = rng.randrange(3)
    if operation == 0:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        choices = [ch for ch in alphabet if ch != chars[index]]
        chars[index] = choices[rng.randrange(len(choices))]
    elif operation == 1:
        chars[index], chars[index + 1] = chars[index + 1], chars[index]
    else:
        del chars[index]
    mutated = "".join(chars)
    if mutated == text or not mutated:
        mutated = text + "X"
    return mutated


def _format_name(name: str, rng: random.Random) -> str:
    style = rng.randrange(3)
    titled = name.title()
    if style == 0:
        return titled
    if style == 1:
        return name.upper()
    return f"  {titled}  "


def _format_phone(digits: str, style: int) -> str:
    area, exchange, line = digits[:3], digits[3:6], digits[6:]
    if style == 0:
        return f"({area}) {exchange}-{line}"
    if style == 1:
        return f"{area}-{exchange}-{line}"
    if style == 2:
        return f"{area}.{exchange}.{line}"
    return f"1-{area}-{exchange}-{line}"


def _format_ssn(digits: str, dashed: bool) -> str:
    if dashed:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return digits


def _format_dob(value: date, slash: bool) -> str:
    if slash:
        return f"{value.month}/{value.day}/{value.year}"
    return value.isoformat()


def _format_address(person: Person, style: int) -> str:
    street = person.street.title()
    suffix = person.suffix if style == 0 else SUFFIX_LONG[person.suffix]
    base = f"{person.number} {street} {suffix}"
    if not person.unit:
        return base
    if style == 1:
        return f"{base}, Apt. {person.unit}"
    if style == 2:
        return f"{base} Apartment {person.unit}"
    return f"{base} #{person.unit}"


def _format_sex(gender: str, rng: random.Random) -> str:
    if gender == "male":
        return rng.choice(("M", "M", "Male", "male"))
    if gender == "female":
        return rng.choice(("F", "F", "Female", "female"))
    if gender == "other":
        return rng.choice(("O", "X", "Other"))
    return rng.choice(("U", "Unknown", ""))


def _eligible(person: Person, variant: str) -> bool:
    if variant in {"nickname", "combined"}:
        return person.given in CANONICAL_TO_NICKNAMES
    if variant == "transposed_dob":
        return person.birth.day <= 12 and person.birth.day != person.birth.month
    if variant == "swapped_names":
        return person.given != person.family
    return True


def _apply_noise(raw: RawRecord, rng: random.Random, rates: NoiseRates = DEFAULT_NOISE) -> RawRecord:
    """Independent data-quality damage on charts that are not part of a duplicate pair.

    Baseline rates keep the same random-call order as the original generator.
    Extra name-typo rolls run only when that rate is above zero.
    """
    roll = rng.random()
    if roll < rates.phone_missing:
        raw.phone = ""
    elif roll < rates.phone_invalid:
        raw.phone = "CALL OFFICE"

    roll = rng.random()
    if roll < rates.ssn_missing:
        raw.ssn = ""
    elif roll < rates.ssn_invalid:
        raw.ssn = "000-00-0000"

    if rng.random() < rates.address_missing:
        raw.address = ""
    if rng.random() < rates.postal_invalid:
        raw.zip = "AB12"
    if rng.random() < rates.dob_invalid:
        raw.birth_date = "02/31/1980"

    roll = rng.random()
    if roll < rates.gender_blank:
        raw.sex = ""
    elif roll < rates.gender_bad:
        raw.sex = "N/A"

    if rng.random() < rates.family_missing:
        raw.last_name = ""
    if rng.random() < rates.given_missing:
        raw.first_name = ""
    if rng.random() < rates.mrn_missing:
        raw.mrn = ""
    if rng.random() < rates.inactive:
        raw.active = "N"
    if rates.name_typo > 0 and raw.last_name and rng.random() < rates.name_typo:
        raw.last_name = _typo(clean_person_name(raw.last_name) or "SMITH", rng).title()
    return raw


def _different_birth(birth: date) -> date:
    year = birth.year + 20 if birth.year + 20 <= 2015 else birth.year - 20
    if year == birth.year:
        month = 1 if birth.month != 1 else 2
        return date(year, month, birth.day)
    return date(year, birth.month, birth.day)


class Generator:
    def __init__(self, scenario: ScenarioSpec) -> None:
        if scenario.persons <= scenario.duplicates:
            raise ValueError("persons must be greater than the duplicate count")
        if scenario.persons < 1 or scenario.duplicates < 1:
            raise ValueError("persons and duplicates must be positive")
        self.scenario = scenario
        self.persons = scenario.persons
        self.duplicates = scenario.duplicates
        self.seed = scenario.seed
        Faker.seed(scenario.seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(scenario.seed)
        self.rng = random.Random(scenario.seed)
        self._phones: set[str] = set()
        self._ssns: set[str] = set()
        self._counters = {key: 0 for key in SOURCES}

    def build(self) -> tuple[list[RawRecord], list[TruthRow]]:
        people = [self._person(index) for index in range(1, self.persons + 1)]
        reserved = self._apply_lookalikes(people)
        assignments = self._assign_duplicates(people, reserved)
        protected = {person.golden_id for person, _variant in assignments} | reserved
        by_id = {person.golden_id: person for person in people}

        raw_rows: list[RawRecord] = []
        truth: list[TruthRow] = []
        parent_raw: dict[str, RawRecord] = {}

        for person in people:
            variant = next(
                (name for owner, name in assignments if owner.golden_id == person.golden_id),
                "",
            )
            raw = self._base_raw(person, variant)
            if person.golden_id not in protected:
                raw = _apply_noise(raw, self.rng, self.scenario.noise)
            raw = self._maybe_damage_lab(raw)
            raw_rows.append(raw)
            parent_raw[person.golden_id] = raw
            truth.append(
                TruthRow(
                    source_record_id=raw.source_record_id,
                    golden_person_id=person.golden_id,
                    is_injected_duplicate=0,
                    variant="",
                    parent_record_id="",
                    source_system=raw.source_system,
                    scenario_key=self.scenario.key,
                )
            )

        for person, variant in assignments:
            raw = self._duplicate_raw(person, variant, parent_raw[person.golden_id])
            raw = self._maybe_damage_lab(raw)
            raw_rows.append(raw)
            truth.append(
                TruthRow(
                    source_record_id=raw.source_record_id,
                    golden_person_id=person.golden_id,
                    is_injected_duplicate=1,
                    variant=variant,
                    parent_record_id=parent_raw[person.golden_id].source_record_id,
                    source_system=raw.source_system,
                    scenario_key=self.scenario.key,
                )
            )

        # `by_id` keeps the person list referenced for readers of the generator.
        if len(by_id) != self.persons:
            raise RuntimeError("person id collision")
        return raw_rows, truth

    def _person(self, index: int) -> Person:
        gender = self.rng.choices(
            ["female", "male", "other", "unknown"],
            weights=[49, 47, 2, 2],
        )[0]
        if gender == "female":
            faker_given = self.fake.first_name_female()
            canon_pool = FEMALE_CANONICAL
        elif gender == "male":
            faker_given = self.fake.first_name_male()
            canon_pool = MALE_CANONICAL
        else:
            faker_given = self.fake.first_name()
            canon_pool = ()
        family = clean_person_name(self.fake.last_name()) or "HARPER"
        street = _street_base(self.fake.street_name())
        use_common = (
            self.scenario.common_name_rate > 0
            and self.rng.random() < self.scenario.common_name_rate
        )
        if use_common:
            given, family, gender = COMMON_NAMES[self.rng.randrange(len(COMMON_NAMES))]
        elif canon_pool and self.rng.random() < 0.55:
            given = canon_pool[self.rng.randrange(len(canon_pool))]
        else:
            given = clean_person_name(faker_given) or "ALEX"
        if given == family:
            family = f"{family}SON"
        middle = chr(ord("A") + self.rng.randrange(26)) if self.rng.random() < 0.6 else ""
        year = self.rng.randint(1940, 2015)
        month = self.rng.randint(1, 12)
        day = self.rng.randint(1, 28)
        city, state, zip3, _full = PLACES[self.rng.randrange(len(PLACES))]
        postal = f"{zip3}{self.rng.randint(0, 99):02d}"
        number = self.rng.randint(100, 9999)
        suffix = STREET_SUFFIXES[self.rng.randrange(len(STREET_SUFFIXES))]
        unit = str(self.rng.randint(1, 12)) if self.rng.random() < 0.35 else ""
        golden = f"{self.scenario.key}__G{index:06d}"
        local = "".join(ch for ch in f"{given}{family}".lower() if ch.isalpha())[:18]
        return Person(
            golden_id=golden,
            given=given,
            middle=middle,
            family=family,
            gender=gender,
            birth=date(year, month, day),
            ssn=_ssn(self.rng, self._ssns),
            phone=_phone(self.rng, self._phones),
            email=f"{local}{index}@example.com",
            number=number,
            street=street,
            suffix=suffix,
            unit=unit,
            city=city,
            state=state,
            postal=postal,
        )

    def _assign_duplicates(
        self,
        people: list[Person],
        reserved: set[str],
    ) -> list[tuple[Person, str]]:
        remaining = {
            person.golden_id: person for person in people if person.golden_id not in reserved
        }
        if self.duplicates > len(remaining):
            raise ValueError("not enough unreserved people for the duplicate count")
        assignments: list[tuple[Person, str]] = []
        weights = list(self.scenario.variant_weights) or list(VARIANT_WEIGHTS)
        for variant in allocate_variants(self.duplicates, weights):
            pool = [
                person
                for _gid, person in sorted(remaining.items())
                if _eligible(person, variant)
            ]
            chosen_variant = variant
            if not pool:
                chosen_variant = "address_format"
                pool = [person for _gid, person in sorted(remaining.items())]
            person = pool[self.rng.randrange(len(pool))]
            del remaining[person.golden_id]
            if chosen_variant == "maiden_name":
                maiden = clean_person_name(self.fake.last_name()) or "HARPER"
                if maiden == person.family:
                    maiden = f"{maiden}SON"
                person.family_maiden = maiden  # type: ignore[attr-defined]
            assignments.append((person, chosen_variant))
        return assignments

    def _next_ids(self, source: str) -> tuple[str, str]:
        self._counters[source] += 1
        number = self._counters[source]
        meta = SOURCES[source]
        record_id = f"{self.scenario.key}__{meta['prefix']}-{number:06d}"
        mrn = f"{self.scenario.key}-{meta['mrn_prefix']}{number:07d}"
        return record_id, mrn

    def _pick_source(self) -> str:
        return self.rng.choices(
            ["registration", "lab", "billing"],
            weights=list(self.scenario.source_weights),
        )[0]

    def _base_raw(self, person: Person, variant: str) -> RawRecord:
        source = self._pick_source()
        record_id, mrn = self._next_ids(source)
        received = _random_date(self.rng)
        phone_style = 0 if variant == "phone_format" else self.rng.randrange(4)
        address_style = 0 if variant in {"address_format", "combined"} else self.rng.randrange(3)
        state_value = self._state_text(person)
        return RawRecord(
            source_record_id=record_id,
            source_system=source,
            mrn=mrn,
            name_use="official",
            first_name=_format_name(person.given, self.rng),
            middle_name=person.middle.title() if person.middle else "",
            last_name=_format_name(person.family, self.rng),
            birth_date=_format_dob(person.birth, slash=bool(self.rng.randrange(2))),
            sex=_format_sex(person.gender, self.rng),
            ssn=_format_ssn(person.ssn, dashed=bool(self.rng.randrange(2))) if person.ssn else "",
            phone=_format_phone(person.phone, phone_style),
            email=person.email,
            address=_format_address(person, address_style),
            city=person.city.title(),
            state=state_value,
            zip=person.postal,
            active="Y",
            received_date=received.isoformat(),
        )

    def _state_text(self, person: Person) -> str:
        if self.rng.random() < 0.25:
            for _city, abbr, _zip, full in PLACES:
                if abbr == person.state:
                    return full
        return person.state

    def _duplicate_raw(self, person: Person, variant: str, parent: RawRecord) -> RawRecord:
        given, family = person.given, person.family
        name_use = "official"
        birth = person.birth
        ssn: str | None = person.ssn
        phone: str | None = person.phone
        if variant == "typo_family":
            family = _typo(family, self.rng)
        elif variant == "typo_given":
            given = _typo(given, self.rng)
        elif variant == "nickname":
            given = self._nickname(person.given)
            name_use = "nickname"
        elif variant == "transposed_dob":
            birth = date(birth.year, birth.day, birth.month)
        elif variant == "swapped_names":
            given, family = family, given
        elif variant == "missing_ssn":
            ssn = None
        elif variant == "missing_phone":
            phone = None
        elif variant == "maiden_name":
            family = getattr(person, "family_maiden")
            name_use = "maiden"
        elif variant == "combined":
            given = self._nickname(person.given)
            name_use = "nickname"
        elif variant == "name_dob_only":
            ssn = None
            phone = None
        source = self._duplicate_source(parent.source_system)
        record_id, mrn = self._next_ids(source)
        parent_received = date.fromisoformat(parent.received_date)
        lag = timedelta(days=self.rng.randint(1, 90))
        received = min(WINDOW_END, parent_received + lag)
        if received < parent_received:
            received = parent_received
        phone_style = 3 if variant == "phone_format" else self.rng.randrange(4)
        if variant in {"address_format", "combined"}:
            address_style = 2
        else:
            address_style = self.rng.randrange(3)
        local = "".join(ch for ch in f"{given}{family}".lower() if ch.isalpha())[:18]
        raw = RawRecord(
            source_record_id=record_id,
            source_system=source,
            mrn=mrn,
            name_use=name_use,
            first_name=_format_name(given, self.rng) if given else "",
            middle_name="" if self.rng.random() < 0.5 else (person.middle.title() if person.middle else ""),
            last_name=_format_name(family, self.rng) if family else "",
            birth_date=_format_dob(birth, slash=bool(self.rng.randrange(2))),
            sex=_format_sex(person.gender, self.rng),
            ssn="" if ssn is None else _format_ssn(ssn, dashed=bool(self.rng.randrange(2))),
            phone="" if phone is None else _format_phone(phone, phone_style),
            email=f"{local}.dup{record_id[-4:]}@example.com",
            address=_format_address(person, address_style),
            city=person.city.title(),
            state=self._state_text(person),
            zip=person.postal if self.rng.random() < 0.85 else f"{person.postal}-{self.rng.randint(1000, 9999)}",
            active="Y",
            received_date=received.isoformat(),
        )
        if variant == "name_dob_only":
            raw.address = f"{person.number + 17} Other Road"
            raw.city = "Other City"
            raw.state = "WY" if person.state != "WY" else "TX"
            raw.zip = "82999" if not person.postal.startswith("829") else "75001"
        return raw

    def _nickname(self, given: str) -> str:
        options = CANONICAL_TO_NICKNAMES[given]
        return options[self.rng.randrange(len(options))]

    def _duplicate_source(self, parent_source: str) -> str:
        others = [key for key in SOURCES if key != parent_source]
        if self.rng.random() < self.scenario.cross_source_duplicate_rate:
            return others[self.rng.randrange(len(others))]
        return parent_source

    def _maybe_damage_lab(self, raw: RawRecord) -> RawRecord:
        """Legacy lab extract: SSN dropped, phone and dates often unusable."""
        if not self.scenario.damage_lab or raw.source_system != "lab":
            return raw
        raw.ssn = ""
        roll = self.rng.random()
        if roll < 0.45:
            raw.phone = ""
        elif roll < 0.65:
            raw.phone = "SEE CHART"
        if self.rng.random() < 0.12:
            raw.birth_date = "02/31/1980"
        if self.rng.random() < 0.20:
            raw.address = ""
        if self.rng.random() < 0.15:
            raw.zip = "00000"
        if raw.last_name:
            raw.last_name = f"  {raw.last_name.upper()}  "
        if raw.first_name:
            raw.first_name = f"  {raw.first_name.upper()} "
        return raw

    def _apply_lookalikes(self, people: list[Person]) -> set[str]:
        """Different people who share household or twin demographics.

        Returns their golden ids so they are not also used as injected duplicates.
        Baseline calls this with zero counts and does not draw random numbers.
        """
        spec = self.scenario
        if (
            spec.twin_pairs_blank_ssn == 0
            and spec.twin_pairs_conflict_ssn == 0
            and spec.household_pairs == 0
        ):
            return set()
        reserved: set[str] = set()
        cursor = 0

        def take() -> Person:
            nonlocal cursor
            if cursor >= len(people):
                raise RuntimeError("not enough people to build lookalikes")
            person = people[cursor]
            cursor += 1
            reserved.add(person.golden_id)
            return person

        def copy_home(src: Person, dst: Person) -> None:
            dst.family = src.family
            dst.phone = src.phone
            dst.number = src.number
            dst.street = src.street
            dst.suffix = src.suffix
            dst.unit = src.unit
            dst.city = src.city
            dst.state = src.state
            dst.postal = src.postal
            dst.gender = src.gender

        def separate_given(src: Person, dst: Person, fallback: str) -> None:
            if dst.given == src.given:
                dst.given = fallback if src.given != fallback else "ALEX"

        for _ in range(spec.twin_pairs_blank_ssn):
            anchor, other = take(), take()
            copy_home(anchor, other)
            other.birth = anchor.birth
            anchor.ssn = ""
            other.ssn = ""
            separate_given(anchor, other, "JORDAN")
        for _ in range(spec.twin_pairs_conflict_ssn):
            anchor, other = take(), take()
            copy_home(anchor, other)
            other.birth = anchor.birth
            separate_given(anchor, other, "JORDAN")
        for _ in range(spec.household_pairs):
            anchor, other = take(), take()
            copy_home(anchor, other)
            anchor.ssn = ""
            other.ssn = ""
            other.birth = _different_birth(anchor.birth)
            separate_given(anchor, other, "TAYLOR")
        return reserved


def generate_dataset(
    data_dir: Path = DATA_DIR,
    persons: int | None = None,
    duplicates: int | None = None,
    seed: int | None = None,
    scenario: ScenarioSpec | None = None,
) -> dict[str, int]:
    spec = scenario or baseline_spec()
    if persons is not None or duplicates is not None or seed is not None:
        from dataclasses import replace

        spec = replace(
            spec,
            persons=PERSON_COUNT if persons is None else persons,
            duplicates=DUPLICATE_COUNT if duplicates is None else duplicates,
            seed=SEED if seed is None else seed,
        )
    raw_rows, truth = Generator(spec).build()
    data_dir.mkdir(parents=True, exist_ok=True)
    for source, meta in SOURCES.items():
        rows = [row for row in raw_rows if row.source_system == source]
        rows.sort(key=lambda row: row.source_record_id)
        write_csv(
            data_dir / meta["file_name"],
            [row.__dict__ for row in rows],
            RAW_COLUMNS,
        )
    truth.sort(key=lambda row: row.source_record_id)
    write_csv(
        data_dir / "ground_truth.csv",
        [row.__dict__ for row in truth],
        TRUTH_COLUMNS,
    )
    return {
        "persons": persons,
        "duplicates": duplicates,
        "records": len(raw_rows),
        "seed": spec.seed,
        "scenario": spec.key,
        "as_of": AS_OF.isoformat(),
    }
