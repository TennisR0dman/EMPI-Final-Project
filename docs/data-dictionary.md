# Data dictionary

All tables are synthetic. `eval_*` files use the injected answer key. The other files are what an analyst could build from the source feeds and the matcher.

Refresh any description from the CSVs in `outputs/` after `python -m empi`. Column order matches the files.

## Star schema

### dim_patient

One row per source chart.

| Column | Description |
| --- | --- |
| record_id | Chart id from the source extract. Primary key. Prefixed with the scenario key so two scenarios cannot share an id. |
| scenario_key | Which fictional population this chart belongs to. Filter this through `dim_scenario`, not by parsing the record id. |
| fhir_logical_id | Patient resource id. Separate from the MRN. |
| mrn_system | Identifier system URI for the MRN. |
| mrn | Medical record number value. |
| source_system_key | registration, lab, or billing. Display attribute. The filtering relationship is on the facts, not from this dimension to dim_source_system. |
| source_system_name | Registration, Laboratory, or Billing. |
| active | 1 in use, 0 not in use. Auto-link sets the retired chart to 0. |
| gender | FHIR administrative gender: male, female, other, unknown. |
| birth_date | ISO date, blank when the source value did not parse. |
| age_years | Whole years as of 2026-11-15. Blank when birth date is blank. |
| given_name, family_name | Display form of the captured name. |
| city, state, postal_code | Standardized city, USPS state, 5-digit ZIP. |

### dim_source_system

| Column | Description |
| --- | --- |
| source_system_key | Primary key. |
| system_name | Short name for visuals. |
| system_uri | FHIR identifier system for that source's MRN. |
| description | What the fictional feed represents. |

### dim_date

One row per day from 2025-01-01 through 2026-10-31. Mark `full_date` as the date table column. Relate facts on `date_key`.

| Column | Description |
| --- | --- |
| date_key | YYYYMMDD integer key. |
| full_date | Date column. |
| year, quarter, month, day | Calendar parts. |
| year_quarter | Label such as 2025 Q1. Sort by year_quarter_sort. |
| month_name | Sort by month. |
| year_month | Label such as 2025-01. Sort by year_month_sort. |
| day_name | Sort by weekday_number (Monday = 1). |

### dim_issue_type

Every check in the catalog, including checks that fired zero times.

| Column | Description |
| --- | --- |
| issue_type | Primary key. |
| severity | error or warning. |
| field_name | Field the check is about. |
| cross_record | 1 when the check compares two charts, such as a shared SSN. |
| description | Plain-language definition. |

### dim_match_grade

FHIR match-grade codes: certain, probable, possible, certainly-not. The fact table does not contain certainly-not pairs. Sort `grade_name` by `grade_sort`.

### dim_field

The nine completeness flags. `in_core_score` is 1 for the six fields inside `completeness_score`. Phone, SSN, and MRN are tracked and are outside that headline score.

### dim_scenario

One row per named population. Sort `scenario_name` by `scenario_sort`.

| Column | Description |
| --- | --- |
| scenario_key | Primary key: baseline, merger, messy_entry, hard_cases, lab_migration. |
| scenario_name | Slicer label. |
| scenario_sort | Display order. |
| description | What the scenario changes. Synthetic. |
| seed | Random seed for that scenario. |

`scenario_metrics.csv` is one row per scenario: injected duplicate rate, auto-link and flagged precision/recall/F1, false-positive counts, review queue size, mean core completeness, and the suspected duplicate record rate. Relate it only to `dim_scenario`. It uses the answer key.

`eval_summary.csv` is the same table. Import one of them.

`eval_threshold_metrics.csv`, `eval_score_histogram.csv`, and `eval_recall_by_variant.csv` also carry `scenario_key`.

## Facts

Every fact includes `scenario_key`. Relate each fact's `scenario_key` to `dim_scenario[scenario_key]`. A scenario slicer then filters charts, pairs, issues, and field completeness together.

### fact_patient

One row per chart. This is the grain for rates, completeness, and the monthly trend.

| Column | Description |
| --- | --- |
| record_id | To dim_patient. |
| source_system_key | To dim_source_system. |
| date_key | Received date, to dim_date. |
| in_auto_link | 1 when the chart is in a certain auto-link pair. |
| needs_review | 1 when the chart is in a manual-review pair and is not in an auto-link. |
| active | Same flag as the patient dimension, repeated here so a chart-level filter does not need a bidirectional relationship. |
| completeness_score | Share of the six core fields present, from 0 to 1. |
| has_* | 1 or 0 for given name, family name, birth date, known gender, street, postal code, phone, SSN, and MRN. |

### fact_match_pair

One row per candidate at or above the review threshold. On the seeded run that is 170 rows.

`record_id_1` is the lexicographically smaller chart id. `date_key` and `later_source_system_key` belong to the chart with the later received date. `survivor_record_id` and `retired_record_id` are filled only for auto-link. Names, MRNs, and source names on this table are convenience columns for the review queue.

### fact_data_quality_issue

One row per issue on one chart. A chart can have several issues. Cross-record checks still store one row per chart involved.

### fact_field_completeness

One row per chart per field (nine rows per chart). `is_present` is 1 or 0. Use it for a bar of completeness by field.

## Evaluation files

These exist because the generator kept labels. A real feed would not include them.

| File | Grain |
| --- | --- |
| eval_record.csv | One chart. `is_injected_duplicate` is 1 only on the extra chart, not on the original. |
| eval_summary.csv | One row of precision, recall, F1, and counts. |
| eval_threshold_metrics.csv | One row per score threshold from 0.50 to 0.99. |
| eval_recall_by_variant.csv | One row per injected error type. |
| eval_score_histogram.csv | Blocked pairs in 0.05 score buckets, split into true pairs and false pairs. |

## Query results

`outputs/query_results/` holds the SQL reports. `index.csv` lists each report and its row count. Definitions are the `purpose` comments in `sql/data_quality_queries.sql`.
