# Power BI build guide: EMPI data integrity

Build the `.pbix` yourself in Power BI Desktop. This repository does not contain one. The CSVs in `outputs/` are the semantic model's source. The seeded run behind those files is described in the README.

The skill names below follow the [PL-300 study guide](https://learn.microsoft.com/en-us/credentials/certifications/resources/study-guides/pl-300) (skills measured as of April 20, 2026).

| Exam area | Weight | What you practice here |
| --- | --- | --- |
| Prepare the data | 25–30% | Import the CSVs, set types, replace blanks, add an Age Band column, choose Import mode. |
| Model the data | 25–30% | Star schema, role-playing patient dimension, date table, DAX measures, time intelligence. |
| Visualize and analyze the data | 25–30% | Four report pages, slicers, conditional formatting, a review queue, an evaluation page. |
| Manage and secure Power BI | 15–20% | How you would publish, refresh, label, and share this dataset. Study notes, not a tenant you have to configure. |

Power BI Desktop for this exam is the Windows app. The field list after import should match [data-dictionary.md](data-dictionary.md).

## 1. Prepare the data

### 1.1 Choose Import

**Get data → Text/CSV** for each file in `outputs/`, except the files under `query_results/`. Those are SQL previews, not model tables.

Use **Import**. The files are local extracts, the model needs calculated columns, and the time-intelligence measures need an in-memory date table. DirectQuery is a poor fit for a folder of CSVs. DirectLake is a Fabric warehouse pattern, not this file set.

Import `dim_scenario.csv` and `scenario_metrics.csv`. Do not also import `eval_summary.csv`; it is the same table as `scenario_metrics.csv`. Relate `scenario_metrics` only to `dim_scenario`. The precision columns use the synthetic answer key.

### 1.2 A folder parameter, once

PL-300 asks you to create a parameter and to know what a reference query is.

1. Home → **Manage parameters** → New. Name it `FolderPath`. Type: Text. Current value: the full path to `outputs`, with a trailing slash.
2. On `fact_patient`, open Transform data. Replace the hard-coded source path with `FolderPath` plus `fact_patient.csv` if you want the parameter to be real:

```powerquery
Csv.Document(File.Contents(FolderPath & "fact_patient.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv])
```

Do that for one table so you have practiced it. The other tables can stay as normal CSV imports. Encoding 65001 is UTF-8. The files include a BOM so Desktop usually detects that on its own.

### 1.3 Set types and blanks

On each fact and dimension, in Power Query:

1. Use the column-quality and column-distribution view (**View → Column quality / Column distribution**) and note which columns are empty. That is the profile step.
2. Replace empty strings with null on text columns: select the text columns, **Transform → Replace values**, replace an empty value with `null`. Do this before you set numeric types, or a blank ZIP and a blank score become errors.
3. Set types explicitly. Do not leave them as text if the visual will aggregate them.

| Columns | Type |
| --- | --- |
| `date_key`, `year`, `quarter`, `month`, `day`, `year_month_sort`, `year_quarter_sort`, `weekday_number`, `grade_sort`, `field_sort`, `active`, `in_auto_link`, `needs_review`, `is_present`, `has_*`, `cross_record`, `in_core_score`, `is_injected_duplicate` | Whole number |
| `completeness_score`, `score`, `weight_total`, `auto_link_precision`, `auto_link_recall`, `auto_link_f1`, `flagged_precision`, `flagged_recall`, `flagged_f1`, `injected_duplicate_rate`, threshold metrics | Decimal number |
| `full_date`, `birth_date` | Date |
| `postal_code`, `mrn`, `record_id`, `fhir_logical_id`, `date_key` if you prefer to keep the key as text | Text for postal code, MRN, and ids. `date_key` stays a whole number because it is the relationship key. |
| Names, grades, decisions, descriptions | Text |

`postal_code` must stay text. A numeric type drops the leading zero on ZIP codes such as `021xx`.

`age_years` arrives as text because blank ages are empty. Set it to Whole number after the blank-to-null step.

### 1.4 Age Band in Power Query

The pipeline already calculated `age_years` as of 2026-11-15. Add the band yourself. This is a custom column, which is the exam's "create and transform columns" task.

On `dim_patient`: **Add Column → Custom column**. Name: `Age Band`.

```powerquery
if [age_years] = null then "Unknown"
else if [age_years] < 18 then "0-17"
else if [age_years] < 40 then "18-39"
else if [age_years] < 65 then "40-64"
else "65+"
```

Close and apply when every table has types. If a column shows errors after the type change, fix the type. Do not delete the rows. The quality story is about bad values that were already separated into `fact_data_quality_issue`.

### 1.5 Keys

Each dimension has one key, named in the dictionary. Facts store those keys. You do not need to merge the CSVs in Power Query. They are already separate tables. Merging them into one wide table would destroy the star schema.

`fact_field_completeness` is the unpivoted form of the `has_*` columns. If you want the unpivot practice: reference `fact_patient` (**right-click → Reference**, not Duplicate), keep `record_id`, `source_system_key`, `date_key`, and the `has_*` columns, then **Unpivot Other Columns** on the `has_*` columns. A reference keeps one upstream query. A duplicate copies the steps and then drifts. Compare the row count with the provided file (nine rows per chart) and then remove your practice query so you do not load two copies.

## 2. Model the data

### 2.1 Relationships

Model view. Create only these relationships. Cardinality is many-to-one. Cross-filter direction is **single**, from the dimension to the fact.

| From (many) | To (one) |
| --- | --- |
| fact_patient[record_id] | dim_patient[record_id] |
| fact_patient[source_system_key] | dim_source_system[source_system_key] |
| fact_patient[date_key] | dim_date[date_key] |
| fact_match_pair[record_id_1] | dim_patient[record_id] |
| fact_match_pair[record_id_2] | dim_patient[record_id] |
| fact_match_pair[later_source_system_key] | dim_source_system[source_system_key] |
| fact_match_pair[date_key] | dim_date[date_key] |
| fact_match_pair[match_grade] | dim_match_grade[match_grade] |
| fact_data_quality_issue[record_id] | dim_patient[record_id] |
| fact_data_quality_issue[source_system_key] | dim_source_system[source_system_key] |
| fact_data_quality_issue[date_key] | dim_date[date_key] |
| fact_data_quality_issue[issue_type] | dim_issue_type[issue_type] |
| fact_field_completeness[record_id] | dim_patient[record_id] |
| fact_field_completeness[source_system_key] | dim_source_system[source_system_key] |
| fact_field_completeness[date_key] | dim_date[date_key] |
| fact_field_completeness[field_key] | dim_field[field_key] |
| fact_patient[scenario_key] | dim_scenario[scenario_key] |
| fact_match_pair[scenario_key] | dim_scenario[scenario_key] |
| fact_data_quality_issue[scenario_key] | dim_scenario[scenario_key] |
| fact_field_completeness[scenario_key] | dim_scenario[scenario_key] |
| scenario_metrics[scenario_key] | dim_scenario[scenario_key] |
| eval_threshold_metrics[scenario_key] | dim_scenario[scenario_key] |
| eval_recall_by_variant[scenario_key] | dim_scenario[scenario_key] |
| eval_score_histogram[scenario_key] | dim_scenario[scenario_key] |
| eval_record[scenario_key] | dim_scenario[scenario_key] |

The second patient relationship (`record_id_2`) is inactive. Power BI allows one active path between two tables. Leave `record_id_1` active. The measure `Record 2 Family Name` uses `USERELATIONSHIP` for the inactive path. That is the role-playing dimension pattern on the exam.

Do not relate `dim_patient[source_system_key]` to `dim_source_system`. The source key on the patient dimension is a label. A second path would make filters ambiguous.

`scenario_metrics` is related to `dim_scenario` in the table above. Do not also relate it to the date table. A date slicer should not blank the precision cards.

`eval_record[scenario_key]` is already related to `dim_scenario`. You can also relate `eval_record[record_id]` to `dim_patient[record_id]` if you want names beside the answer key. Keep that page free of the operational rate cards.

### 2.2 Date table and sort order

1. Select `dim_date`. **Table tools → Mark as date table**. Date column: `full_date`.
2. Sort `dim_scenario[scenario_name]` by `scenario_sort`.
3. Sort by column:
   - `month_name` by `month`
   - `day_name` by `weekday_number`
   - `year_month` by `year_month_sort`
   - `year_quarter` by `year_quarter_sort`
   - `dim_match_grade[grade_name]` by `grade_sort`
   - `dim_field[field_name]` by `field_sort`
4. Create a hierarchy on `dim_date`: Year → Year Quarter → Year Month. Name it `Calendar`.
5. In Model view, hide the key and sort columns from report view: `date_key`, `year_month_sort`, `year_quarter_sort`, `weekday_number`, `grade_sort`, `field_sort`. Relationships keep working after a column is hidden.

### 2.3 Measures

Open `docs/dax-measures.dax`. Create each measure. A measure table keeps the field list readable: **Enter data**, make a one-column table named `Measures` with a single unused row, load it, put the measures there, then hide the dummy column.

Read the comment above each measure before you use it. In particular:

- **Suspected Duplicate Record Rate** counts charts. A linked pair contributes two charts.
- **Estimated Extra Chart Rate** counts auto-link pairs. On this file that is 160 / 8,170.
- **Known Injected Duplicate Rate** is the generator's 170 / 8,170. It uses the answer key.

After the measures exist, use **Performance analyzer** (View → Performance analyzer) on the overview page once. You are looking for the habit, not a slow visual. This model is small.

## 3. Visualize and analyze

Use a plain theme with a dark text color and one accent. Grade must not be communicated by color alone. Put the grade name on the visual.

Build four pages. Add a text box on each page that states the grain in one sentence.

### Page 1. Data integrity overview

Slicers: `dim_scenario[scenario_name]`, `dim_source_system[system_name]`, `dim_date[year]`, `dim_date[year_month]`. Sync the scenario slicer to every page, and the source slicer to pages 2 and 3 (**View → Sync slicers**). Leave the scenario slicer on **Baseline** while you check the first three pages. The default multi-select would mix five populations into one rate.

Cards:

- Record Count
- Suspected Duplicate Record Rate, as a percentage
- Data Completeness %
- Records Needing Review
- Issue Count
- Issues per 100 Records

Clustered bar: axis `dim_source_system[system_name]`, values Issue Count and Record Count. Turn on **data labels**.

Line chart: axis `dim_date[year_month]`, values Issue Count and Suspected Duplicate Record Rate. The rate stays interpretable if the line uses a secondary axis or its own small chart. A combo chart is fine.

Bar: axis `dim_field[field_name]`, value Field Completeness %. This is the chart that shows SSN and phone lagging the core demographics.

Matrix (optional): rows `Calendar` hierarchy, values Issue Count, and Issue Count MoM % as a second value. Expand to month and confirm the prior-month measure is blank on January 2025, the first month in the date table.

### Page 2. Duplicate review queue

This page is the work queue. Auto-link has already retired one chart of each certain pair. Review pairs do not have a `Patient.link` yet.

Slicer: `fact_match_pair[decision]`, default selection `manual_review`. Second slicer: `dim_match_grade[grade_name]`.

Cards: Auto Link Pair Count, Pairs Needing Review, Certain Pair Count, Probable Pair Count, Possible Pair Count.

Table, at the pair grain. Because `record_id_2` is an inactive relationship, the easy path is the convenience columns already on the fact:

- record_1_name, record_1_mrn, record_1_source
- record_2_name, record_2_mrn, record_2_source
- score, match_grade, decision, decision_reason, agreed_fields

Sort by score descending. Add data bars on score (**conditional formatting → data bars**).

To practice `USERELATIONSHIP`, add the measure `Record 2 Family Name` as a column and confirm it matches `record_2_name`'s family name.

Donut or bar of Match Pair Count by `dim_match_grade[grade_name]`. Include the grade name, not only a color.

A bookmark named `Review only` that hides the auto-link rows (via the decision slicer) is enough bookmark practice. Add a button that applies it.

### Page 3. Data quality by source

Slicers: source, severity (`fact_data_quality_issue[severity]` or `dim_issue_type[severity]`), year_month.

Stacked bar: axis `dim_issue_type[issue_type]`, legend severity, value Issue Count. Sort by Issue Count.

Matrix: rows issue type, columns source system, values Issue Count. This is the "which feed is dirty" view.

Table of example issues if you want drillthrough: from the bar, **drillthrough** to a hidden page filtered to one issue type, showing `dim_patient[record_id]`, name, source, and received month. Create the drillthrough page, set it to keep all filters, and add a back button.

On the main page, set alt text on the bar and the matrix (**Format → General → Alt text**). That is the accessibility item. Also check **View → Selection** order so the tab order follows the page from the slicers to the charts.

### Page 4. Evaluation, synthetic labels only

Title the page so a viewer cannot mistake it for an operational KPI: "Evaluation against injected labels. Not available on a real feed."

Cards from `eval_summary`: Auto Link Precision, Auto Link Recall, Auto Link F1, Flagged Precision, Flagged Recall, Flagged F1, Known Injected Duplicate Rate.

Line chart from `eval_threshold_metrics`: axis `threshold`, values `precision`, `recall`, `f1`. On this file the lines stay at 1 until the threshold starts to pass the name-and-date-only pairs. Say that in a subtitle so the flat line is a finding, not a broken visual.

Clustered column from `eval_score_histogram`: axis `bucket_floor`, values `true_pair_count` and `false_pair_count`. The false pairs sit in the first bucket. The true pairs sit at the right. Put the counts in the tooltip.

Bar from `eval_recall_by_variant`: axis `variant`, values `auto_link_recall` and `flagged_recall`. `name_dob_only` is the row where auto-link recall is 0 and flagged recall is 1.

Do not add the operational duplicate-rate card to this page. The two definitions answer different questions.

With the scenario slicer on Baseline, auto-link F1 is 0.970 and flagged F1 is 1. Change the slicer to Hard cases and auto-link precision falls to about 0.65, with 35 false positives. That is the point of the slicer.

### Page 5. Scenario comparison

Title: "Five synthetic populations. Not five hospitals."

No date slicer on this page. Keep the scenario slicer, set to all five.

Matrix, rows `dim_scenario[scenario_name]`. Values from `scenario_metrics`, with summarization set to **Don't summarize** (each scenario is one row, so a sum would be an accident):

- injected_duplicate_rate
- auto_link_precision, auto_link_recall, auto_link_f1
- auto_link_fp
- review_pairs
- flagged_precision, flagged_recall, flagged_f1
- mean_completeness

Clustered column: axis scenario name, values Auto Link F1 and Flagged F1.

Line chart from `eval_threshold_metrics`: axis `threshold`, legend `dim_scenario[scenario_name]`, values `precision` and, on a second chart, `recall`. Hard cases is the line that leaves 1.0. Lab migration is the line whose recall never reaches 1, because five true pairs never entered a block.

#### What-if threshold

This is the PL-300 numeric-parameter pattern. The curve above is score-only: a pair counts as predicted when its score is at least the cutoff. It does not re-apply the corroboration rule or the SSN and gender vetoes. The cards use the full policy. Say that in a subtitle.

1. **Modeling → New parameter → Numeric range**.
2. Name: `Auto Link Threshold`. Minimum 0.50, maximum 0.99, increment 0.01, default 0.95. Add it as a slicer.
3. Paste `What-If Precision`, `What-If Recall`, and `What-If F1` from `docs/dax-measures.dax`.
4. Put the three measures on cards. Move the slicer from 0.95 to 0.55 with **Hard cases** selected and watch precision rise as the cutoff gets stricter, and recall fall. On Baseline the precision card stays at 1 across that range; recall drops once the cutoff passes the name-and-date-only pairs (they sit near 0.70–0.85).

A second parameter for a review floor is the same click path. One parameter is enough to practice the skill.

### A few visual checks

- Source slicer on page 1 changes Record Count, Issue Count, and the duplicate rate together. If only one of them moves, a relationship is missing.
- January 2025 has no prior month. Issue Count MoM % is blank, not an error.
- With the scenario slicer on Baseline, filtering the review page to `manual_review` shows 10 pairs.
- Certain pairs have a survivor and a retired chart. Review pairs leave those two columns blank.
- Field completeness for SSN is visibly lower than for given name. If it is not, `fact_field_completeness` is not related to `dim_field`.

## 4. Manage and secure

You can stop after the Desktop model and still have the portfolio piece. This section is the exam vocabulary for what happens after Desktop. It does not describe a workspace that was set up for this project.

**Publish.** Home → Publish, to a workspace you can use for study. The report and the semantic model land as two items.

**Workspace roles.** Admin, Member, Contributor, and Viewer are the four roles. A Viewer consumes. A Contributor builds. Publishing and granting access sit with higher roles. Know which role can add users and which can only read.

**App versus workspace.** A workspace is where you edit. An app is a curated package for readers. For a data-quality review queue, an app with a link to the review page is the distribution method you would explain. Sharing the workspace itself is for builders.

**Refresh.** These CSVs live in a local folder. The Power BI service cannot see that folder on a laptop. Scheduled refresh of a local file needs a gateway on a machine that can read the path, or the files need to move to a source the service can reach (for example SharePoint or a lakehouse). The exam item is "identify when a gateway is required." For this project, a gateway would be required if you kept the files on a private disk and still wanted a scheduled refresh. Re-running `python -m empi` and refreshing Desktop is the path this repository actually supports.

**Sensitivity.** Apply a label if your tenant has them. The habit matters. The contents here are synthetic, and the label text should say that rather than imply a hospital data classification you do not have.

**Row-level security.** This model has no user or facility column, so there is no honest RLS role to ship. For study: create a role, put a DAX filter on a dimension, and use **View as role**. Then delete the role if it does not correspond to a real rule. Do not leave a filter that hides rows for a reason you cannot explain.

**Endorse.** Promote means "someone on the team trusts this." Certify is a tighter, usually admin-controlled mark. A portfolio file on a personal workspace does not need either. Know the difference for the exam.

**Dashboard.** Pin one card from the overview page to a dashboard if you want the pin-and-alert experience. An alert on Issue Count is the kind of alert the exam describes. It is optional.

## 5. Numbers to expect from the seeded files

`outputs/scenario_metrics.csv` is the check. With the slicer on one scenario, the cards should match that row.

| Scenario | Charts | Injected rate | Auto-link P / R / F1 | Auto-link FP | Review pairs | Flagged P / R / F1 | Mean core completeness |
| --- | ---: | ---: | --- | ---: | ---: | --- | ---: |
| Baseline | 8,170 | 0.020808 | 1.000 / 0.941 / 0.970 | 0 | 10 | 1.000 / 1.000 / 1.000 | 0.990 |
| Hospital merger | 4,400 | 0.090909 | 1.000 / 0.940 / 0.969 | 0 | 24 | 1.000 / 1.000 / 1.000 | 0.990 |
| Messy data entry | 3,080 | 0.025974 | 1.000 / 0.938 / 0.968 | 0 | 5 | 1.000 / 1.000 / 1.000 | 0.952 |
| Hard cases | 2,570 | 0.027237 | 0.653 / 0.943 / 0.772 | 35 | 16 | 0.598 / 1.000 / 0.749 | 0.990 |
| Lab migration | 3,090 | 0.029126 | 1.000 / 0.800 / 0.889 | 0 | 13 | 1.000 / 0.944 / 0.971 | 0.977 |

Baseline registration / lab / billing counts are still 5,836 / 1,340 / 994. Filter `records_per_source` to `baseline` before comparing.

If a card disagrees, the usual causes are a bidirectional filter, a missing scenario relationship, or a slicer left on every scenario while the measure is `SELECTEDVALUE` (that card should be blank).
