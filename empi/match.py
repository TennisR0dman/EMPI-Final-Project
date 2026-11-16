"""Blocking plus a Fellegi-Sunter-style score and a conservative link policy.

The score is a posterior probability. Each field adds log2(m/u) when it agrees
and log2((1-m)/(1-u)) when it disagrees. Missing fields add nothing. m and u
are the stated parameters in config.py. They are not an EM estimate.

Auto-link is stricter than the score alone. A high score from name and birth
date, with no second identifier and no matching street, stays in review.
A known gender conflict or a clearly different SSN also stays in review.
FHIR R4 match grades used here:
  certain       -> auto_link
  probable      -> manual_review
  possible      -> manual_review
  certainly-not -> non_match, and the pair is not stored
"""

import math
from itertools import combinations

from empi.config import (
    BLOCK_CAP,
    FIELD_M_U,
    IDENTIFIER_BLOCK_CAP,
    PRIOR,
    SCORE_CERTAIN,
    SCORE_POSSIBLE,
    SCORE_PROBABLE,
    SOURCE_PRIORITY,
)
from empi.models import FieldComparison, LinkRow, MatchFeatures, PairScore
from empi.nicknames import canonical_given
from empi.standardize import first_token, is_transposed_dob
from empi.stringmatch import jaro_winkler, soundex

# partial counts as agreement for corroboration; weak does not.
STRONG = {"agree", "partial", "transposed"}


def _agree_weight(field: str) -> float:
    match_prob, unmatch_prob = FIELD_M_U[field]
    return math.log2(match_prob / unmatch_prob)


def _disagree_weight(field: str) -> float:
    match_prob, unmatch_prob = FIELD_M_U[field]
    return math.log2((1 - match_prob) / (1 - unmatch_prob))


def field_weight(field: str, status: str) -> float:
    if status == "agree":
        return _agree_weight(field)
    if status == "partial":
        scale = 0.35 if field == "ssn" else 0.75
        return _agree_weight(field) * scale
    if status == "weak":
        return _agree_weight(field) * 0.40
    if status == "transposed":
        return _agree_weight(field) * 0.55
    if status == "disagree":
        return _disagree_weight(field)
    if status == "missing":
        return 0.0
    raise ValueError(f"Unknown comparison status {status}")


def weight_to_score(weight: float, prior: float = PRIOR) -> float:
    capped = max(-40.0, min(40.0, weight))
    prior_odds = prior / (1.0 - prior)
    odds = prior_odds * (2.0 ** capped)
    return odds / (1.0 + odds)


def _name_status(left: str, right: str, nicknames: bool) -> str:
    if not left or not right:
        return "missing"
    if nicknames:
        left_key = canonical_given(first_token(left))
        right_key = canonical_given(first_token(right))
    else:
        left_key, right_key = left, right
    if left == right or left_key == right_key:
        return "agree"
    similarity = max(jaro_winkler(left, right), jaro_winkler(left_key, right_key))
    if similarity >= 0.93:
        return "partial"
    if similarity >= 0.88:
        return "weak"
    return "disagree"


def _ssn_status(left: str | None, right: str | None) -> str:
    if not left or not right:
        return "missing"
    if left == right:
        return "agree"
    if len(left) == len(right) and sum(a != b for a, b in zip(left, right)) == 1:
        return "partial"
    return "disagree"


def _exact_status(left: str | None, right: str | None) -> str:
    if not left or not right:
        return "missing"
    if left == right:
        return "agree"
    return "disagree"


def _dob_status(left: str | None, right: str | None) -> str:
    if not left or not right:
        return "missing"
    if left == right:
        return "agree"
    if is_transposed_dob(left, right):
        return "transposed"
    return "disagree"


def _gender_status(left: str, right: str) -> str:
    if left == "unknown" or right == "unknown":
        return "missing"
    if left == right:
        return "agree"
    return "disagree"


def _comparisons(left: MatchFeatures, right: MatchFeatures, swap: bool) -> list[FieldComparison]:
    if swap:
        given = _name_status(left.given_norm, right.family_norm, True)
        family = _name_status(left.family_norm, right.given_norm, True)
    else:
        given = _name_status(left.given_norm, right.given_norm, True)
        family = _name_status(left.family_norm, right.family_norm, False)
    statuses = {
        "given": given,
        "family": family,
        "dob": _dob_status(left.birth_date, right.birth_date),
        "ssn": _ssn_status(left.ssn_norm, right.ssn_norm),
        "phone": _exact_status(left.phone_norm, right.phone_norm),
        "street": _name_status(left.street_norm, right.street_norm, False),
        "postal": _exact_status(left.postal_norm, right.postal_norm),
        "gender": _gender_status(left.gender, right.gender),
    }
    return [
        FieldComparison(field, status, field_weight(field, status))
        for field, status in statuses.items()
    ]


def _swap_supported(comparisons: list[FieldComparison]) -> bool:
    statuses = {item.field: item.status for item in comparisons}
    return statuses["given"] in {"agree", "partial"} and statuses["family"] in {
        "agree",
        "partial",
    }


def corroborated(statuses: dict[str, str]) -> bool:
    """Second-identifier rule for retiring a chart without a person looking."""
    demographic_support = sum(
        statuses[field] in STRONG for field in ("given", "family", "dob", "phone", "street")
    )
    ssn_ok = statuses["ssn"] == "agree" and demographic_support >= 1
    phone_ok = statuses["phone"] == "agree" and (
        statuses["dob"] in {"agree", "transposed"}
        or statuses["family"] in STRONG
        or statuses["given"] in STRONG
    )
    address_ok = (
        statuses["dob"] == "agree"
        and statuses["family"] in STRONG
        and statuses["given"] in STRONG
        and statuses["street"] in STRONG
    )
    return ssn_ok or phone_ok or address_ok


def decide(score: float, statuses: dict[str, str]) -> tuple[str, str, str]:
    """Return match grade, decision, and a short reason code."""
    if score < SCORE_POSSIBLE:
        return "certainly-not", "non_match", "below_review_threshold"
    conflict = statuses["ssn"] == "disagree" or statuses["gender"] == "disagree"
    if conflict:
        if score >= SCORE_PROBABLE:
            return "probable", "manual_review", "identity_conflict"
        return "possible", "manual_review", "identity_conflict"
    if score >= SCORE_CERTAIN and corroborated(statuses):
        return "certain", "auto_link", "corroborated_high_score"
    if score >= SCORE_CERTAIN:
        return "probable", "manual_review", "high_score_without_corroboration"
    if score >= SCORE_PROBABLE:
        return "probable", "manual_review", "probable_band"
    return "possible", "manual_review", "possible_band"


def score_pair(left: MatchFeatures, right: MatchFeatures, blocked_by: str = "") -> PairScore:
    if left.record_id == right.record_id:
        raise ValueError("a chart cannot match itself")
    first, second = (left, right) if left.record_id < right.record_id else (right, left)
    direct = _comparisons(first, second, swap=False)
    swapped = _comparisons(first, second, swap=True)
    alignment = "direct"
    chosen = direct
    if _swap_supported(swapped):
        direct_weight = sum(item.weight for item in direct)
        swap_weight = sum(item.weight for item in swapped)
        if swap_weight > direct_weight:
            chosen = swapped
            alignment = "swapped"
    weight = sum(item.weight for item in chosen)
    score = weight_to_score(weight)
    statuses = {item.field: item.status for item in chosen}
    grade, decision, reason = decide(score, statuses)
    return PairScore(
        record_id_1=first.record_id,
        record_id_2=second.record_id,
        weight=weight,
        score=score,
        match_grade=grade,
        decision=decision,
        decision_reason=reason,
        alignment=alignment,
        blocked_by=blocked_by,
        fields=chosen,
    )


def blocking_keys(record: MatchFeatures) -> list[str]:
    """Block keys include the scenario so two fictional populations are never compared."""
    scenario = record.scenario_key
    keys: list[str] = []
    if record.ssn_norm:
        keys.append(f"ssn:{scenario}:{record.ssn_norm}")
    if record.phone_norm:
        keys.append(f"ph:{scenario}:{record.phone_norm}")
    family_code = soundex(record.family_norm)
    given_code = soundex(first_token(record.given_norm))
    if family_code and record.birth_year:
        keys.append(f"fsy:{scenario}:{family_code}:{record.birth_year}")
    if given_code and record.birth_year:
        # Indexing the given-name soundex under fsy lets a swapped-name chart
        # share a block with the original family-name soundex.
        keys.append(f"fsy:{scenario}:{given_code}:{record.birth_year}")
        keys.append(f"gsy:{scenario}:{given_code}:{record.birth_year}")
    if given_code and record.birth_date:
        keys.append(f"gdb:{scenario}:{given_code}:{record.birth_date}")
    if family_code and record.birth_date:
        keys.append(f"fdb:{scenario}:{family_code}:{record.birth_date}")
    return keys


def _block_family(key: str) -> str:
    return key.split(":", 1)[0]


def score_candidates(records: list[MatchFeatures]) -> tuple[list[PairScore], dict[str, int]]:
    blocks: dict[str, list[str]] = {}
    by_id = {record.record_id: record for record in records}
    for record in records:
        for key in blocking_keys(record):
            blocks.setdefault(key, []).append(record.record_id)

    candidates: dict[tuple[str, str], set[str]] = {}
    skipped = 0
    max_block = 0
    for key, members in blocks.items():
        unique = sorted(set(members))
        max_block = max(max_block, len(unique))
        cap = IDENTIFIER_BLOCK_CAP if key.startswith(("ssn:", "ph:")) else BLOCK_CAP
        if len(unique) < 2 or len(unique) > cap:
            if len(unique) > cap:
                skipped += 1
            continue
        family = _block_family(key)
        for left_id, right_id in combinations(unique, 2):
            candidates.setdefault((left_id, right_id), set()).add(family)

    scored = [
        score_pair(
            by_id[left_id],
            by_id[right_id],
            blocked_by="|".join(sorted(families)),
        )
        for (left_id, right_id), families in candidates.items()
    ]
    stats = {
        "candidate_pairs": len(scored),
        "blocks_used": len(blocks) - skipped,
        "blocks_skipped": skipped,
        "max_block_size": max_block,
    }
    return scored, stats


def _survivor_sort_key(record: MatchFeatures) -> tuple:
    # Higher completeness wins, then the later chart, then registration, then id.
    return (
        -record.completeness,
        -_ordinal(record.received_date),
        SOURCE_PRIORITY.get(record.source_system_key, 9),
        record.record_id,
    )


def _ordinal(iso_date: str) -> int:
    year, month, day = (int(part) for part in iso_date.split("-"))
    return year * 10000 + month * 100 + day


def choose_survivor(members: list[MatchFeatures]) -> MatchFeatures:
    if not members:
        raise ValueError("empty cluster")
    return min(members, key=_survivor_sort_key)


def build_links(
    records: list[MatchFeatures],
    pairs: list[PairScore],
) -> tuple[list[LinkRow], list[str]]:
    """One survivor per auto-link cluster. Review pairs do not create links."""
    parent: dict[str, str] = {}

    def find(record_id: str) -> str:
        parent.setdefault(record_id, record_id)
        root = record_id
        while parent[root] != root:
            root = parent[root]
        while parent[record_id] != root:
            parent[record_id], record_id = root, parent[record_id]
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    auto = [pair for pair in pairs if pair.decision == "auto_link"]
    for pair in auto:
        union(pair.record_id_1, pair.record_id_2)

    clusters: dict[str, list[str]] = {}
    for record_id in list(parent):
        clusters.setdefault(find(record_id), []).append(record_id)

    by_id = {record.record_id: record for record in records}
    pair_index = {(pair.record_id_1, pair.record_id_2): pair for pair in auto}
    links: list[LinkRow] = []
    retired: list[str] = []
    for member_ids in clusters.values():
        members = [by_id[record_id] for record_id in member_ids]
        survivor = choose_survivor(members)
        for record in members:
            if record.record_id == survivor.record_id:
                continue
            retired.append(record.record_id)
            key = tuple(sorted((record.record_id, survivor.record_id)))
            pair = pair_index.get(key)
            score = pair.score if pair else max(item.score for item in auto)
            grade = pair.match_grade if pair else "certain"
            links.append(
                LinkRow(
                    record_id=record.record_id,
                    other_record_id=survivor.record_id,
                    link_type="replaced-by",
                    score=score,
                    match_grade=grade,
                )
            )
            links.append(
                LinkRow(
                    record_id=survivor.record_id,
                    other_record_id=record.record_id,
                    link_type="replaces",
                    score=score,
                    match_grade=grade,
                )
            )
    return links, retired
