-- Lakeside Health synthetic EMPI store (SQLite).
--
-- The patient row is one source-system chart, not one real-world person.
-- Flat demographic columns are the comparison values used by matching and by
-- the data-quality queries. The child tables hold the same facts in a shape
-- closer to FHIR Patient (identifier, name, telecom, address, link).
--
-- fhir_logical_id is the Patient resource id. It is not the MRN.
-- The MRN is a row in patient_identifier with type_code MR.
--
-- eval_ground_truth is the synthetic answer key. Matching does not read it.

PRAGMA foreign_keys = ON;

CREATE TABLE scenario (
    scenario_key TEXT PRIMARY KEY,
    scenario_name TEXT NOT NULL,
    scenario_sort INTEGER NOT NULL,
    description TEXT NOT NULL,
    seed INTEGER NOT NULL
);

CREATE TABLE source_system (
    source_system_key TEXT PRIMARY KEY,
    system_uri TEXT NOT NULL,
    system_name TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE patient (
    record_id TEXT PRIMARY KEY,
    fhir_logical_id TEXT NOT NULL UNIQUE,
    scenario_key TEXT NOT NULL REFERENCES scenario(scenario_key),
    source_system_key TEXT NOT NULL REFERENCES source_system(source_system_key),
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other', 'unknown')),
    gender_raw TEXT,
    birth_date TEXT,
    birth_date_raw TEXT,
    received_date TEXT NOT NULL,
    given_name_raw TEXT,
    family_name_raw TEXT,
    middle_name_raw TEXT,
    given_name_norm TEXT,
    family_name_norm TEXT,
    middle_name_norm TEXT,
    name_use TEXT NOT NULL,
    phone_raw TEXT,
    phone_norm TEXT,
    email_raw TEXT,
    ssn_raw TEXT,
    ssn_norm TEXT,
    address_line_raw TEXT,
    address_line_norm TEXT,
    city_raw TEXT,
    city_norm TEXT,
    state_raw TEXT,
    state_norm TEXT,
    postal_code_raw TEXT,
    postal_code_norm TEXT,
    completeness_score REAL NOT NULL
);

CREATE TABLE patient_identifier (
    identifier_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    system_uri TEXT NOT NULL,
    value TEXT NOT NULL,
    type_code TEXT NOT NULL CHECK (type_code IN ('MR', 'SS')),
    UNIQUE (record_id, system_uri, type_code)
);

-- One MRN value per identifier system. Duplicate charts get a different MRN.
-- SSN is not unique: a repeated SSN is one of the signals under study.
CREATE UNIQUE INDEX ux_patient_mrn
    ON patient_identifier(system_uri, value)
    WHERE type_code = 'MR';

CREATE TABLE patient_name (
    name_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    use_code TEXT NOT NULL CHECK (use_code IN ('official', 'maiden', 'nickname', 'usual')),
    family_raw TEXT,
    given_raw TEXT,
    middle_raw TEXT,
    family_norm TEXT,
    given_norm TEXT
);

CREATE TABLE patient_telecom (
    telecom_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    system_code TEXT NOT NULL CHECK (system_code IN ('phone', 'email')),
    value_raw TEXT,
    value_norm TEXT,
    use_code TEXT
);

CREATE TABLE patient_address (
    address_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    use_code TEXT,
    line_raw TEXT,
    line_norm TEXT,
    city_raw TEXT,
    city_norm TEXT,
    state_raw TEXT,
    state_norm TEXT,
    postal_code_raw TEXT,
    postal_code_norm TEXT
);

CREATE TABLE data_quality_issue (
    issue_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    issue_type TEXT NOT NULL,
    field_name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('error', 'warning')),
    detail TEXT NOT NULL,
    UNIQUE (record_id, issue_type)
);

CREATE TABLE match_pair (
    pair_id INTEGER PRIMARY KEY,
    record_id_1 TEXT NOT NULL REFERENCES patient(record_id),
    record_id_2 TEXT NOT NULL REFERENCES patient(record_id),
    score REAL NOT NULL,
    weight_total REAL NOT NULL,
    match_grade TEXT NOT NULL CHECK (
        match_grade IN ('certain', 'probable', 'possible', 'certainly-not')
    ),
    decision TEXT NOT NULL CHECK (
        decision IN ('auto_link', 'manual_review', 'non_match')
    ),
    decision_reason TEXT NOT NULL,
    alignment TEXT NOT NULL,
    blocked_by TEXT NOT NULL,
    agreed_fields TEXT NOT NULL,
    CHECK (record_id_1 < record_id_2),
    UNIQUE (record_id_1, record_id_2)
);

-- Written only for auto-link decisions. A review pair is not yet an assertion
-- that the two charts are the same person, so it does not get a Patient.link.
CREATE TABLE patient_link (
    link_id INTEGER PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES patient(record_id),
    other_record_id TEXT NOT NULL REFERENCES patient(record_id),
    link_type TEXT NOT NULL CHECK (
        link_type IN ('replaced-by', 'replaces', 'refer', 'seealso')
    ),
    score REAL,
    match_grade TEXT NOT NULL,
    UNIQUE (record_id, other_record_id, link_type)
);

-- Synthetic answer key. Loaded after matching so the match step cannot join it
-- by accident. Do not use this table in an operational dashboard measure.
CREATE TABLE eval_ground_truth (
    record_id TEXT PRIMARY KEY REFERENCES patient(record_id),
    golden_person_id TEXT NOT NULL,
    is_injected_duplicate INTEGER NOT NULL CHECK (is_injected_duplicate IN (0, 1)),
    variant TEXT,
    parent_record_id TEXT,
    source_system_key TEXT NOT NULL
);

CREATE INDEX ix_patient_scenario ON patient(scenario_key);
CREATE INDEX ix_patient_source ON patient(source_system_key);
CREATE INDEX ix_patient_ssn ON patient(ssn_norm);
CREATE INDEX ix_patient_phone ON patient(phone_norm);
CREATE INDEX ix_patient_name_dob ON patient(family_name_norm, given_name_norm, birth_date);
CREATE INDEX ix_patient_received ON patient(received_date);
CREATE INDEX ix_issue_type ON data_quality_issue(issue_type);
CREATE INDEX ix_match_decision ON match_pair(decision);
CREATE INDEX ix_truth_golden ON eval_ground_truth(golden_person_id);
