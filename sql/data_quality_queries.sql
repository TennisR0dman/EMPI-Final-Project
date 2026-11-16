-- Data-quality and deterministic duplicate checks for the synthetic EMPI.
--
-- Each block is one statement. The pipeline uses the name and kind comments:
--   kind: issue   -> rows are inserted into data_quality_issue
--   kind: report  -> rows are exported under outputs/query_results/
--
-- Issue SELECTs return record_id, issue_type, field_name, severity, detail.
-- Run them in DB Browser for SQLite or the sqlite3 CLI after python -m empi.
-- Dates and phones below use the standardized columns, not the raw text.

-- name: records_per_source
-- kind: report
-- purpose: Count charts by scenario and source system. This is the first reconciliation check when an extract lands.

SELECT sc.scenario_key,
       s.system_name,
       s.source_system_key,
       COUNT(p.record_id) AS record_count,
       SUM(CASE WHEN p.active = 1 THEN 1 ELSE 0 END) AS active_records,
       ROUND(AVG(p.completeness_score), 4) AS mean_core_completeness
FROM scenario sc
CROSS JOIN source_system s
LEFT JOIN patient p
    ON p.source_system_key = s.source_system_key
   AND p.scenario_key = sc.scenario_key
GROUP BY sc.scenario_key, s.system_name, s.source_system_key
ORDER BY sc.scenario_key, record_count DESC;

-- name: records_by_month
-- kind: report
-- purpose: Chart volume by the month the source record was received. The Power BI trend uses the same grain.

SELECT scenario_key,
       SUBSTR(received_date, 1, 7) AS year_month,
       source_system_key,
       COUNT(*) AS record_count
FROM patient
GROUP BY scenario_key, SUBSTR(received_date, 1, 7), source_system_key
ORDER BY scenario_key, year_month, source_system_key;

-- name: active_flag_counts
-- kind: report
-- purpose: Active versus inactive charts after auto-link survivorship. Retired duplicates are active = 0.

SELECT scenario_key,
       source_system_key,
       active,
       COUNT(*) AS record_count
FROM patient
GROUP BY scenario_key, source_system_key, active
ORDER BY scenario_key, source_system_key, active;

-- name: missing_family_name
-- kind: issue
-- purpose: Family name is required for a usable chart and for safe automatic linking.

SELECT record_id,
       'missing_family_name' AS issue_type,
       'family_name' AS field_name,
       'error' AS severity,
       'Normalized family name is blank.' AS detail
FROM patient
WHERE family_name_norm IS NULL OR TRIM(family_name_norm) = '';

-- name: missing_given_name
-- kind: issue
-- purpose: Given name is part of the core demographic set.

SELECT record_id,
       'missing_given_name' AS issue_type,
       'given_name' AS field_name,
       'error' AS severity,
       'Normalized given name is blank.' AS detail
FROM patient
WHERE given_name_norm IS NULL OR TRIM(given_name_norm) = '';

-- name: missing_birth_date
-- kind: issue
-- purpose: The source sent no birth date. Unparseable text is a different issue.

SELECT record_id,
       'missing_birth_date' AS issue_type,
       'birth_date' AS field_name,
       'error' AS severity,
       'Birth date was not sent.' AS detail
FROM patient
WHERE (birth_date IS NULL OR TRIM(birth_date) = '')
  AND (birth_date_raw IS NULL OR TRIM(birth_date_raw) = '');

-- name: invalid_birth_date
-- kind: issue
-- purpose: Text was sent but it is not a real date in range. Catches 02/31/1980, future dates, and dates before 1900.

SELECT record_id,
       'invalid_birth_date' AS issue_type,
       'birth_date' AS field_name,
       'error' AS severity,
       'Birth date text could not be parsed into a plausible ISO date.' AS detail
FROM patient
WHERE (birth_date IS NULL OR TRIM(birth_date) = '')
  AND birth_date_raw IS NOT NULL
  AND TRIM(birth_date_raw) <> '';

-- name: missing_phone
-- kind: issue
-- purpose: Phone is useful for matching and often legitimately missing, so the severity is a warning.

SELECT record_id,
       'missing_phone' AS issue_type,
       'phone' AS field_name,
       'warning' AS severity,
       'No phone number was sent.' AS detail
FROM patient
WHERE phone_raw IS NULL OR TRIM(phone_raw) = '';

-- name: invalid_phone
-- kind: issue
-- purpose: A phone value was sent and it did not normalize to 10 digits. Placeholder text lands here.

SELECT record_id,
       'invalid_phone' AS issue_type,
       'phone' AS field_name,
       'error' AS severity,
       'Phone text did not normalize to a 10-digit number.' AS detail
FROM patient
WHERE phone_raw IS NOT NULL
  AND TRIM(phone_raw) <> ''
  AND (phone_norm IS NULL OR TRIM(phone_norm) = '');

-- name: missing_ssn
-- kind: issue
-- purpose: SSN is a strong identifier when present. Absence is common and is only a warning.

SELECT record_id,
       'missing_ssn' AS issue_type,
       'ssn' AS field_name,
       'warning' AS severity,
       'No SSN was sent.' AS detail
FROM patient
WHERE ssn_raw IS NULL OR TRIM(ssn_raw) = '';

-- name: invalid_ssn
-- kind: issue
-- purpose: Structural SSN check only. Area 000, 666, and 9xx, group 00, and serial 0000 are rejected.

SELECT record_id,
       'invalid_ssn' AS issue_type,
       'ssn' AS field_name,
       'error' AS severity,
       'SSN text failed the structural format check.' AS detail
FROM patient
WHERE ssn_raw IS NOT NULL
  AND TRIM(ssn_raw) <> ''
  AND (ssn_norm IS NULL OR TRIM(ssn_norm) = '');

-- name: missing_address
-- kind: issue
-- purpose: Street line is part of core demographic completeness.

SELECT record_id,
       'missing_address' AS issue_type,
       'address' AS field_name,
       'warning' AS severity,
       'Street address is blank.' AS detail
FROM patient
WHERE address_line_raw IS NULL OR TRIM(address_line_raw) = '';

-- name: missing_postal_code
-- kind: issue
-- purpose: ZIP code supports blocking and the address corroboration rule.

SELECT record_id,
       'missing_postal_code' AS issue_type,
       'postal_code' AS field_name,
       'warning' AS severity,
       'Postal code is blank.' AS detail
FROM patient
WHERE postal_code_raw IS NULL OR TRIM(postal_code_raw) = '';

-- name: invalid_postal_code
-- kind: issue
-- purpose: Postal text was sent and it did not contain five digits.

SELECT record_id,
       'invalid_postal_code' AS issue_type,
       'postal_code' AS field_name,
       'error' AS severity,
       'Postal code text did not contain a 5-digit ZIP.' AS detail
FROM patient
WHERE postal_code_raw IS NOT NULL
  AND TRIM(postal_code_raw) <> ''
  AND (postal_code_norm IS NULL OR TRIM(postal_code_norm) = '');

-- name: invalid_state
-- kind: issue
-- purpose: State text did not map to a USPS abbreviation. Full state names that do map are not issues.

SELECT record_id,
       'invalid_state' AS issue_type,
       'state' AS field_name,
       'error' AS severity,
       'State text did not map to a USPS abbreviation.' AS detail
FROM patient
WHERE state_raw IS NOT NULL
  AND TRIM(state_raw) <> ''
  AND (state_norm IS NULL OR TRIM(state_norm) = '');

-- name: gender_unknown
-- kind: issue
-- purpose: FHIR administrative gender unknown, either because the source left it blank or sent an explicit unknown token.

SELECT record_id,
       'gender_unknown' AS issue_type,
       'gender' AS field_name,
       'warning' AS severity,
       'Administrative gender is unknown.' AS detail
FROM patient
WHERE gender = 'unknown'
  AND (
        gender_raw IS NULL
        OR TRIM(gender_raw) = ''
        OR UPPER(TRIM(gender_raw)) IN ('U', 'UNK', 'UNKNOWN')
      );

-- name: unrecognized_gender
-- kind: issue
-- purpose: The sex value was outside the source map, so ETL stored FHIR gender unknown and raised a warning.

SELECT record_id,
       'unrecognized_gender' AS issue_type,
       'gender' AS field_name,
       'warning' AS severity,
       'Sex value was not in the source map and was stored as unknown.' AS detail
FROM patient
WHERE gender_raw IS NOT NULL
  AND TRIM(gender_raw) <> ''
  AND UPPER(TRIM(gender_raw)) NOT IN (
        'M', 'MALE', 'F', 'FEMALE', 'O', 'OTHER', 'X', 'NONBINARY', 'NON-BINARY',
        'U', 'UNK', 'UNKNOWN'
      );

-- name: missing_mrn
-- kind: issue
-- purpose: Every source chart should carry an MR identifier. The resource id is not a substitute.

SELECT p.record_id,
       'missing_mrn' AS issue_type,
       'mrn' AS field_name,
       'error' AS severity,
       'No MR identifier was loaded for this chart.' AS detail
FROM patient p
WHERE NOT EXISTS (
    SELECT 1
    FROM patient_identifier i
    WHERE i.record_id = p.record_id
      AND i.type_code = 'MR'
      AND TRIM(i.value) <> ''
);

-- name: shared_ssn
-- kind: issue
-- purpose: Deterministic block. The same normalized SSN on two charts is a duplicate candidate even when the names differ.

SELECT p.record_id,
       'shared_ssn' AS issue_type,
       'ssn' AS field_name,
       'warning' AS severity,
       'Another chart has the same normalized SSN.' AS detail
FROM patient p
WHERE p.ssn_norm IS NOT NULL
  AND TRIM(p.ssn_norm) <> ''
  AND EXISTS (
      SELECT 1
      FROM patient o
      WHERE o.record_id <> p.record_id
        AND o.ssn_norm = p.ssn_norm
  );

-- name: exact_name_and_dob
-- kind: issue
-- purpose: Exact-match blocking on normalized given name, family name, and birth date. Different MRNs can still fall in one group.

SELECT p.record_id,
       'exact_name_and_dob' AS issue_type,
       'demographic' AS field_name,
       'warning' AS severity,
       'Another chart shares normalized given name, family name, and birth date.' AS detail
FROM patient p
WHERE p.given_name_norm IS NOT NULL
  AND p.family_name_norm IS NOT NULL
  AND p.birth_date IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM patient o
      WHERE o.record_id <> p.record_id
        AND o.given_name_norm = p.given_name_norm
        AND o.family_name_norm = p.family_name_norm
        AND o.birth_date = p.birth_date
  );

-- name: shared_phone_and_dob
-- kind: issue
-- purpose: Same normalized phone and same birth date. Household phones make this a review signal, not an automatic link by itself.

SELECT p.record_id,
       'shared_phone_and_dob' AS issue_type,
       'phone' AS field_name,
       'warning' AS severity,
       'Another chart shares the normalized phone number and birth date.' AS detail
FROM patient p
WHERE p.phone_norm IS NOT NULL
  AND p.birth_date IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM patient o
      WHERE o.record_id <> p.record_id
        AND o.phone_norm = p.phone_norm
        AND o.birth_date = p.birth_date
  );

-- name: exact_match_groups
-- kind: report
-- purpose: One row per exact normalized name-and-DOB group that contains more than one chart. Use this as the deterministic worklist beside the probabilistic scores.

SELECT given_name_norm,
       family_name_norm,
       birth_date,
       COUNT(*) AS chart_count,
       GROUP_CONCAT(record_id, ', ') AS record_ids
FROM patient
WHERE given_name_norm IS NOT NULL
  AND family_name_norm IS NOT NULL
  AND birth_date IS NOT NULL
GROUP BY given_name_norm, family_name_norm, birth_date
HAVING COUNT(*) > 1
ORDER BY chart_count DESC, family_name_norm, given_name_norm;

-- name: suspicious_ssn_name_conflict
-- kind: report
-- purpose: Same SSN, different normalized family name. Maiden-name duplicates and bad SSN keying both land here. A person still has to review them.

SELECT p.record_id AS record_id,
       o.record_id AS other_record_id,
       p.family_name_norm AS family_name,
       o.family_name_norm AS other_family_name,
       p.birth_date,
       o.birth_date AS other_birth_date
FROM patient p
JOIN patient o
  ON p.ssn_norm = o.ssn_norm
 AND p.record_id < o.record_id
WHERE p.ssn_norm IS NOT NULL
  AND IFNULL(p.family_name_norm, '') <> IFNULL(o.family_name_norm, '');

-- name: issue_counts
-- kind: report
-- purpose: Issue volume by type and severity. This is the same grain as the data-quality bar chart.

SELECT issue_type,
       field_name,
       severity,
       COUNT(*) AS issue_count
FROM data_quality_issue
GROUP BY issue_type, field_name, severity
ORDER BY issue_count DESC, issue_type;
