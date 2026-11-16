-- Evaluation queries. They join the synthetic answer key.
--
-- A production extract does not have eval_ground_truth. Keep these numbers on
-- the study page of the report, separate from the operational duplicate rate.
-- record_id_1 is always the lexicographically smaller id, matching match_pair.

-- name: auto_link_confusion
-- kind: evaluation
-- purpose: True pairs, auto-link predictions, and true positives. Precision and recall are computed from these three counts.

WITH truth AS (
    SELECT g1.record_id AS record_id_1,
           g2.record_id AS record_id_2
    FROM eval_ground_truth g1
    JOIN eval_ground_truth g2
      ON g1.golden_person_id = g2.golden_person_id
     AND g1.record_id < g2.record_id
),
predicted AS (
    SELECT record_id_1, record_id_2
    FROM match_pair
    WHERE decision = 'auto_link'
)
SELECT
    (SELECT COUNT(*) FROM truth) AS true_pairs,
    (SELECT COUNT(*) FROM predicted) AS predicted_pairs,
    (
        SELECT COUNT(*)
        FROM predicted p
        JOIN truth t
          ON p.record_id_1 = t.record_id_1
         AND p.record_id_2 = t.record_id_2
    ) AS true_positives;

-- name: flagged_confusion
-- kind: evaluation
-- purpose: The same counts when a positive prediction is either an auto-link or a manual-review pair. This is the "did the queue catch it" operating point.

WITH truth AS (
    SELECT g1.record_id AS record_id_1,
           g2.record_id AS record_id_2
    FROM eval_ground_truth g1
    JOIN eval_ground_truth g2
      ON g1.golden_person_id = g2.golden_person_id
     AND g1.record_id < g2.record_id
),
predicted AS (
    SELECT record_id_1, record_id_2
    FROM match_pair
    WHERE decision IN ('auto_link', 'manual_review')
)
SELECT
    (SELECT COUNT(*) FROM truth) AS true_pairs,
    (SELECT COUNT(*) FROM predicted) AS predicted_pairs,
    (
        SELECT COUNT(*)
        FROM predicted p
        JOIN truth t
          ON p.record_id_1 = t.record_id_1
         AND p.record_id_2 = t.record_id_2
    ) AS true_positives;

-- name: injected_rate_by_source
-- kind: evaluation
-- purpose: Share of charts in each source that were injected as extra duplicate charts. The original chart of that person is not counted in the numerator.

SELECT source_system_key,
       COUNT(*) AS records,
       SUM(is_injected_duplicate) AS injected_duplicate_records,
       ROUND(1.0 * SUM(is_injected_duplicate) / COUNT(*), 4) AS injected_duplicate_rate
FROM eval_ground_truth
GROUP BY source_system_key
ORDER BY source_system_key;
