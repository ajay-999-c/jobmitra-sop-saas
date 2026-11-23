-- Empty isolated DEVELOPMENT schema. No source rows are imported.

-- TEXT dates/JSON preserve the exact SQLite representation.

-- Salary NUMERIC has no typmod: no implicit rounding or scale truncation.

CREATE SCHEMA __V12_SCHEMA__;

REVOKE ALL ON SCHEMA __V12_SCHEMA__ FROM PUBLIC;

CREATE TABLE __V12_SCHEMA__.candidates (
    id                      BIGINT PRIMARY KEY,
    candidate_code          TEXT COLLATE "C" UNIQUE,
    full_name               TEXT COLLATE "C" NOT NULL CHECK(length(trim(full_name))>0),
    phone                   TEXT COLLATE "C",
    phone_normalized        TEXT COLLATE "C",
    email                   TEXT COLLATE "C",
    email_normalized        TEXT COLLATE "C",
    links_json              TEXT COLLATE "C" NOT NULL DEFAULT '{}' CHECK((links_json IS JSON)),
    job_title               TEXT COLLATE "C",
    current_employer        TEXT COLLATE "C",
    current_city            TEXT COLLATE "C",
    preferred_cities_json   TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((preferred_cities_json IS JSON)),
    experience_years        DOUBLE PRECISION CHECK(experience_years IS NULL OR experience_years >= 0),
    qualification           TEXT COLLATE "C",
    primary_domain          TEXT COLLATE "C",
    skills_json             TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((skills_json IS JSON)),
    professional_summary    TEXT COLLATE "C",
    search_text             TEXT COLLATE "C",
    current_salary_inr      NUMERIC CHECK(current_salary_inr IS NULL OR current_salary_inr >= 0),
    current_salary_period   TEXT COLLATE "C" CHECK(current_salary_period IS NULL OR current_salary_period IN ('MONTHLY','ANNUAL')),
    current_salary_basis    TEXT COLLATE "C" CHECK(current_salary_basis IS NULL OR current_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    expected_salary_inr     NUMERIC CHECK(expected_salary_inr IS NULL OR expected_salary_inr >= 0),
    expected_salary_period  TEXT COLLATE "C" CHECK(expected_salary_period IS NULL OR expected_salary_period IN ('MONTHLY','ANNUAL')),
    expected_salary_basis   TEXT COLLATE "C" CHECK(expected_salary_basis IS NULL OR expected_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    notice_days             BIGINT CHECK(notice_days IS NULL OR notice_days >= 0),
    availability            TEXT COLLATE "C" NOT NULL DEFAULT 'TO_CONFIRM' CHECK(availability IN ('AVAILABLE','TO_CONFIRM','UNAVAILABLE')),
    source                  TEXT COLLATE "C" NOT NULL DEFAULT 'MANUAL' CHECK(source IN ('MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER','EMAIL')),
    is_active               BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at              TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    updated_at              TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
, legacy_postgres_id TEXT COLLATE "C", source_json TEXT COLLATE "C" CHECK(source_json IS NULL OR (source_json IS JSON)), source_fingerprint TEXT COLLATE "C", imported_at TEXT COLLATE "C");

CREATE TABLE __V12_SCHEMA__.companies (
    id                          TEXT COLLATE "C" PRIMARY KEY CHECK(length(id)=36),
    legacy_postgres_id          TEXT COLLATE "C" UNIQUE,
    company_name                TEXT COLLATE "C" NOT NULL CHECK(length(trim(company_name))>0),
    company_name_key            TEXT COLLATE "C" NOT NULL UNIQUE CHECK(length(trim(company_name_key))>0),
    general_phone_numbers_json  TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((general_phone_numbers_json IS JSON) AND json_typeof(general_phone_numbers_json::json)='array'),
    contacts_json               TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((contacts_json IS JSON) AND json_typeof(contacts_json::json)='array'),
    address_line                TEXT COLLATE "C",
    city                        TEXT COLLATE "C",
    state                       TEXT COLLATE "C",
    postal_code                 TEXT COLLATE "C",
    source_register_ids_json    TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((source_register_ids_json IS JSON) AND json_typeof(source_register_ids_json::json)='array'),
    is_active                   BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at                  TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    updated_at                  TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    source_json                 TEXT COLLATE "C" CHECK(source_json IS NULL OR (source_json IS JSON)),
    source_fingerprint          TEXT COLLATE "C",
    imported_at                 TEXT COLLATE "C"
, audit_request_key TEXT COLLATE "C", audit_request_fingerprint TEXT COLLATE "C", audit_actor_name TEXT COLLATE "C", audit_actor_role TEXT COLLATE "C");

CREATE TABLE __V12_SCHEMA__.job_descriptions (
    id                  BIGINT PRIMARY KEY,
    jd_code             TEXT COLLATE "C" NOT NULL UNIQUE,
    company_id          TEXT COLLATE "C" NOT NULL CHECK(length(company_id)=36 AND substr(company_id,9,1)='-' AND substr(company_id,14,1)='-' AND substr(company_id,19,1)='-' AND substr(company_id,24,1)='-'),
    title               TEXT COLLATE "C" NOT NULL CHECK(length(trim(title)) > 0),
    company_contact     TEXT COLLATE "C",
    location            TEXT COLLATE "C",
    work_mode           TEXT COLLATE "C" CHECK(work_mode IS NULL OR work_mode IN ('ONSITE','HYBRID','REMOTE')),
    vacancies           BIGINT CHECK(vacancies IS NULL OR vacancies > 0),
    status              TEXT COLLATE "C" NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','ACTIVE','ON_HOLD','CLOSED')),
    created_at          TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    target_date         TEXT COLLATE "C",
    is_legacy_import    BIGINT NOT NULL DEFAULT 0 CHECK(is_legacy_import IN (0,1)),
    skills_json         TEXT COLLATE "C" NOT NULL DEFAULT '[]' CHECK((skills_json IS JSON)),
    experience_min      DOUBLE PRECISION CHECK(experience_min IS NULL OR experience_min >= 0),
    experience_max      DOUBLE PRECISION CHECK(experience_max IS NULL OR experience_max >= 0),
    qualification       TEXT COLLATE "C",
    salary_min_inr      NUMERIC CHECK(salary_min_inr IS NULL OR salary_min_inr >= 0),
    salary_max_inr      NUMERIC CHECK(salary_max_inr IS NULL OR salary_max_inr >= 0),
    salary_period       TEXT COLLATE "C" CHECK(salary_period IS NULL OR salary_period IN ('MONTHLY','ANNUAL')),
    salary_basis        TEXT COLLATE "C" NOT NULL DEFAULT 'UNKNOWN' CHECK(salary_basis IN ('UNKNOWN','CTC','GROSS','IN_HAND')),
    requirement_notes   TEXT COLLATE "C",
    full_jd             TEXT COLLATE "C",
    workflow_mode       TEXT COLLATE "C" NOT NULL DEFAULT 'UNKNOWN' CHECK(workflow_mode IN ('UNKNOWN','DIRECT','CONFIGURED')),
    workflow_version    BIGINT NOT NULL DEFAULT 0 CHECK(workflow_version >= 0),
    owner_name          TEXT COLLATE "C",
    updated_at          TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')), company_contact_id TEXT COLLATE "C", company_contact_name_snapshot TEXT COLLATE "C", company_contact_email_snapshot TEXT COLLATE "C", contact_request_key TEXT COLLATE "C", contact_request_fingerprint TEXT COLLATE "C", contact_actor_name TEXT COLLATE "C", contact_actor_role TEXT COLLATE "C",
    CHECK(target_date IS NOT NULL OR is_legacy_import = 1),
    CHECK(target_date IS NULL OR target_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
    CHECK(target_date IS NULL OR is_legacy_import=1 OR target_date >= ((created_at::timestamptz AT TIME ZONE 'Asia/Kolkata')::date)::text),
    CHECK(experience_min IS NULL OR experience_max IS NULL OR experience_max >= experience_min),
    CHECK(salary_min_inr IS NULL OR salary_max_inr IS NULL OR salary_max_inr >= salary_min_inr)
);

CREATE TABLE __V12_SCHEMA__.jd_interview_rounds (
    id              TEXT COLLATE "C" PRIMARY KEY,
    job_id          BIGINT NOT NULL REFERENCES __V12_SCHEMA__.job_descriptions(id) ON DELETE RESTRICT,
    round_name      TEXT COLLATE "C" NOT NULL CHECK(length(trim(round_name)) >= 3),
    display_order   BIGINT NOT NULL CHECK(display_order >= 1),
    mode            TEXT COLLATE "C" NOT NULL DEFAULT 'FLEXIBLE' CHECK(mode IN ('FLEXIBLE','FACE_TO_FACE','VIDEO','PHONE')),
    is_active       BIGINT NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    retired_at      TEXT COLLATE "C",
    created_at      TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    UNIQUE(job_id, id)
);

CREATE TABLE __V12_SCHEMA__.jd_candidates (
    id                      BIGINT PRIMARY KEY,
    job_id                  BIGINT NOT NULL REFERENCES __V12_SCHEMA__.job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            BIGINT NOT NULL REFERENCES __V12_SCHEMA__.candidates(id) ON DELETE RESTRICT,
    stage_code              TEXT COLLATE "C" NOT NULL DEFAULT 'POOL' CHECK(stage_code IN (
                              'POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND','SELECTED','JOINED','NOT_SELECTED')),
    round_id                TEXT COLLATE "C",
    stage_note              TEXT COLLATE "C",
    rejected_from_stage     TEXT COLLATE "C",
    rejected_round_name     TEXT COLLATE "C",
    rejected_round_index    BIGINT,
    rejected_at             TEXT COLLATE "C",
    added_by                TEXT COLLATE "C",
    changed_by              TEXT COLLATE "C",
    added_at                TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    stage_updated_at        TEXT COLLATE "C", selection_outcome TEXT COLLATE "C" CHECK(selection_outcome IS NULL OR selection_outcome IN ('PENDING_JOINING','JOINED_CONFIRMED','NOT_JOINED','SELECTION_CANCELLED')), selected_on TEXT COLLATE "C", selected_at_utc TEXT COLLATE "C", joined_on TEXT COLLATE "C", joining_confirmed_at_utc TEXT COLLATE "C", outcome_closed_on TEXT COLLATE "C", outcome_reason TEXT COLLATE "C", eligibility_released_at_utc TEXT COLLATE "C", eligibility_release_reason TEXT COLLATE "C", confirmation_evidence TEXT COLLATE "C", action_actor_name TEXT COLLATE "C", action_actor_role TEXT COLLATE "C", action_request_key TEXT COLLATE "C", action_request_fingerprint TEXT COLLATE "C",
    UNIQUE(job_id, candidate_id),
    CHECK((stage_code = 'ROUND' AND round_id IS NOT NULL) OR (stage_code <> 'ROUND' AND round_id IS NULL)),
    FOREIGN KEY(job_id, round_id) REFERENCES __V12_SCHEMA__.jd_interview_rounds(job_id,id) ON DELETE RESTRICT
);

CREATE TABLE __V12_SCHEMA__.candidate_resumes (
    id                  BIGINT PRIMARY KEY,
    candidate_id        BIGINT NOT NULL REFERENCES __V12_SCHEMA__.candidates(id) ON DELETE RESTRICT,
    source_type         TEXT COLLATE "C" NOT NULL CHECK(source_type IN ('UPLOADED','FOUNDIT_PASTE','GENERATED')),
    resume_kind         TEXT COLLATE "C" NOT NULL CHECK(resume_kind IN ('ORIGINAL','JOBMITRA_STANDARD','PARSED_TEXT')),
    original_filename   TEXT COLLATE "C",
    storage_path        TEXT COLLATE "C",
    raw_text            TEXT COLLATE "C",
    parsed_json         TEXT COLLATE "C" CHECK(parsed_json IS NULL OR (parsed_json IS JSON)),
    is_current          BIGINT NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    created_at          TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')), legacy_source_table TEXT COLLATE "C", legacy_postgres_id TEXT COLLATE "C", source_json TEXT COLLATE "C" CHECK(source_json IS NULL OR (source_json IS JSON)), imported_at TEXT COLLATE "C",
    CHECK(storage_path IS NOT NULL OR raw_text IS NOT NULL OR parsed_json IS NOT NULL)
);

CREATE TABLE __V12_SCHEMA__.candidate_activities (
    id              BIGINT PRIMARY KEY,
    candidate_id    BIGINT NOT NULL REFERENCES __V12_SCHEMA__.candidates(id) ON DELETE RESTRICT,
    job_id          BIGINT REFERENCES __V12_SCHEMA__.job_descriptions(id) ON DELETE RESTRICT,
    activity_type   TEXT COLLATE "C" NOT NULL CHECK(activity_type IN ('FOLLOW_UP','OFFICE_VISIT','JOB_SEARCH_REQUEST','CALL','INTERVIEW','CANDIDATE_SUBMISSION','OTHER')),
    status          TEXT COLLATE "C" NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DONE','CANCELLED')),
    due_at          TEXT COLLATE "C",
    occurred_at     TEXT COLLATE "C",
    notes           TEXT COLLATE "C",
    details_json    TEXT COLLATE "C" NOT NULL DEFAULT '{}' CHECK((details_json IS JSON)),
    assigned_to     TEXT COLLATE "C",
    created_at      TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'))
);

CREATE TABLE __V12_SCHEMA__.recruitment_events (
    id                      BIGINT PRIMARY KEY,
    job_id                  BIGINT REFERENCES __V12_SCHEMA__.job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            BIGINT REFERENCES __V12_SCHEMA__.candidates(id) ON DELETE RESTRICT,
    jd_candidate_id         BIGINT REFERENCES __V12_SCHEMA__.jd_candidates(id) ON DELETE RESTRICT,
    event_type              TEXT COLLATE "C" NOT NULL,
    from_stage              TEXT COLLATE "C",
    to_stage                TEXT COLLATE "C",
    from_label_snapshot     TEXT COLLATE "C",
    to_label_snapshot       TEXT COLLATE "C",
    feedback                TEXT COLLATE "C",
    feedback_source         TEXT COLLATE "C" CHECK(feedback_source IS NULL OR feedback_source IN ('COMPANY','JOBMITRA','CANDIDATE','NOT_SPECIFIED')),
    workflow_version        BIGINT,
    payload_json            TEXT COLLATE "C" NOT NULL DEFAULT '{}' CHECK((payload_json IS JSON)),
    before_json             TEXT COLLATE "C" CHECK(before_json IS NULL OR (before_json IS JSON)),
    after_json              TEXT COLLATE "C" CHECK(after_json IS NULL OR (after_json IS JSON)),
    actor_name              TEXT COLLATE "C",
    created_at              TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    CHECK(job_id IS NOT NULL OR candidate_id IS NOT NULL)
);

CREATE TABLE __V12_SCHEMA__.company_audit_events (
    id BIGINT PRIMARY KEY,
    company_id TEXT COLLATE "C" NOT NULL REFERENCES __V12_SCHEMA__.companies(id) ON DELETE RESTRICT,
    action TEXT COLLATE "C" NOT NULL,
    before_json TEXT COLLATE "C" CHECK(before_json IS NULL OR (before_json IS JSON)),
    after_json TEXT COLLATE "C" CHECK(after_json IS NULL OR (after_json IS JSON)),
    actor_staff_id TEXT COLLATE "C",
    actor_name_snapshot TEXT COLLATE "C",
    actor_verification_status TEXT COLLATE "C",
    source_system TEXT COLLATE "C",
    source_event_id TEXT COLLATE "C",
    request_fingerprint TEXT COLLATE "C",
    created_at TEXT COLLATE "C" NOT NULL DEFAULT (to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')),
    UNIQUE(source_system,source_event_id)
);

CREATE TABLE __V12_SCHEMA__.candidate_profile_versions (
 id BIGINT PRIMARY KEY,
 candidate_id BIGINT NOT NULL REFERENCES __V12_SCHEMA__.candidates(id) ON DELETE RESTRICT,
 profile_json TEXT COLLATE "C" NOT NULL CHECK((profile_json IS JSON)),
 before_json TEXT COLLATE "C" NOT NULL CHECK((before_json IS JSON)),
 after_json TEXT COLLATE "C" NOT NULL CHECK((after_json IS JSON)),
 provenance_json TEXT COLLATE "C" NOT NULL CHECK((provenance_json IS JSON)),
 actor_name TEXT COLLATE "C" NOT NULL,
 actor_role TEXT COLLATE "C" NOT NULL,
 created_at TEXT COLLATE "C" NOT NULL,
 request_key TEXT COLLATE "C" NOT NULL UNIQUE,
 request_hash TEXT COLLATE "C" NOT NULL
);

CREATE TABLE __V12_SCHEMA__.company_proposals (
 id TEXT COLLATE "C" PRIMARY KEY,
 company_id TEXT COLLATE "C" NOT NULL REFERENCES __V12_SCHEMA__.companies(id) ON DELETE RESTRICT,
 contact_id TEXT COLLATE "C",
 reference TEXT COLLATE "C" NOT NULL UNIQUE,
 issue_date TEXT COLLATE "C" NOT NULL,
 fee_basis_points BIGINT NOT NULL CHECK(fee_basis_points IN (600,833)),
 snapshot_json TEXT COLLATE "C" NOT NULL CHECK((snapshot_json IS JSON)),
 pdf_key TEXT COLLATE "C" NOT NULL UNIQUE,
 pdf_sha256 TEXT COLLATE "C" NOT NULL CHECK(length(pdf_sha256)=64),
 pdf_size BIGINT NOT NULL CHECK(pdf_size>0),
 created_at TEXT COLLATE "C" NOT NULL,
 prepared_by TEXT COLLATE "C" NOT NULL,
 actor_role TEXT COLLATE "C" NOT NULL,
 request_key TEXT COLLATE "C" NOT NULL UNIQUE,
 request_hash TEXT COLLATE "C" NOT NULL
);

CREATE TABLE __V12_SCHEMA__.company_proposal_signed_documents (
 id TEXT COLLATE "C" PRIMARY KEY,
 proposal_id TEXT COLLATE "C" NOT NULL REFERENCES __V12_SCHEMA__.company_proposals(id) ON DELETE RESTRICT,
 storage_key TEXT COLLATE "C" NOT NULL UNIQUE,
 sha256 TEXT COLLATE "C" NOT NULL CHECK(length(sha256)=64),
 size BIGINT NOT NULL CHECK(size>0),
 original_filename TEXT COLLATE "C" NOT NULL,
 uploaded_at TEXT COLLATE "C" NOT NULL,
 uploaded_by TEXT COLLATE "C" NOT NULL,
 actor_role TEXT COLLATE "C" NOT NULL,
 request_key TEXT COLLATE "C" NOT NULL UNIQUE,
 request_hash TEXT COLLATE "C" NOT NULL
);

CREATE TABLE __V12_SCHEMA__.company_proposal_status_events (
 id TEXT COLLATE "C" PRIMARY KEY,
 proposal_id TEXT COLLATE "C" NOT NULL REFERENCES __V12_SCHEMA__.company_proposals(id) ON DELETE RESTRICT,
 status TEXT COLLATE "C" NOT NULL CHECK(status IN ('SENT','ACCEPTED','DECLINED')),
 evidence TEXT COLLATE "C" NOT NULL,
 effective_date TEXT COLLATE "C" NOT NULL,
 authorized_signatory TEXT COLLATE "C",
 signed_document_id TEXT COLLATE "C" REFERENCES __V12_SCHEMA__.company_proposal_signed_documents(id) ON DELETE RESTRICT,
 created_at TEXT COLLATE "C" NOT NULL,
 recorded_by TEXT COLLATE "C" NOT NULL,
 actor_role TEXT COLLATE "C" NOT NULL,
 request_key TEXT COLLATE "C" NOT NULL UNIQUE,
 request_hash TEXT COLLATE "C" NOT NULL
);

ALTER TABLE __V12_SCHEMA__.job_descriptions ADD FOREIGN KEY(company_id) REFERENCES __V12_SCHEMA__.companies(id) ON DELETE RESTRICT;

ALTER TABLE __V12_SCHEMA__.jd_candidates ADD UNIQUE(id,job_id,candidate_id);

ALTER TABLE __V12_SCHEMA__.recruitment_events ADD FOREIGN KEY(jd_candidate_id,job_id,candidate_id) REFERENCES __V12_SCHEMA__.jd_candidates(id,job_id,candidate_id) ON DELETE RESTRICT;

ALTER TABLE __V12_SCHEMA__.company_proposal_signed_documents ADD UNIQUE(proposal_id,id);

ALTER TABLE __V12_SCHEMA__.company_proposal_status_events ADD FOREIGN KEY(proposal_id,signed_document_id) REFERENCES __V12_SCHEMA__.company_proposal_signed_documents(proposal_id,id) ON DELETE RESTRICT;

CREATE INDEX idx_activities_due ON __V12_SCHEMA__.candidate_activities(status,activity_type,due_at);

CREATE INDEX idx_ats_company_options ON __V12_SCHEMA__.companies(is_active,company_name_key,id);

CREATE INDEX idx_candidate_resumes_history ON __V12_SCHEMA__.candidate_resumes(candidate_id, created_at DESC);

CREATE INDEX idx_candidates_city ON __V12_SCHEMA__.candidates(current_city);

CREATE INDEX idx_candidates_email_normalized ON __V12_SCHEMA__.candidates(email_normalized);

CREATE INDEX idx_candidates_experience ON __V12_SCHEMA__.candidates(experience_years);

CREATE INDEX idx_candidates_name ON __V12_SCHEMA__.candidates(lower(full_name));

CREATE INDEX idx_candidates_notice ON __V12_SCHEMA__.candidates(notice_days);

CREATE INDEX idx_candidates_phone_normalized ON __V12_SCHEMA__.candidates(phone_normalized);

CREATE INDEX idx_candidates_salary ON __V12_SCHEMA__.candidates(expected_salary_basis, expected_salary_period, expected_salary_inr);

CREATE INDEX idx_candidates_updated ON __V12_SCHEMA__.candidates(updated_at DESC);

CREATE INDEX idx_company_audit_time ON __V12_SCHEMA__.company_audit_events(company_id,created_at DESC,id DESC);

CREATE INDEX idx_confirmed_joining_date ON __V12_SCHEMA__.jd_candidates(joined_on,job_id) WHERE selection_outcome='JOINED_CONFIRMED';

CREATE INDEX idx_events_candidate_time ON __V12_SCHEMA__.recruitment_events(candidate_id,created_at DESC,id DESC);

CREATE INDEX idx_events_job_time ON __V12_SCHEMA__.recruitment_events(job_id,created_at DESC);

CREATE INDEX idx_events_link_time ON __V12_SCHEMA__.recruitment_events(jd_candidate_id,created_at DESC);

CREATE INDEX idx_jd_company_status ON __V12_SCHEMA__.job_descriptions(company_id,status);

CREATE INDEX idx_jd_target ON __V12_SCHEMA__.job_descriptions(status,target_date);

CREATE INDEX idx_pool_by_candidate ON __V12_SCHEMA__.jd_candidates(candidate_id,added_at DESC);

CREATE INDEX idx_pool_by_job_stage ON __V12_SCHEMA__.jd_candidates(job_id,stage_code);

CREATE INDEX idx_round_job_position ON __V12_SCHEMA__.jd_interview_rounds(job_id,is_active,display_order);

CREATE INDEX idx_selection_date ON __V12_SCHEMA__.jd_candidates(selected_on,job_id);

CREATE INDEX ix_candidate_profile_versions ON __V12_SCHEMA__.candidate_profile_versions(candidate_id,id DESC);

CREATE INDEX ix_company_proposals_company ON __V12_SCHEMA__.company_proposals(company_id,created_at);

CREATE INDEX ix_proposal_events_parent ON __V12_SCHEMA__.company_proposal_status_events(proposal_id,created_at);

CREATE INDEX ix_proposal_signed_parent ON __V12_SCHEMA__.company_proposal_signed_documents(proposal_id,uploaded_at);

CREATE UNIQUE INDEX uq_candidate_legacy_postgres ON __V12_SCHEMA__.candidates(legacy_postgres_id);

CREATE UNIQUE INDEX uq_current_resume_kind ON __V12_SCHEMA__.candidate_resumes(candidate_id, resume_kind) WHERE is_current=1;

CREATE UNIQUE INDEX uq_resume_legacy_postgres ON __V12_SCHEMA__.candidate_resumes(legacy_source_table,legacy_postgres_id);

CREATE UNIQUE INDEX uq_v12_event_request ON __V12_SCHEMA__.recruitment_events((payload_json::json ->> 'idempotency_key')) WHERE (payload_json::json ->> 'idempotency_key') IS NOT NULL;

CREATE VIEW __V12_SCHEMA__.v_candidate_allocation_eligibility AS
SELECT c.id AS candidate_id,
 CASE
 WHEN EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='JOINED' AND l.eligibility_released_at_utc IS NULL) THEN 'PLACED_LOCKED'
 WHEN EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='SELECTED' AND (l.selection_outcome IS NULL OR l.selection_outcome='PENDING_JOINING')) THEN 'SELECTED_ON_HOLD'
 WHEN EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_candidates l WHERE l.candidate_id=c.id AND l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED','JOINED_CONFIRMED')) THEN 'AVAILABLE_AGAIN'
 ELSE 'AVAILABLE' END AS allocation_eligibility
FROM __V12_SCHEMA__.candidates c;

CREATE VIEW __V12_SCHEMA__.v_candidate_jd_history AS
SELECT l.id AS jd_candidate_id,l.candidate_id,c.full_name,j.id AS job_id,j.jd_code,j.title AS job_title,
l.stage_code,l.round_id,l.added_at,l.rejected_from_stage,l.rejected_round_name,l.rejected_round_index,l.rejected_at,
l.selection_outcome,l.selected_on,l.joined_on,l.joining_confirmed_at_utc,
CASE WHEN l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN l.selection_outcome ELSE l.stage_code END AS effective_status
FROM __V12_SCHEMA__.jd_candidates l JOIN __V12_SCHEMA__.candidates c ON c.id=l.candidate_id JOIN __V12_SCHEMA__.job_descriptions j ON j.id=l.job_id;

CREATE VIEW __V12_SCHEMA__.v_company_placement_register AS
SELECT l.id AS jd_candidate_id,j.company_id,j.id AS job_id,j.jd_code,j.title AS job_title,
 c.id AS candidate_id,c.full_name,l.stage_code,l.selection_outcome,l.selected_on,l.joined_on,
 l.joining_confirmed_at_utc,l.outcome_closed_on,l.outcome_reason,l.eligibility_released_at_utc,
 CASE WHEN l.selection_outcome IS NOT NULL THEN l.selection_outcome WHEN l.stage_code='JOINED' THEN 'JOINED_UNVERIFIED' ELSE 'SELECTED_UNVERIFIED' END AS effective_status,
 e.allocation_eligibility
FROM __V12_SCHEMA__.jd_candidates l JOIN __V12_SCHEMA__.job_descriptions j ON j.id=l.job_id JOIN __V12_SCHEMA__.candidates c ON c.id=l.candidate_id
JOIN __V12_SCHEMA__.v_candidate_allocation_eligibility e ON e.candidate_id=c.id
WHERE l.stage_code IN ('SELECTED','JOINED');

CREATE VIEW __V12_SCHEMA__.v_jd_dashboard AS
WITH joined AS (SELECT job_id,count(*) joined_count FROM __V12_SCHEMA__.jd_candidates WHERE selection_outcome='JOINED_CONFIRMED' AND joined_on IS NOT NULL AND joining_confirmed_at_utc IS NOT NULL GROUP BY job_id),
 amounts AS (SELECT j.id,j.jd_code,j.company_id,j.title,j.status,j.created_at,j.target_date,j.vacancies,COALESCE(x.joined_count,0) joined_count FROM __V12_SCHEMA__.job_descriptions j LEFT JOIN joined x ON x.job_id=j.id)
SELECT a.*,CASE WHEN status='CLOSED' THEN 'CLOSED' WHEN vacancies IS NOT NULL AND joined_count>=vacancies THEN 'FILLED' WHEN status<>'ACTIVE' OR target_date IS NULL THEN 'UNSET' WHEN target_date<((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date::text) THEN 'OVERDUE' WHEN target_date<=(((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date + 2)::text) THEN 'DUE' ELSE 'TRACK' END AS target_state,
(target_date::date - (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date) AS days_remaining FROM amounts a;

CREATE VIEW __V12_SCHEMA__.v_jd_stage_counts AS
SELECT job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END AS stage_code,
COALESCE(round_id,'') AS round_key,COUNT(*) AS candidate_count
FROM __V12_SCHEMA__.jd_candidates GROUP BY job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END,COALESCE(round_id,'');


ALTER TABLE __V12_SCHEMA__.candidates ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (START WITH 4294967296);
ALTER TABLE __V12_SCHEMA__.job_descriptions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.jd_candidates ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.candidate_resumes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.candidate_activities ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.recruitment_events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.company_audit_events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.candidate_profile_versions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY;
ALTER TABLE __V12_SCHEMA__.company_proposals ADD COLUMN _record_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE;
ALTER TABLE __V12_SCHEMA__.company_proposal_signed_documents ADD COLUMN _record_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE;
ALTER TABLE __V12_SCHEMA__.company_proposal_status_events ADD COLUMN _record_order BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE;

CREATE TABLE __V12_SCHEMA__.backend_versions (
 version INTEGER PRIMARY KEY,
 definition_sha256 TEXT COLLATE "C" NOT NULL,
 environment TEXT COLLATE "C" NOT NULL CHECK(environment='ISOLATED_DEVELOPMENT')
);
CREATE TABLE __V12_SCHEMA__.development_source_records (
 source_store_id UUID NOT NULL,
 table_name TEXT COLLATE "C" NOT NULL,
 source_pk TEXT COLLATE "C" NOT NULL,
 legacy_source_table TEXT COLLATE "C",
 legacy_postgres_id TEXT COLLATE "C",
 source_sha256 TEXT COLLATE "C" NOT NULL CHECK(length(source_sha256)=64),
 target_sha256 TEXT COLLATE "C" NOT NULL CHECK(length(target_sha256)=64),
 classification TEXT COLLATE "C" NOT NULL CHECK(classification IN ('IMPORTED_LEGACY','DEVELOPMENT_TEST')),
 classification_evidence TEXT COLLATE "C" NOT NULL,
 PRIMARY KEY(source_store_id,table_name,source_pk)
);
CREATE UNIQUE INDEX uq_development_global_candidate_lock ON __V12_SCHEMA__.jd_candidates(candidate_id)
 WHERE (stage_code='JOINED' AND eligibility_released_at_utc IS NULL)
 OR (stage_code='SELECTED' AND (selection_outcome IS NULL OR selection_outcome='PENDING_JOINING'));

CREATE FUNCTION __V12_SCHEMA__.json_extract(value TEXT, path TEXT) RETURNS TEXT
 LANGUAGE SQL IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
 SELECT value::json #>> string_to_array(substr(path,3),'.'); $$;
CREATE FUNCTION __V12_SCHEMA__.json_array_length(value TEXT) RETURNS INTEGER
 LANGUAGE SQL IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
 SELECT pg_catalog.json_array_length(value::json); $$;
CREATE FUNCTION __V12_SCHEMA__.json_each(input TEXT) RETURNS TABLE(key TEXT,value TEXT)
 LANGUAGE SQL IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
 SELECT (ordinality-1)::text, CASE WHEN json_typeof(item)='string' THEN item#>>'{}'
 ELSE item::text END FROM json_array_elements(input::json) WITH ORDINALITY AS x(item,ordinality); $$;
CREATE FUNCTION __V12_SCHEMA__.julianday(value TEXT) RETURNS DOUBLE PRECISION
 LANGUAGE SQL STABLE STRICT SET search_path=pg_catalog SET timezone='UTC' AS $$
 SELECT extract(epoch FROM value::timestamptz)::double precision/86400+2440587.5; $$;
CREATE FUNCTION __V12_SCHEMA__.strftime(format TEXT,value TEXT) RETURNS TEXT
 LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog SET timezone='UTC' AS $$
 BEGIN
 IF format<>'%Y-%m-%dT%H:%M:%fZ' OR value<>'now' THEN
 RAISE EXCEPTION 'Unsupported V12 timestamp expression'; END IF;
 RETURN to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"');
 END; $$;
CREATE FUNCTION __V12_SCHEMA__.valid_date(value TEXT) RETURNS BOOLEAN
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog AS $$
 BEGIN
 RETURN value ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' AND (value::date)::text=value;
 EXCEPTION WHEN data_exception THEN RETURN FALSE;
 END; $$;
