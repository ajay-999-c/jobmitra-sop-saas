-- Staging snapshot only. Not a live PostgreSQL backend migration.

-- TEXT dates/JSON preserve the exact SQLite representation.

-- Salary NUMERIC has no typmod: no implicit rounding or scale truncation.

CREATE SCHEMA jobmitra_v12_stage;

REVOKE ALL ON SCHEMA jobmitra_v12_stage FROM PUBLIC;

CREATE TABLE jobmitra_v12_stage.candidates (
    id                      BIGINT PRIMARY KEY,
    candidate_code          TEXT UNIQUE,
    full_name               TEXT NOT NULL CHECK(length(trim(full_name))>0),
    phone                   TEXT,
    phone_normalized        TEXT,
    email                   TEXT,
    email_normalized        TEXT,
    links_json              TEXT NOT NULL DEFAULT '{}' CHECK((links_json IS JSON)),
    job_title               TEXT,
    current_employer        TEXT,
    current_city            TEXT,
    preferred_cities_json   TEXT NOT NULL DEFAULT '[]' CHECK((preferred_cities_json IS JSON)),
    experience_years        DOUBLE PRECISION CHECK(experience_years IS NULL OR experience_years >= 0),
    qualification           TEXT,
    primary_domain          TEXT,
    skills_json             TEXT NOT NULL DEFAULT '[]' CHECK((skills_json IS JSON)),
    professional_summary    TEXT,
    search_text             TEXT,
    current_salary_inr      NUMERIC CHECK(current_salary_inr IS NULL OR current_salary_inr >= 0),
    current_salary_period   TEXT CHECK(current_salary_period IS NULL OR current_salary_period IN ('MONTHLY','ANNUAL')),
    current_salary_basis    TEXT CHECK(current_salary_basis IS NULL OR current_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    expected_salary_inr     NUMERIC CHECK(expected_salary_inr IS NULL OR expected_salary_inr >= 0),
    expected_salary_period  TEXT CHECK(expected_salary_period IS NULL OR expected_salary_period IN ('MONTHLY','ANNUAL')),
    expected_salary_basis   TEXT CHECK(expected_salary_basis IS NULL OR expected_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    notice_days             BIGINT CHECK(notice_days IS NULL OR notice_days >= 0),
    availability            TEXT NOT NULL DEFAULT 'TO_CONFIRM' CHECK(availability IN ('AVAILABLE','TO_CONFIRM','UNAVAILABLE')),
    source                  TEXT NOT NULL DEFAULT 'MANUAL' CHECK(source IN ('MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER')),
    is_active               BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at              TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    updated_at              TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
, legacy_postgres_id TEXT, source_json TEXT CHECK(source_json IS NULL OR (source_json IS JSON)), source_fingerprint TEXT, imported_at TEXT);

CREATE TABLE jobmitra_v12_stage.companies (
    id                          TEXT PRIMARY KEY CHECK(length(id)=36),
    legacy_postgres_id          TEXT UNIQUE,
    company_name                TEXT NOT NULL CHECK(length(trim(company_name))>0),
    company_name_key            TEXT NOT NULL UNIQUE CHECK(length(trim(company_name_key))>0),
    general_phone_numbers_json  TEXT NOT NULL DEFAULT '[]' CHECK((general_phone_numbers_json IS JSON) AND json_typeof(general_phone_numbers_json::json)='array'),
    contacts_json               TEXT NOT NULL DEFAULT '[]' CHECK((contacts_json IS JSON) AND json_typeof(contacts_json::json)='array'),
    address_line                TEXT,
    city                        TEXT,
    state                       TEXT,
    postal_code                 TEXT,
    source_register_ids_json    TEXT NOT NULL DEFAULT '[]' CHECK((source_register_ids_json IS JSON) AND json_typeof(source_register_ids_json::json)='array'),
    is_active                   BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at                  TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    updated_at                  TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    source_json                 TEXT CHECK(source_json IS NULL OR (source_json IS JSON)),
    source_fingerprint          TEXT,
    imported_at                 TEXT
, audit_request_key TEXT, audit_request_fingerprint TEXT, audit_actor_name TEXT, audit_actor_role TEXT);

CREATE TABLE jobmitra_v12_stage.job_descriptions (
    id                  BIGINT PRIMARY KEY,
    jd_code             TEXT NOT NULL UNIQUE,
    company_id          TEXT NOT NULL CHECK(length(company_id)=36 AND substr(company_id,9,1)='-' AND substr(company_id,14,1)='-' AND substr(company_id,19,1)='-' AND substr(company_id,24,1)='-'),
    title               TEXT NOT NULL CHECK(length(trim(title)) > 0),
    company_contact     TEXT,
    location            TEXT,
    work_mode           TEXT CHECK(work_mode IS NULL OR work_mode IN ('ONSITE','HYBRID','REMOTE')),
    vacancies           BIGINT CHECK(vacancies IS NULL OR vacancies > 0),
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','ACTIVE','ON_HOLD','CLOSED')),
    created_at          TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    target_date         TEXT,
    is_legacy_import    BIGINT NOT NULL DEFAULT 0 CHECK(is_legacy_import IN (0,1)),
    skills_json         TEXT NOT NULL DEFAULT '[]' CHECK((skills_json IS JSON)),
    experience_min      DOUBLE PRECISION CHECK(experience_min IS NULL OR experience_min >= 0),
    experience_max      DOUBLE PRECISION CHECK(experience_max IS NULL OR experience_max >= 0),
    qualification       TEXT,
    salary_min_inr      NUMERIC CHECK(salary_min_inr IS NULL OR salary_min_inr >= 0),
    salary_max_inr      NUMERIC CHECK(salary_max_inr IS NULL OR salary_max_inr >= 0),
    salary_period       TEXT CHECK(salary_period IS NULL OR salary_period IN ('MONTHLY','ANNUAL')),
    salary_basis        TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(salary_basis IN ('UNKNOWN','CTC','GROSS','IN_HAND')),
    requirement_notes   TEXT,
    full_jd             TEXT,
    workflow_mode       TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(workflow_mode IN ('UNKNOWN','DIRECT','CONFIGURED')),
    workflow_version    BIGINT NOT NULL DEFAULT 0 CHECK(workflow_version >= 0),
    owner_name          TEXT,
    updated_at          TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')), company_contact_id TEXT, company_contact_name_snapshot TEXT, company_contact_email_snapshot TEXT, contact_request_key TEXT, contact_request_fingerprint TEXT, contact_actor_name TEXT, contact_actor_role TEXT,
    CHECK(target_date IS NOT NULL OR is_legacy_import = 1),
    CHECK(target_date IS NULL OR target_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
    CHECK(target_date IS NULL OR is_legacy_import=1 OR target_date >= ((created_at::timestamptz AT TIME ZONE 'Asia/Kolkata')::date)::text),
    CHECK(experience_min IS NULL OR experience_max IS NULL OR experience_max >= experience_min),
    CHECK(salary_min_inr IS NULL OR salary_max_inr IS NULL OR salary_max_inr >= salary_min_inr)
);

CREATE TABLE jobmitra_v12_stage.jd_interview_rounds (
    id              TEXT PRIMARY KEY,           
    job_id          BIGINT NOT NULL REFERENCES jobmitra_v12_stage.job_descriptions(id) ON DELETE RESTRICT,
    round_name      TEXT NOT NULL CHECK(length(trim(round_name)) >= 3),
    display_order   BIGINT NOT NULL CHECK(display_order >= 1),
    mode            TEXT NOT NULL DEFAULT 'FLEXIBLE' CHECK(mode IN ('FLEXIBLE','FACE_TO_FACE','VIDEO','PHONE')),
    is_active       BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    retired_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    UNIQUE(job_id, id)
);

CREATE TABLE jobmitra_v12_stage.jd_candidates (
    id                      BIGINT PRIMARY KEY,
    job_id                  BIGINT NOT NULL REFERENCES jobmitra_v12_stage.job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            BIGINT NOT NULL REFERENCES jobmitra_v12_stage.candidates(id) ON DELETE RESTRICT,
    stage_code              TEXT NOT NULL DEFAULT 'POOL' CHECK(stage_code IN (
                              'POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND','SELECTED','JOINED','NOT_SELECTED')),
    round_id                TEXT,
    stage_note              TEXT,
    rejected_from_stage     TEXT,
    rejected_round_name     TEXT,
    rejected_round_index    BIGINT,
    rejected_at             TEXT,
    added_by                TEXT,
    changed_by              TEXT,
    added_at                TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    stage_updated_at        TEXT, selection_outcome TEXT CHECK(selection_outcome IS NULL OR selection_outcome IN ('PENDING_JOINING','JOINED_CONFIRMED','NOT_JOINED','SELECTION_CANCELLED')), selected_on TEXT, selected_at_utc TEXT, joined_on TEXT, joining_confirmed_at_utc TEXT, outcome_closed_on TEXT, outcome_reason TEXT, eligibility_released_at_utc TEXT, eligibility_release_reason TEXT, confirmation_evidence TEXT, action_actor_name TEXT, action_actor_role TEXT, action_request_key TEXT, action_request_fingerprint TEXT,
    UNIQUE(job_id, candidate_id),
    CHECK((stage_code = 'ROUND' AND round_id IS NOT NULL) OR (stage_code <> 'ROUND' AND round_id IS NULL)),
    FOREIGN KEY(job_id, round_id) REFERENCES jobmitra_v12_stage.jd_interview_rounds(job_id,id) ON DELETE RESTRICT
);

CREATE TABLE jobmitra_v12_stage.candidate_resumes (
    id                  BIGINT PRIMARY KEY,
    candidate_id        BIGINT NOT NULL REFERENCES jobmitra_v12_stage.candidates(id) ON DELETE RESTRICT,
    source_type         TEXT NOT NULL CHECK(source_type IN ('UPLOADED','FOUNDIT_PASTE','GENERATED')),
    resume_kind         TEXT NOT NULL CHECK(resume_kind IN ('ORIGINAL','JOBMITRA_STANDARD','PARSED_TEXT')),
    original_filename   TEXT,
    storage_path        TEXT,
    raw_text            TEXT,
    parsed_json         TEXT CHECK(parsed_json IS NULL OR (parsed_json IS JSON)),
    is_current          BIGINT NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    created_at          TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')), legacy_source_table TEXT, legacy_postgres_id TEXT, source_json TEXT CHECK(source_json IS NULL OR (source_json IS JSON)), imported_at TEXT,
    CHECK(storage_path IS NOT NULL OR raw_text IS NOT NULL OR parsed_json IS NOT NULL)
);

CREATE TABLE jobmitra_v12_stage.candidate_activities (
    id              BIGINT PRIMARY KEY,
    candidate_id    BIGINT NOT NULL REFERENCES jobmitra_v12_stage.candidates(id) ON DELETE RESTRICT,
    job_id          BIGINT REFERENCES jobmitra_v12_stage.job_descriptions(id) ON DELETE RESTRICT,
    activity_type   TEXT NOT NULL CHECK(activity_type IN ('FOLLOW_UP','OFFICE_VISIT','JOB_SEARCH_REQUEST','CALL','INTERVIEW','CANDIDATE_SUBMISSION','OTHER')),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DONE','CANCELLED')),
    due_at          TEXT,
    occurred_at     TEXT,
    notes           TEXT,
    details_json    TEXT NOT NULL DEFAULT '{}' CHECK((details_json IS JSON)),
    assigned_to     TEXT,
    created_at      TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
);

CREATE TABLE jobmitra_v12_stage.recruitment_events (
    id                      BIGINT PRIMARY KEY,
    job_id                  BIGINT REFERENCES jobmitra_v12_stage.job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            BIGINT REFERENCES jobmitra_v12_stage.candidates(id) ON DELETE RESTRICT,
    jd_candidate_id         BIGINT REFERENCES jobmitra_v12_stage.jd_candidates(id) ON DELETE RESTRICT,
    event_type              TEXT NOT NULL,
    from_stage              TEXT,
    to_stage                TEXT,
    from_label_snapshot     TEXT,
    to_label_snapshot       TEXT,
    feedback                TEXT,
    feedback_source         TEXT CHECK(feedback_source IS NULL OR feedback_source IN ('COMPANY','JOBMITRA','CANDIDATE','NOT_SPECIFIED')),
    workflow_version        BIGINT,
    payload_json            TEXT NOT NULL DEFAULT '{}' CHECK((payload_json IS JSON)),
    before_json             TEXT CHECK(before_json IS NULL OR (before_json IS JSON)),
    after_json              TEXT CHECK(after_json IS NULL OR (after_json IS JSON)),
    actor_name              TEXT,  
    created_at              TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    CHECK(job_id IS NOT NULL OR candidate_id IS NOT NULL)
);

CREATE TABLE jobmitra_v12_stage.company_audit_events (
    id BIGINT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES jobmitra_v12_stage.companies(id) ON DELETE RESTRICT,
    action TEXT NOT NULL,
    before_json TEXT CHECK(before_json IS NULL OR (before_json IS JSON)),
    after_json TEXT CHECK(after_json IS NULL OR (after_json IS JSON)),
    actor_staff_id TEXT,
    actor_name_snapshot TEXT,
    actor_verification_status TEXT,
    source_system TEXT,
    source_event_id TEXT,
    request_fingerprint TEXT,
    created_at TEXT NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    UNIQUE(source_system,source_event_id)
);

CREATE TABLE jobmitra_v12_stage.candidate_profile_versions (
 id BIGINT PRIMARY KEY,
 candidate_id BIGINT NOT NULL REFERENCES jobmitra_v12_stage.candidates(id) ON DELETE RESTRICT,
 profile_json TEXT NOT NULL CHECK((profile_json IS JSON)),
 before_json TEXT NOT NULL CHECK((before_json IS JSON)),
 after_json TEXT NOT NULL CHECK((after_json IS JSON)),
 provenance_json TEXT NOT NULL CHECK((provenance_json IS JSON)),
 actor_name TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 created_at TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);

CREATE TABLE jobmitra_v12_stage.company_proposals (
 id TEXT PRIMARY KEY,
 company_id TEXT NOT NULL REFERENCES jobmitra_v12_stage.companies(id) ON DELETE RESTRICT,
 contact_id TEXT,
 reference TEXT NOT NULL UNIQUE,
 issue_date TEXT NOT NULL,
 fee_basis_points BIGINT NOT NULL CHECK(fee_basis_points IN (600,833)),
 snapshot_json TEXT NOT NULL CHECK((snapshot_json IS JSON)),
 pdf_key TEXT NOT NULL UNIQUE,
 pdf_sha256 TEXT NOT NULL CHECK(length(pdf_sha256)=64),
 pdf_size BIGINT NOT NULL CHECK(pdf_size>0),
 created_at TEXT NOT NULL,
 prepared_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);

CREATE TABLE jobmitra_v12_stage.company_proposal_signed_documents (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES jobmitra_v12_stage.company_proposals(id) ON DELETE RESTRICT,
 storage_key TEXT NOT NULL UNIQUE,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64),
 size BIGINT NOT NULL CHECK(size>0),
 original_filename TEXT NOT NULL,
 uploaded_at TEXT NOT NULL,
 uploaded_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);

CREATE TABLE jobmitra_v12_stage.company_proposal_status_events (
 id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES jobmitra_v12_stage.company_proposals(id) ON DELETE RESTRICT,
 status TEXT NOT NULL CHECK(status IN ('SENT','ACCEPTED','DECLINED')),
 evidence TEXT NOT NULL,
 effective_date TEXT NOT NULL,
 authorized_signatory TEXT,
 signed_document_id TEXT REFERENCES jobmitra_v12_stage.company_proposal_signed_documents(id) ON DELETE RESTRICT,
 created_at TEXT NOT NULL,
 recorded_by TEXT NOT NULL,
 actor_role TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 request_hash TEXT NOT NULL
);

ALTER TABLE jobmitra_v12_stage.job_descriptions ADD FOREIGN KEY(company_id) REFERENCES jobmitra_v12_stage.companies(id) ON DELETE RESTRICT;

ALTER TABLE jobmitra_v12_stage.jd_candidates ADD UNIQUE(id,job_id,candidate_id);

ALTER TABLE jobmitra_v12_stage.recruitment_events ADD FOREIGN KEY(jd_candidate_id,job_id,candidate_id) REFERENCES jobmitra_v12_stage.jd_candidates(id,job_id,candidate_id) ON DELETE RESTRICT;

ALTER TABLE jobmitra_v12_stage.company_proposal_signed_documents ADD UNIQUE(proposal_id,id);

ALTER TABLE jobmitra_v12_stage.company_proposal_status_events ADD FOREIGN KEY(proposal_id,signed_document_id) REFERENCES jobmitra_v12_stage.company_proposal_signed_documents(proposal_id,id) ON DELETE RESTRICT;

CREATE INDEX idx_activities_due ON jobmitra_v12_stage.candidate_activities(status,activity_type,due_at);

CREATE INDEX idx_ats_company_options ON jobmitra_v12_stage.companies(is_active,company_name_key,id);

CREATE INDEX idx_candidate_resumes_history ON jobmitra_v12_stage.candidate_resumes(candidate_id, created_at DESC);

CREATE INDEX idx_candidates_city ON jobmitra_v12_stage.candidates(current_city);

CREATE INDEX idx_candidates_email_normalized ON jobmitra_v12_stage.candidates(email_normalized);

CREATE INDEX idx_candidates_experience ON jobmitra_v12_stage.candidates(experience_years);

CREATE INDEX idx_candidates_name ON jobmitra_v12_stage.candidates(lower(full_name));

CREATE INDEX idx_candidates_notice ON jobmitra_v12_stage.candidates(notice_days);

CREATE INDEX idx_candidates_phone_normalized ON jobmitra_v12_stage.candidates(phone_normalized);

CREATE INDEX idx_candidates_salary ON jobmitra_v12_stage.candidates(expected_salary_basis, expected_salary_period, expected_salary_inr);

CREATE INDEX idx_candidates_updated ON jobmitra_v12_stage.candidates(updated_at DESC);

CREATE INDEX idx_company_audit_time ON jobmitra_v12_stage.company_audit_events(company_id,created_at DESC,id DESC);

CREATE INDEX idx_confirmed_joining_date ON jobmitra_v12_stage.jd_candidates(joined_on,job_id) WHERE selection_outcome='JOINED_CONFIRMED';

CREATE INDEX idx_events_candidate_time ON jobmitra_v12_stage.recruitment_events(candidate_id,created_at DESC,id DESC);

CREATE INDEX idx_events_job_time ON jobmitra_v12_stage.recruitment_events(job_id,created_at DESC);

CREATE INDEX idx_events_link_time ON jobmitra_v12_stage.recruitment_events(jd_candidate_id,created_at DESC);

CREATE INDEX idx_jd_company_status ON jobmitra_v12_stage.job_descriptions(company_id,status);

CREATE INDEX idx_jd_target ON jobmitra_v12_stage.job_descriptions(status,target_date);

CREATE INDEX idx_pool_by_candidate ON jobmitra_v12_stage.jd_candidates(candidate_id,added_at DESC);

CREATE INDEX idx_pool_by_job_stage ON jobmitra_v12_stage.jd_candidates(job_id,stage_code);

CREATE INDEX idx_round_job_position ON jobmitra_v12_stage.jd_interview_rounds(job_id,is_active,display_order);

CREATE INDEX idx_selection_date ON jobmitra_v12_stage.jd_candidates(selected_on,job_id);

CREATE INDEX ix_candidate_profile_versions ON jobmitra_v12_stage.candidate_profile_versions(candidate_id,id DESC);

CREATE INDEX ix_company_proposals_company ON jobmitra_v12_stage.company_proposals(company_id,created_at);

CREATE INDEX ix_proposal_events_parent ON jobmitra_v12_stage.company_proposal_status_events(proposal_id,created_at);

CREATE INDEX ix_proposal_signed_parent ON jobmitra_v12_stage.company_proposal_signed_documents(proposal_id,uploaded_at);

CREATE UNIQUE INDEX uq_candidate_legacy_postgres ON jobmitra_v12_stage.candidates(legacy_postgres_id);

CREATE UNIQUE INDEX uq_current_resume_kind ON jobmitra_v12_stage.candidate_resumes(candidate_id, resume_kind) WHERE is_current=1;

CREATE UNIQUE INDEX uq_resume_legacy_postgres ON jobmitra_v12_stage.candidate_resumes(legacy_source_table,legacy_postgres_id);

CREATE UNIQUE INDEX uq_v12_event_request ON jobmitra_v12_stage.recruitment_events((payload_json::json ->> 'idempotency_key')) WHERE (payload_json::json ->> 'idempotency_key') IS NOT NULL;

CREATE VIEW jobmitra_v12_stage.v_candidate_allocation_eligibility AS
SELECT c.id AS candidate_id,
 CASE
 WHEN EXISTS(SELECT 1 FROM jobmitra_v12_stage.jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='JOINED' AND l.eligibility_released_at_utc IS NULL) THEN 'PLACED_LOCKED'
 WHEN EXISTS(SELECT 1 FROM jobmitra_v12_stage.jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='SELECTED' AND (l.selection_outcome IS NULL OR l.selection_outcome='PENDING_JOINING')) THEN 'SELECTED_ON_HOLD'
 WHEN EXISTS(SELECT 1 FROM jobmitra_v12_stage.jd_candidates l WHERE l.candidate_id=c.id AND l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED','JOINED_CONFIRMED')) THEN 'AVAILABLE_AGAIN'
 ELSE 'AVAILABLE' END AS allocation_eligibility
FROM jobmitra_v12_stage.candidates c;

CREATE VIEW jobmitra_v12_stage.v_candidate_jd_history AS
SELECT l.id AS jd_candidate_id,l.candidate_id,c.full_name,j.id AS job_id,j.jd_code,j.title AS job_title,
l.stage_code,l.round_id,l.added_at,l.rejected_from_stage,l.rejected_round_name,l.rejected_round_index,l.rejected_at,
l.selection_outcome,l.selected_on,l.joined_on,l.joining_confirmed_at_utc,
CASE WHEN l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN l.selection_outcome ELSE l.stage_code END AS effective_status
FROM jobmitra_v12_stage.jd_candidates l JOIN jobmitra_v12_stage.candidates c ON c.id=l.candidate_id JOIN jobmitra_v12_stage.job_descriptions j ON j.id=l.job_id;

CREATE VIEW jobmitra_v12_stage.v_company_placement_register AS
SELECT l.id AS jd_candidate_id,j.company_id,j.id AS job_id,j.jd_code,j.title AS job_title,
 c.id AS candidate_id,c.full_name,l.stage_code,l.selection_outcome,l.selected_on,l.joined_on,
 l.joining_confirmed_at_utc,l.outcome_closed_on,l.outcome_reason,l.eligibility_released_at_utc,
 CASE WHEN l.selection_outcome IS NOT NULL THEN l.selection_outcome WHEN l.stage_code='JOINED' THEN 'JOINED_UNVERIFIED' ELSE 'SELECTED_UNVERIFIED' END AS effective_status,
 e.allocation_eligibility
FROM jobmitra_v12_stage.jd_candidates l JOIN jobmitra_v12_stage.job_descriptions j ON j.id=l.job_id JOIN jobmitra_v12_stage.candidates c ON c.id=l.candidate_id
JOIN jobmitra_v12_stage.v_candidate_allocation_eligibility e ON e.candidate_id=c.id
WHERE l.stage_code IN ('SELECTED','JOINED');

CREATE VIEW jobmitra_v12_stage.v_jd_dashboard AS
WITH joined AS (SELECT job_id,count(*) joined_count FROM jobmitra_v12_stage.jd_candidates WHERE selection_outcome='JOINED_CONFIRMED' AND joined_on IS NOT NULL AND joining_confirmed_at_utc IS NOT NULL GROUP BY job_id),
 amounts AS (SELECT j.id,j.jd_code,j.company_id,j.title,j.status,j.created_at,j.target_date,j.vacancies,COALESCE(x.joined_count,0) joined_count FROM jobmitra_v12_stage.job_descriptions j LEFT JOIN joined x ON x.job_id=j.id)
SELECT a.*,CASE WHEN status='CLOSED' THEN 'CLOSED' WHEN vacancies IS NOT NULL AND joined_count>=vacancies THEN 'FILLED' WHEN status<>'ACTIVE' OR target_date IS NULL THEN 'UNSET' WHEN target_date<((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date::text) THEN 'OVERDUE' WHEN target_date<=(((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date + 2)::text) THEN 'DUE' ELSE 'TRACK' END AS target_state,
(target_date::date - (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date) AS days_remaining FROM amounts a;

CREATE VIEW jobmitra_v12_stage.v_jd_stage_counts AS
SELECT job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END AS stage_code,
COALESCE(round_id,'') AS round_key,COUNT(*) AS candidate_count
FROM jobmitra_v12_stage.jd_candidates GROUP BY job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END,COALESCE(round_id,'');


CREATE TABLE jobmitra_v12_stage.migration_versions (
 version TEXT PRIMARY KEY,
 migration_sha256 TEXT NOT NULL,
 source_contract_sha256 TEXT NOT NULL,
 source_store_id UUID NOT NULL UNIQUE,
 sqlite_backup_sha256 TEXT NOT NULL,
 postgres_backup_sha256 TEXT NOT NULL,
 public_fingerprint_sha256 TEXT NOT NULL,
 applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE jobmitra_v12_stage.source_identity_map (
 source_store_id UUID NOT NULL,
 table_name TEXT NOT NULL,
 source_pk TEXT NOT NULL,
 legacy_source_table TEXT,
 legacy_postgres_id TEXT,
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 target_sha256 TEXT NOT NULL CHECK(length(target_sha256)=64),
 classification TEXT NOT NULL CHECK(classification IN ('IMPORTED_LEGACY','DEVELOPMENT_TEST')),
 classification_evidence TEXT NOT NULL,
 PRIMARY KEY(source_store_id,table_name,source_pk),
 FOREIGN KEY(source_store_id) REFERENCES jobmitra_v12_stage.migration_versions(source_store_id)
);
CREATE UNIQUE INDEX uq_stage_legacy_source_identity ON jobmitra_v12_stage.source_identity_map
 (source_store_id,legacy_source_table,legacy_postgres_id) WHERE legacy_postgres_id IS NOT NULL;
CREATE TABLE jobmitra_v12_stage.document_manifest (
 source_table TEXT NOT NULL,
 source_pk TEXT NOT NULL,
 manifest_json TEXT NOT NULL CHECK(manifest_json IS JSON),
 PRIMARY KEY(source_table,source_pk)
);
CREATE FUNCTION jobmitra_v12_stage.reject_snapshot_mutation() RETURNS trigger
 LANGUAGE plpgsql SET search_path = pg_catalog AS $$
 BEGIN
 RAISE EXCEPTION 'Immutable V12 staging snapshot: application writes are not enabled';
 END;
$$;
COMMENT ON SCHEMA jobmitra_v12_stage IS
 'Isolated immutable V12 migration snapshot. Contains development/test records. Not production-ready.';

