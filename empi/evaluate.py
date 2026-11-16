"""Pair-level precision, recall, and F1 against the injected duplicate labels.

Accuracy is not reported. Almost every pair of charts is a true negative, so
accuracy would look excellent even if every duplicate were missed.

A positive prediction is a pair. It is a true positive when the two charts
share a golden person id. Pairs the blocker never compared are false negatives.
"""

from collections import defaultdict
from itertools import combinations

from empi.models import PairScore


def _prf(true_positive: int, false_positive: int, false_negative: int) -> dict[str, float | int]:
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative)
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "predicted": true_positive + false_positive,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _true_pairs(truth_rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in truth_rows:
        grouped[row["golden_person_id"]].append(row["source_record_id"])
    pairs: set[tuple[str, str]] = set()
    for record_ids in grouped.values():
        ordered = sorted(record_ids)
        for left, right in combinations(ordered, 2):
            pairs.add((left, right))
    return pairs


def _variant_of(truth_rows: list[dict[str, str]], left: str, right: str) -> str:
    variants = {
        row["source_record_id"]: row.get("variant", "")
        for row in truth_rows
    }
    return variants.get(left) or variants.get(right) or "unspecified"


def evaluate(
    pairs: list[PairScore],
    truth_rows: list[dict[str, str]],
    block_stats: dict[str, int],
) -> dict:
    true_pairs = _true_pairs(truth_rows)
    scored = {(pair.record_id_1, pair.record_id_2): pair for pair in pairs}
    blocked_true = sum(1 for key in true_pairs if key in scored)

    def operating_point(decisions: set[str]) -> dict[str, float | int]:
        true_positive = 0
        false_positive = 0
        for pair in pairs:
            if pair.decision not in decisions:
                continue
            key = (pair.record_id_1, pair.record_id_2)
            if key in true_pairs:
                true_positive += 1
            else:
                false_positive += 1
        false_negative = len(true_pairs) - true_positive
        return _prf(true_positive, false_positive, false_negative)

    auto = operating_point({"auto_link"})
    flagged = operating_point({"auto_link", "manual_review"})

    by_variant: dict[str, dict[str, int]] = defaultdict(
        lambda: {"true_pairs": 0, "auto_link_tp": 0, "flagged_tp": 0}
    )
    for left, right in true_pairs:
        variant = _variant_of(truth_rows, left, right)
        bucket = by_variant[variant]
        bucket["true_pairs"] += 1
        pair = scored.get((left, right))
        if pair and pair.decision == "auto_link":
            bucket["auto_link_tp"] += 1
            bucket["flagged_tp"] += 1
        elif pair and pair.decision == "manual_review":
            bucket["flagged_tp"] += 1

    variant_rows = []
    for variant, counts in sorted(by_variant.items()):
        true_count = counts["true_pairs"]
        variant_rows.append(
            {
                "variant": variant,
                "true_pairs": true_count,
                "auto_link_tp": counts["auto_link_tp"],
                "flagged_tp": counts["flagged_tp"],
                "auto_link_recall": counts["auto_link_tp"] / true_count if true_count else 0.0,
                "flagged_recall": counts["flagged_tp"] / true_count if true_count else 0.0,
            }
        )

    curve = []
    for step in range(50, 100):
        threshold = step / 100
        predicted = [pair for pair in pairs if pair.score + 1e-12 >= threshold]
        true_positive = sum(
            1
            for pair in predicted
            if (pair.record_id_1, pair.record_id_2) in true_pairs
        )
        false_positive = len(predicted) - true_positive
        false_negative = len(true_pairs) - true_positive
        point = _prf(true_positive, false_positive, false_negative)
        curve.append(
            {
                "threshold": threshold,
                "predicted_pairs": point["predicted"],
                "true_positives": point["tp"],
                "false_positives": point["fp"],
                "false_negatives": point["fn"],
                "precision": point["precision"],
                "recall": point["recall"],
                "f1": point["f1"],
            }
        )

    histogram = []
    for index in range(20):
        floor = index / 20
        ceiling = floor + 0.05
        true_count = 0
        false_count = 0
        for pair in pairs:
            in_bucket = pair.score >= floor and (
                pair.score < ceiling or (index == 19 and pair.score <= 1)
            )
            if not in_bucket:
                continue
            if (pair.record_id_1, pair.record_id_2) in true_pairs:
                true_count += 1
            else:
                false_count += 1
        histogram.append(
            {
                "bucket_floor": round(floor, 2),
                "bucket_ceiling": round(ceiling, 2),
                "true_pair_count": true_count,
                "false_pair_count": false_count,
            }
        )

    injected = sum(int(row["is_injected_duplicate"]) for row in truth_rows)
    total = len(truth_rows)
    return {
        "total_records": total,
        "injected_duplicate_records": injected,
        "injected_duplicate_rate": injected / total if total else 0.0,
        "true_pairs": len(true_pairs),
        "true_pairs_blocked": blocked_true,
        "true_pairs_unblocked": len(true_pairs) - blocked_true,
        "candidate_pairs": block_stats.get("candidate_pairs", len(pairs)),
        "blocks_used": block_stats.get("blocks_used", 0),
        "blocks_skipped": block_stats.get("blocks_skipped", 0),
        "max_block_size": block_stats.get("max_block_size", 0),
        "auto_link": auto,
        "flagged": flagged,
        "auto_link_pairs": auto["predicted"],
        "review_pairs": flagged["predicted"] - auto["predicted"],
        "by_variant": variant_rows,
        "threshold_curve": curve,
        "histogram": histogram,
    }
