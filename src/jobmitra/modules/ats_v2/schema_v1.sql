-- Jobmitra ATS | SQLite V3.1: Candidate + JD + Complete Audit (NO login/employee)
-- Seven-table ATS store. Existing PostgreSQL Companies page supplies company selection.
-- Scope: candidates, resumes, JDs, company rounds, candidate-JD links and activity/history.
-- For a NEW, EMPTY development database only: DO NOT run on existing production schema.
-- Data model derived from Candidate Desk Search V1 and JD Workflow V5 prototypes.
PRAGMA foreign_keys=ON;

-- PostgreSQL owns Company Master. Services validate exact company UUIDs.

-- 2. Canonical Candidate Master (name/contact/parsed/search fields); one candidate across JDs.
CREATE TABLE IF NOT EXISTS candidates (
    id                      INTEGER PRIMARY KEY,
    candidate_code          TEXT UNIQUE,
    full_name               TEXT NOT NULL CHECK(length(trim(full_name))>0),
    phone                   TEXT,
    phone_normalized        TEXT,
    email                   TEXT,
    email_normalized        TEXT,
    links_json              TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(links_json)),
    job_title               TEXT,
    current_employer        TEXT,
    current_city            TEXT,
    preferred_cities_json   TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(preferred_cities_json)),
    experience_years        REAL CHECK(experience_years IS NULL OR experience_years >= 0),
    qualification           TEXT,
    primary_domain          TEXT,
    skills_json             TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(skills_json)),
    professional_summary    TEXT,
    search_text             TEXT,
    current_salary_inr      INTEGER CHECK(current_salary_inr IS NULL OR current_salary_inr >= 0),
    current_salary_period   TEXT CHECK(current_salary_period IS NULL OR current_salary_period IN ('MONTHLY','ANNUAL')),
    current_salary_basis    TEXT CHECK(current_salary_basis IS NULL OR current_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    expected_salary_inr     INTEGER CHECK(expected_salary_inr IS NULL OR expected_salary_inr >= 0),
    expected_salary_period  TEXT CHECK(expected_salary_period IS NULL OR expected_salary_period IN ('MONTHLY','ANNUAL')),
    expected_salary_basis   TEXT CHECK(expected_salary_basis IS NULL OR expected_salary_basis IN ('CTC','GROSS','IN_HAND','UNKNOWN')),
    notice_days             INTEGER CHECK(notice_days IS NULL OR notice_days >= 0),
    availability            TEXT NOT NULL DEFAULT 'TO_CONFIRM' CHECK(availability IN ('AVAILABLE','TO_CONFIRM','UNAVAILABLE')),
    source                  TEXT NOT NULL DEFAULT 'MANUAL' CHECK(source IN ('MANUAL','WALK_IN','FOUNDIT_PASTE','RESUME_UPLOAD','OTHER')),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- 3. Original resume, Jobmitra standardized resume and parse result (safe relative paths).
CREATE TABLE IF NOT EXISTS candidate_resumes (
    id                  INTEGER PRIMARY KEY,
    candidate_id        INTEGER NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    source_type         TEXT NOT NULL CHECK(source_type IN ('UPLOADED','FOUNDIT_PASTE','GENERATED')),
    resume_kind         TEXT NOT NULL CHECK(resume_kind IN ('ORIGINAL','JOBMITRA_STANDARD','PARSED_TEXT')),
    original_filename   TEXT,
    storage_path        TEXT,
    raw_text            TEXT,
    parsed_json         TEXT CHECK(parsed_json IS NULL OR json_valid(parsed_json)),
    is_current          INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0,1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(storage_path IS NOT NULL OR raw_text IS NOT NULL OR parsed_json IS NOT NULL)
);

-- 4. JD owned by company_id, mandatory target date for new JDs.
CREATE TABLE IF NOT EXISTS job_descriptions (
    id                  INTEGER PRIMARY KEY,
    jd_code             TEXT NOT NULL UNIQUE,
    company_id          TEXT NOT NULL CHECK(length(company_id)=36 AND substr(company_id,9,1)='-' AND substr(company_id,14,1)='-' AND substr(company_id,19,1)='-' AND substr(company_id,24,1)='-'),
    title               TEXT NOT NULL CHECK(length(trim(title)) > 0),
    company_contact     TEXT,
    location            TEXT,
    work_mode           TEXT CHECK(work_mode IS NULL OR work_mode IN ('ONSITE','HYBRID','REMOTE')),
    vacancies           INTEGER CHECK(vacancies IS NULL OR vacancies > 0),
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','ACTIVE','ON_HOLD','CLOSED')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    target_date         TEXT,
    is_legacy_import    INTEGER NOT NULL DEFAULT 0 CHECK(is_legacy_import IN (0,1)),
    skills_json         TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(skills_json)),
    experience_min      REAL CHECK(experience_min IS NULL OR experience_min >= 0),
    experience_max      REAL CHECK(experience_max IS NULL OR experience_max >= 0),
    qualification       TEXT,
    salary_min_inr      INTEGER CHECK(salary_min_inr IS NULL OR salary_min_inr >= 0),
    salary_max_inr      INTEGER CHECK(salary_max_inr IS NULL OR salary_max_inr >= 0),
    salary_period       TEXT CHECK(salary_period IS NULL OR salary_period IN ('MONTHLY','ANNUAL')),
    salary_basis        TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(salary_basis IN ('UNKNOWN','CTC','GROSS','IN_HAND')),
    requirement_notes   TEXT,
    full_jd             TEXT,
    workflow_mode       TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(workflow_mode IN ('UNKNOWN','DIRECT','CONFIGURED')),
    workflow_version    INTEGER NOT NULL DEFAULT 0 CHECK(workflow_version >= 0),
    owner_name          TEXT,
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(target_date IS NOT NULL OR is_legacy_import = 1),
    CHECK(target_date IS NULL OR target_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    CHECK(target_date IS NULL OR is_legacy_import=1 OR target_date >= date(created_at, '+330 minutes')),
    CHECK(experience_min IS NULL OR experience_max IS NULL OR experience_max >= experience_min),
    CHECK(salary_min_inr IS NULL OR salary_max_inr IS NULL OR salary_max_inr >= salary_min_inr)
);

-- 5. JD-specific COMPANY rounds. Four fixed Jobmitra stages live in application logic.
CREATE TABLE IF NOT EXISTS jd_interview_rounds (
    id              TEXT PRIMARY KEY,           -- Stable UUID / stage key, never derive from position
    job_id          INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE RESTRICT,
    round_name      TEXT NOT NULL CHECK(length(trim(round_name)) >= 3),
    display_order   INTEGER NOT NULL CHECK(display_order >= 1),
    mode            TEXT NOT NULL DEFAULT 'FLEXIBLE' CHECK(mode IN ('FLEXIBLE','FACE_TO_FACE','VIDEO','PHONE')),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    retired_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(job_id, id)
);

-- 6. Candidate-JD join, unique on pair, each new link starts at POOL.
CREATE TABLE IF NOT EXISTS jd_candidates (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER NOT NULL REFERENCES job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            INTEGER NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    stage_code              TEXT NOT NULL DEFAULT 'POOL' CHECK(stage_code IN (
                              'POOL','CONTACT','SCREENING','COMPANY_SUBMISSION','ROUND','SELECTED','JOINED','NOT_SELECTED')),
    round_id                TEXT,
    stage_note              TEXT,
    rejected_from_stage     TEXT,
    rejected_round_name     TEXT,
    rejected_round_index    INTEGER,
    rejected_at             TEXT,
    added_by                TEXT,
    changed_by              TEXT,
    added_at                TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    stage_updated_at        TEXT,
    UNIQUE(job_id, candidate_id),
    CHECK((stage_code = 'ROUND' AND round_id IS NOT NULL) OR (stage_code <> 'ROUND' AND round_id IS NULL)),
    FOREIGN KEY(job_id, round_id) REFERENCES jd_interview_rounds(job_id,id) ON DELETE RESTRICT
);

-- 7. Unified append-only audit / journey log: JD-only, candidate-only or candidate-in-JD.
-- Historical V3 actor_name is kept as an optional compatibility field; no login/user table.
CREATE TABLE IF NOT EXISTS recruitment_events (
    id                      INTEGER PRIMARY KEY,
    job_id                  INTEGER REFERENCES job_descriptions(id) ON DELETE RESTRICT,
    candidate_id            INTEGER REFERENCES candidates(id) ON DELETE RESTRICT,
    jd_candidate_id         INTEGER REFERENCES jd_candidates(id) ON DELETE RESTRICT,
    event_type              TEXT NOT NULL,
    from_stage              TEXT,
    to_stage                TEXT,
    from_label_snapshot     TEXT,
    to_label_snapshot       TEXT,
    feedback                TEXT,
    feedback_source         TEXT CHECK(feedback_source IS NULL OR feedback_source IN ('COMPANY','JOBMITRA','CANDIDATE','NOT_SPECIFIED')),
    workflow_version        INTEGER,
    payload_json            TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    before_json             TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
    after_json              TEXT CHECK(after_json IS NULL OR json_valid(after_json)),
    actor_name              TEXT,  -- legacy V3 compatibility only; no actor tracking in V3.1
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK(job_id IS NOT NULL OR candidate_id IS NOT NULL)
);

-- 8. Candidate follow-ups, office visits and job-search requests.
CREATE TABLE IF NOT EXISTS candidate_activities (
    id              INTEGER PRIMARY KEY,
    candidate_id    INTEGER NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    job_id          INTEGER REFERENCES job_descriptions(id) ON DELETE RESTRICT,
    activity_type   TEXT NOT NULL CHECK(activity_type IN ('FOLLOW_UP','OFFICE_VISIT','JOB_SEARCH_REQUEST','CALL','INTERVIEW','CANDIDATE_SUBMISSION','OTHER')),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DONE','CANCELLED')),
    due_at          TEXT,
    occurred_at     TEXT,
    notes           TEXT,
    details_json    TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)),
    assigned_to     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Search and join indexes: no extra tables, FTS5 or shadow tables.
CREATE INDEX IF NOT EXISTS idx_candidates_phone_normalized ON candidates(phone_normalized);
CREATE INDEX IF NOT EXISTS idx_candidates_email_normalized ON candidates(email_normalized);
CREATE INDEX IF NOT EXISTS idx_candidates_experience ON candidates(experience_years);
CREATE INDEX IF NOT EXISTS idx_candidates_salary ON candidates(expected_salary_basis, expected_salary_period, expected_salary_inr);
CREATE INDEX IF NOT EXISTS idx_candidates_notice ON candidates(notice_days);
CREATE INDEX IF NOT EXISTS idx_candidates_name ON candidates(full_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_candidates_city ON candidates(current_city);
CREATE INDEX IF NOT EXISTS idx_candidates_updated ON candidates(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidate_resumes_history ON candidate_resumes(candidate_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_current_resume_kind ON candidate_resumes(candidate_id, resume_kind) WHERE is_current=1;
CREATE INDEX IF NOT EXISTS idx_jd_company_status ON job_descriptions(company_id,status);
CREATE INDEX IF NOT EXISTS idx_jd_target ON job_descriptions(status,target_date);
CREATE INDEX IF NOT EXISTS idx_round_job_position ON jd_interview_rounds(job_id,is_active,display_order);
CREATE INDEX IF NOT EXISTS idx_pool_by_job_stage ON jd_candidates(job_id,stage_code);
CREATE INDEX IF NOT EXISTS idx_pool_by_candidate ON jd_candidates(candidate_id,added_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_job_time ON recruitment_events(job_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_link_time ON recruitment_events(jd_candidate_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activities_due ON candidate_activities(status,activity_type,due_at);


-- Shared V3.1 audit patch, used by BOTH fresh initializer and V3 -> V3.1 copy migration.
-- Zero new physical tables. No login, employee, proposal or user accounts.
CREATE INDEX IF NOT EXISTS idx_events_job_time ON recruitment_events(job_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_events_link_time ON recruitment_events(jd_candidate_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_events_candidate_time ON recruitment_events(candidate_id,created_at DESC,id DESC);

-- Event log is immutable. Scope consistency prevents cross-candidate/JD misattribution.
CREATE TRIGGER IF NOT EXISTS trg_event_scope_valid BEFORE INSERT ON recruitment_events
BEGIN
    SELECT CASE WHEN NEW.job_id IS NULL AND NEW.candidate_id IS NULL
        THEN RAISE(ABORT,'Audit event requires job_id or candidate_id') END;
    SELECT CASE WHEN NEW.jd_candidate_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM jd_candidates jc WHERE jc.id=NEW.jd_candidate_id
            AND jc.job_id=NEW.job_id
            AND (NEW.candidate_id IS NULL OR jc.candidate_id=NEW.candidate_id)
    ) THEN RAISE(ABORT,'JD candidate event must match linked job and candidate') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_events_block_update BEFORE UPDATE ON recruitment_events
BEGIN SELECT RAISE(ABORT,'Recruitment events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_events_block_delete BEFORE DELETE ON recruitment_events
BEGIN SELECT RAISE(ABORT,'Recruitment events cannot be deleted'); END;

-- The old Candidate Desk registration is unchanged; creation and field edits are captured.
CREATE TRIGGER IF NOT EXISTS trg_candidate_identity_immutable
BEFORE UPDATE OF id,created_at ON candidates
WHEN OLD.id IS NOT NEW.id OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT,'Candidate identity and creation time are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_candidate_created AFTER INSERT ON candidates
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,after_json,payload_json)
    VALUES(NEW.id,'CANDIDATE_CREATED',
        json_object('candidate_code', NEW.candidate_code, 'full_name', NEW.full_name, 'phone', NEW.phone, 'email', NEW.email, 'links_json', json(NEW.links_json), 'job_title', NEW.job_title, 'current_employer', NEW.current_employer, 'current_city', NEW.current_city, 'preferred_cities_json', json(NEW.preferred_cities_json), 'experience_years', NEW.experience_years, 'qualification', NEW.qualification, 'primary_domain', NEW.primary_domain, 'skills_json', json(NEW.skills_json), 'professional_summary', NEW.professional_summary, 'current_salary_inr', NEW.current_salary_inr, 'current_salary_period', NEW.current_salary_period, 'current_salary_basis', NEW.current_salary_basis, 'expected_salary_inr', NEW.expected_salary_inr, 'expected_salary_period', NEW.expected_salary_period, 'expected_salary_basis', NEW.expected_salary_basis, 'notice_days', NEW.notice_days, 'availability', NEW.availability, 'source', NEW.source, 'is_active', NEW.is_active),
        json_object('entity','candidate'));
END;

CREATE TRIGGER IF NOT EXISTS trg_candidate_updated AFTER UPDATE ON candidates
WHEN OLD.candidate_code IS NOT NEW.candidate_code OR
    OLD.full_name IS NOT NEW.full_name OR
    OLD.phone IS NOT NEW.phone OR
    OLD.email IS NOT NEW.email OR
    OLD.links_json IS NOT NEW.links_json OR
    OLD.job_title IS NOT NEW.job_title OR
    OLD.current_employer IS NOT NEW.current_employer OR
    OLD.current_city IS NOT NEW.current_city OR
    OLD.preferred_cities_json IS NOT NEW.preferred_cities_json OR
    OLD.experience_years IS NOT NEW.experience_years OR
    OLD.qualification IS NOT NEW.qualification OR
    OLD.primary_domain IS NOT NEW.primary_domain OR
    OLD.skills_json IS NOT NEW.skills_json OR
    OLD.professional_summary IS NOT NEW.professional_summary OR
    OLD.current_salary_inr IS NOT NEW.current_salary_inr OR
    OLD.current_salary_period IS NOT NEW.current_salary_period OR
    OLD.current_salary_basis IS NOT NEW.current_salary_basis OR
    OLD.expected_salary_inr IS NOT NEW.expected_salary_inr OR
    OLD.expected_salary_period IS NOT NEW.expected_salary_period OR
    OLD.expected_salary_basis IS NOT NEW.expected_salary_basis OR
    OLD.notice_days IS NOT NEW.notice_days OR
    OLD.availability IS NOT NEW.availability OR
    OLD.source IS NOT NEW.source OR
    OLD.is_active IS NOT NEW.is_active
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,before_json,after_json,payload_json)
    VALUES(NEW.id,'CANDIDATE_UPDATED',
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'candidate_code' AS field_name, json_quote(OLD.candidate_code) AS value_json WHERE OLD.candidate_code IS NOT NEW.candidate_code
        UNION ALL
        SELECT 'full_name' AS field_name, json_quote(OLD.full_name) AS value_json WHERE OLD.full_name IS NOT NEW.full_name
        UNION ALL
        SELECT 'phone' AS field_name, json_quote(OLD.phone) AS value_json WHERE OLD.phone IS NOT NEW.phone
        UNION ALL
        SELECT 'email' AS field_name, json_quote(OLD.email) AS value_json WHERE OLD.email IS NOT NEW.email
        UNION ALL
        SELECT 'links_json' AS field_name, OLD.links_json AS value_json WHERE OLD.links_json IS NOT NEW.links_json
        UNION ALL
        SELECT 'job_title' AS field_name, json_quote(OLD.job_title) AS value_json WHERE OLD.job_title IS NOT NEW.job_title
        UNION ALL
        SELECT 'current_employer' AS field_name, json_quote(OLD.current_employer) AS value_json WHERE OLD.current_employer IS NOT NEW.current_employer
        UNION ALL
        SELECT 'current_city' AS field_name, json_quote(OLD.current_city) AS value_json WHERE OLD.current_city IS NOT NEW.current_city
        UNION ALL
        SELECT 'preferred_cities_json' AS field_name, OLD.preferred_cities_json AS value_json WHERE OLD.preferred_cities_json IS NOT NEW.preferred_cities_json
        UNION ALL
        SELECT 'experience_years' AS field_name, json_quote(OLD.experience_years) AS value_json WHERE OLD.experience_years IS NOT NEW.experience_years
        UNION ALL
        SELECT 'qualification' AS field_name, json_quote(OLD.qualification) AS value_json WHERE OLD.qualification IS NOT NEW.qualification
        UNION ALL
        SELECT 'primary_domain' AS field_name, json_quote(OLD.primary_domain) AS value_json WHERE OLD.primary_domain IS NOT NEW.primary_domain
        UNION ALL
        SELECT 'skills_json' AS field_name, OLD.skills_json AS value_json WHERE OLD.skills_json IS NOT NEW.skills_json
        UNION ALL
        SELECT 'professional_summary' AS field_name, json_quote(OLD.professional_summary) AS value_json WHERE OLD.professional_summary IS NOT NEW.professional_summary
        UNION ALL
        SELECT 'current_salary_inr' AS field_name, json_quote(OLD.current_salary_inr) AS value_json WHERE OLD.current_salary_inr IS NOT NEW.current_salary_inr
        UNION ALL
        SELECT 'current_salary_period' AS field_name, json_quote(OLD.current_salary_period) AS value_json WHERE OLD.current_salary_period IS NOT NEW.current_salary_period
        UNION ALL
        SELECT 'current_salary_basis' AS field_name, json_quote(OLD.current_salary_basis) AS value_json WHERE OLD.current_salary_basis IS NOT NEW.current_salary_basis
        UNION ALL
        SELECT 'expected_salary_inr' AS field_name, json_quote(OLD.expected_salary_inr) AS value_json WHERE OLD.expected_salary_inr IS NOT NEW.expected_salary_inr
        UNION ALL
        SELECT 'expected_salary_period' AS field_name, json_quote(OLD.expected_salary_period) AS value_json WHERE OLD.expected_salary_period IS NOT NEW.expected_salary_period
        UNION ALL
        SELECT 'expected_salary_basis' AS field_name, json_quote(OLD.expected_salary_basis) AS value_json WHERE OLD.expected_salary_basis IS NOT NEW.expected_salary_basis
        UNION ALL
        SELECT 'notice_days' AS field_name, json_quote(OLD.notice_days) AS value_json WHERE OLD.notice_days IS NOT NEW.notice_days
        UNION ALL
        SELECT 'availability' AS field_name, json_quote(OLD.availability) AS value_json WHERE OLD.availability IS NOT NEW.availability
        UNION ALL
        SELECT 'source' AS field_name, json_quote(OLD.source) AS value_json WHERE OLD.source IS NOT NEW.source
        UNION ALL
        SELECT 'is_active' AS field_name, json_quote(OLD.is_active) AS value_json WHERE OLD.is_active IS NOT NEW.is_active
    )),
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'candidate_code' AS field_name, json_quote(NEW.candidate_code) AS value_json WHERE OLD.candidate_code IS NOT NEW.candidate_code
        UNION ALL
        SELECT 'full_name' AS field_name, json_quote(NEW.full_name) AS value_json WHERE OLD.full_name IS NOT NEW.full_name
        UNION ALL
        SELECT 'phone' AS field_name, json_quote(NEW.phone) AS value_json WHERE OLD.phone IS NOT NEW.phone
        UNION ALL
        SELECT 'email' AS field_name, json_quote(NEW.email) AS value_json WHERE OLD.email IS NOT NEW.email
        UNION ALL
        SELECT 'links_json' AS field_name, NEW.links_json AS value_json WHERE OLD.links_json IS NOT NEW.links_json
        UNION ALL
        SELECT 'job_title' AS field_name, json_quote(NEW.job_title) AS value_json WHERE OLD.job_title IS NOT NEW.job_title
        UNION ALL
        SELECT 'current_employer' AS field_name, json_quote(NEW.current_employer) AS value_json WHERE OLD.current_employer IS NOT NEW.current_employer
        UNION ALL
        SELECT 'current_city' AS field_name, json_quote(NEW.current_city) AS value_json WHERE OLD.current_city IS NOT NEW.current_city
        UNION ALL
        SELECT 'preferred_cities_json' AS field_name, NEW.preferred_cities_json AS value_json WHERE OLD.preferred_cities_json IS NOT NEW.preferred_cities_json
        UNION ALL
        SELECT 'experience_years' AS field_name, json_quote(NEW.experience_years) AS value_json WHERE OLD.experience_years IS NOT NEW.experience_years
        UNION ALL
        SELECT 'qualification' AS field_name, json_quote(NEW.qualification) AS value_json WHERE OLD.qualification IS NOT NEW.qualification
        UNION ALL
        SELECT 'primary_domain' AS field_name, json_quote(NEW.primary_domain) AS value_json WHERE OLD.primary_domain IS NOT NEW.primary_domain
        UNION ALL
        SELECT 'skills_json' AS field_name, NEW.skills_json AS value_json WHERE OLD.skills_json IS NOT NEW.skills_json
        UNION ALL
        SELECT 'professional_summary' AS field_name, json_quote(NEW.professional_summary) AS value_json WHERE OLD.professional_summary IS NOT NEW.professional_summary
        UNION ALL
        SELECT 'current_salary_inr' AS field_name, json_quote(NEW.current_salary_inr) AS value_json WHERE OLD.current_salary_inr IS NOT NEW.current_salary_inr
        UNION ALL
        SELECT 'current_salary_period' AS field_name, json_quote(NEW.current_salary_period) AS value_json WHERE OLD.current_salary_period IS NOT NEW.current_salary_period
        UNION ALL
        SELECT 'current_salary_basis' AS field_name, json_quote(NEW.current_salary_basis) AS value_json WHERE OLD.current_salary_basis IS NOT NEW.current_salary_basis
        UNION ALL
        SELECT 'expected_salary_inr' AS field_name, json_quote(NEW.expected_salary_inr) AS value_json WHERE OLD.expected_salary_inr IS NOT NEW.expected_salary_inr
        UNION ALL
        SELECT 'expected_salary_period' AS field_name, json_quote(NEW.expected_salary_period) AS value_json WHERE OLD.expected_salary_period IS NOT NEW.expected_salary_period
        UNION ALL
        SELECT 'expected_salary_basis' AS field_name, json_quote(NEW.expected_salary_basis) AS value_json WHERE OLD.expected_salary_basis IS NOT NEW.expected_salary_basis
        UNION ALL
        SELECT 'notice_days' AS field_name, json_quote(NEW.notice_days) AS value_json WHERE OLD.notice_days IS NOT NEW.notice_days
        UNION ALL
        SELECT 'availability' AS field_name, json_quote(NEW.availability) AS value_json WHERE OLD.availability IS NOT NEW.availability
        UNION ALL
        SELECT 'source' AS field_name, json_quote(NEW.source) AS value_json WHERE OLD.source IS NOT NEW.source
        UNION ALL
        SELECT 'is_active' AS field_name, json_quote(NEW.is_active) AS value_json WHERE OLD.is_active IS NOT NEW.is_active
    )),
        json_object('entity','candidate','snapshot','changed_fields_only'));
    UPDATE candidates SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;

-- Keep raw resumes versioned: insert replacement row instead of overwriting uploaded bytes.
-- Only is_current can be toggled. Resume event metadata never copies raw_text or parsed_json.
CREATE TRIGGER IF NOT EXISTS trg_resume_no_mutation BEFORE UPDATE ON candidate_resumes
WHEN OLD.id IS NOT NEW.id OR OLD.candidate_id IS NOT NEW.candidate_id
  OR OLD.source_type IS NOT NEW.source_type OR OLD.resume_kind IS NOT NEW.resume_kind
  OR OLD.original_filename IS NOT NEW.original_filename
  OR OLD.storage_path IS NOT NEW.storage_path OR OLD.raw_text IS NOT NEW.raw_text
  OR OLD.parsed_json IS NOT NEW.parsed_json OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT,'Create a new resume version instead of modifying a saved resume'); END;
CREATE TRIGGER IF NOT EXISTS trg_resume_no_delete BEFORE DELETE ON candidate_resumes
BEGIN SELECT RAISE(ABORT,'Resume versions are retained; use is_current=0'); END;
CREATE TRIGGER IF NOT EXISTS trg_resume_added AFTER INSERT ON candidate_resumes
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,after_json,payload_json)
    VALUES(NEW.candidate_id,'RESUME_ADDED',
        json_object('resume_id',NEW.id,'resume_kind',NEW.resume_kind,
                    'source_type',NEW.source_type,'original_filename',NEW.original_filename,
                    'is_current',NEW.is_current),
        json_object('entity','candidate_resume','resume_id',NEW.id));
END;
CREATE TRIGGER IF NOT EXISTS trg_resume_current_changed AFTER UPDATE OF is_current ON candidate_resumes
WHEN OLD.is_current IS NOT NEW.is_current
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,before_json,after_json,payload_json)
    VALUES(NEW.candidate_id,'RESUME_STATUS_CHANGED',
        json_object('resume_id',OLD.id,'resume_kind',OLD.resume_kind,'is_current',OLD.is_current),
        json_object('resume_id',NEW.id,'resume_kind',NEW.resume_kind,'is_current',NEW.is_current),
        json_object('entity','candidate_resume','resume_id',NEW.id));
END;

-- JDs always point to a company created on the existing Companies page.
CREATE TRIGGER IF NOT EXISTS trg_jd_identity_immutable BEFORE UPDATE OF id,jd_code,created_at,is_legacy_import ON job_descriptions
WHEN OLD.id IS NOT NEW.id OR OLD.jd_code IS NOT NEW.jd_code OR OLD.created_at IS NOT NEW.created_at
  OR OLD.is_legacy_import IS NOT NEW.is_legacy_import
BEGIN SELECT RAISE(ABORT,'JD identity, creation date and legacy import status are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_jd_version_no_decrease BEFORE UPDATE OF workflow_version ON job_descriptions
WHEN NEW.workflow_version < OLD.workflow_version
BEGIN SELECT RAISE(ABORT,'JD workflow version cannot decrease'); END;
CREATE TRIGGER IF NOT EXISTS trg_jd_created AFTER INSERT ON job_descriptions
BEGIN
    INSERT INTO recruitment_events(job_id,event_type,workflow_version,after_json,payload_json)
    VALUES(NEW.id,'JD_CREATED',NEW.workflow_version,
        json_object('company_id', NEW.company_id, 'title', NEW.title, 'company_contact', NEW.company_contact, 'location', NEW.location, 'work_mode', NEW.work_mode, 'vacancies', NEW.vacancies, 'status', NEW.status, 'target_date', NEW.target_date, 'skills_json', json(NEW.skills_json), 'experience_min', NEW.experience_min, 'experience_max', NEW.experience_max, 'qualification', NEW.qualification, 'salary_min_inr', NEW.salary_min_inr, 'salary_max_inr', NEW.salary_max_inr, 'salary_period', NEW.salary_period, 'salary_basis', NEW.salary_basis, 'requirement_notes', NEW.requirement_notes, 'full_jd', NEW.full_jd, 'workflow_mode', NEW.workflow_mode, 'workflow_version', NEW.workflow_version),
        json_object('entity','job_description','jd_code',NEW.jd_code));
END;

CREATE TRIGGER IF NOT EXISTS trg_jd_updated AFTER UPDATE ON job_descriptions
WHEN OLD.company_id IS NOT NEW.company_id OR
    OLD.title IS NOT NEW.title OR
    OLD.company_contact IS NOT NEW.company_contact OR
    OLD.location IS NOT NEW.location OR
    OLD.work_mode IS NOT NEW.work_mode OR
    OLD.vacancies IS NOT NEW.vacancies OR
    OLD.status IS NOT NEW.status OR
    OLD.target_date IS NOT NEW.target_date OR
    OLD.skills_json IS NOT NEW.skills_json OR
    OLD.experience_min IS NOT NEW.experience_min OR
    OLD.experience_max IS NOT NEW.experience_max OR
    OLD.qualification IS NOT NEW.qualification OR
    OLD.salary_min_inr IS NOT NEW.salary_min_inr OR
    OLD.salary_max_inr IS NOT NEW.salary_max_inr OR
    OLD.salary_period IS NOT NEW.salary_period OR
    OLD.salary_basis IS NOT NEW.salary_basis OR
    OLD.requirement_notes IS NOT NEW.requirement_notes OR
    OLD.full_jd IS NOT NEW.full_jd
BEGIN
    INSERT INTO recruitment_events(job_id,event_type,workflow_version,before_json,after_json,payload_json)
    VALUES(NEW.id,'JD_UPDATED',NEW.workflow_version,
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'company_id' AS field_name, json_quote(OLD.company_id) AS value_json WHERE OLD.company_id IS NOT NEW.company_id
        UNION ALL
        SELECT 'title' AS field_name, json_quote(OLD.title) AS value_json WHERE OLD.title IS NOT NEW.title
        UNION ALL
        SELECT 'company_contact' AS field_name, json_quote(OLD.company_contact) AS value_json WHERE OLD.company_contact IS NOT NEW.company_contact
        UNION ALL
        SELECT 'location' AS field_name, json_quote(OLD.location) AS value_json WHERE OLD.location IS NOT NEW.location
        UNION ALL
        SELECT 'work_mode' AS field_name, json_quote(OLD.work_mode) AS value_json WHERE OLD.work_mode IS NOT NEW.work_mode
        UNION ALL
        SELECT 'vacancies' AS field_name, json_quote(OLD.vacancies) AS value_json WHERE OLD.vacancies IS NOT NEW.vacancies
        UNION ALL
        SELECT 'status' AS field_name, json_quote(OLD.status) AS value_json WHERE OLD.status IS NOT NEW.status
        UNION ALL
        SELECT 'target_date' AS field_name, json_quote(OLD.target_date) AS value_json WHERE OLD.target_date IS NOT NEW.target_date
        UNION ALL
        SELECT 'skills_json' AS field_name, OLD.skills_json AS value_json WHERE OLD.skills_json IS NOT NEW.skills_json
        UNION ALL
        SELECT 'experience_min' AS field_name, json_quote(OLD.experience_min) AS value_json WHERE OLD.experience_min IS NOT NEW.experience_min
        UNION ALL
        SELECT 'experience_max' AS field_name, json_quote(OLD.experience_max) AS value_json WHERE OLD.experience_max IS NOT NEW.experience_max
        UNION ALL
        SELECT 'qualification' AS field_name, json_quote(OLD.qualification) AS value_json WHERE OLD.qualification IS NOT NEW.qualification
        UNION ALL
        SELECT 'salary_min_inr' AS field_name, json_quote(OLD.salary_min_inr) AS value_json WHERE OLD.salary_min_inr IS NOT NEW.salary_min_inr
        UNION ALL
        SELECT 'salary_max_inr' AS field_name, json_quote(OLD.salary_max_inr) AS value_json WHERE OLD.salary_max_inr IS NOT NEW.salary_max_inr
        UNION ALL
        SELECT 'salary_period' AS field_name, json_quote(OLD.salary_period) AS value_json WHERE OLD.salary_period IS NOT NEW.salary_period
        UNION ALL
        SELECT 'salary_basis' AS field_name, json_quote(OLD.salary_basis) AS value_json WHERE OLD.salary_basis IS NOT NEW.salary_basis
        UNION ALL
        SELECT 'requirement_notes' AS field_name, json_quote(OLD.requirement_notes) AS value_json WHERE OLD.requirement_notes IS NOT NEW.requirement_notes
        UNION ALL
        SELECT 'full_jd' AS field_name, json_quote(OLD.full_jd) AS value_json WHERE OLD.full_jd IS NOT NEW.full_jd
    )),
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'company_id' AS field_name, json_quote(NEW.company_id) AS value_json WHERE OLD.company_id IS NOT NEW.company_id
        UNION ALL
        SELECT 'title' AS field_name, json_quote(NEW.title) AS value_json WHERE OLD.title IS NOT NEW.title
        UNION ALL
        SELECT 'company_contact' AS field_name, json_quote(NEW.company_contact) AS value_json WHERE OLD.company_contact IS NOT NEW.company_contact
        UNION ALL
        SELECT 'location' AS field_name, json_quote(NEW.location) AS value_json WHERE OLD.location IS NOT NEW.location
        UNION ALL
        SELECT 'work_mode' AS field_name, json_quote(NEW.work_mode) AS value_json WHERE OLD.work_mode IS NOT NEW.work_mode
        UNION ALL
        SELECT 'vacancies' AS field_name, json_quote(NEW.vacancies) AS value_json WHERE OLD.vacancies IS NOT NEW.vacancies
        UNION ALL
        SELECT 'status' AS field_name, json_quote(NEW.status) AS value_json WHERE OLD.status IS NOT NEW.status
        UNION ALL
        SELECT 'target_date' AS field_name, json_quote(NEW.target_date) AS value_json WHERE OLD.target_date IS NOT NEW.target_date
        UNION ALL
        SELECT 'skills_json' AS field_name, NEW.skills_json AS value_json WHERE OLD.skills_json IS NOT NEW.skills_json
        UNION ALL
        SELECT 'experience_min' AS field_name, json_quote(NEW.experience_min) AS value_json WHERE OLD.experience_min IS NOT NEW.experience_min
        UNION ALL
        SELECT 'experience_max' AS field_name, json_quote(NEW.experience_max) AS value_json WHERE OLD.experience_max IS NOT NEW.experience_max
        UNION ALL
        SELECT 'qualification' AS field_name, json_quote(NEW.qualification) AS value_json WHERE OLD.qualification IS NOT NEW.qualification
        UNION ALL
        SELECT 'salary_min_inr' AS field_name, json_quote(NEW.salary_min_inr) AS value_json WHERE OLD.salary_min_inr IS NOT NEW.salary_min_inr
        UNION ALL
        SELECT 'salary_max_inr' AS field_name, json_quote(NEW.salary_max_inr) AS value_json WHERE OLD.salary_max_inr IS NOT NEW.salary_max_inr
        UNION ALL
        SELECT 'salary_period' AS field_name, json_quote(NEW.salary_period) AS value_json WHERE OLD.salary_period IS NOT NEW.salary_period
        UNION ALL
        SELECT 'salary_basis' AS field_name, json_quote(NEW.salary_basis) AS value_json WHERE OLD.salary_basis IS NOT NEW.salary_basis
        UNION ALL
        SELECT 'requirement_notes' AS field_name, json_quote(NEW.requirement_notes) AS value_json WHERE OLD.requirement_notes IS NOT NEW.requirement_notes
        UNION ALL
        SELECT 'full_jd' AS field_name, json_quote(NEW.full_jd) AS value_json WHERE OLD.full_jd IS NOT NEW.full_jd
    )),
        json_object('entity','job_description','jd_code',NEW.jd_code,'snapshot','changed_fields_only'));
    UPDATE job_descriptions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_jd_workflow_updated AFTER UPDATE ON job_descriptions
WHEN OLD.workflow_mode IS NOT NEW.workflow_mode OR
    OLD.workflow_version IS NOT NEW.workflow_version
BEGIN
    INSERT INTO recruitment_events(job_id,event_type,workflow_version,before_json,after_json,payload_json)
    VALUES(NEW.id,'JD_WORKFLOW_UPDATED',NEW.workflow_version,
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'workflow_mode' AS field_name, json_quote(OLD.workflow_mode) AS value_json WHERE OLD.workflow_mode IS NOT NEW.workflow_mode
        UNION ALL
        SELECT 'workflow_version' AS field_name, json_quote(OLD.workflow_version) AS value_json WHERE OLD.workflow_version IS NOT NEW.workflow_version
    )),
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'workflow_mode' AS field_name, json_quote(NEW.workflow_mode) AS value_json WHERE OLD.workflow_mode IS NOT NEW.workflow_mode
        UNION ALL
        SELECT 'workflow_version' AS field_name, json_quote(NEW.workflow_version) AS value_json WHERE OLD.workflow_version IS NOT NEW.workflow_version
    )),
        json_object('entity','job_description','jd_code',NEW.jd_code,'snapshot','changed_fields_only'));
    UPDATE job_descriptions SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;

-- Stable company round IDs: rename, reorder, add, retire and restore are auditable.
CREATE TRIGGER IF NOT EXISTS trg_round_identity_immutable BEFORE UPDATE OF id,job_id,created_at ON jd_interview_rounds
WHEN OLD.id IS NOT NEW.id OR OLD.job_id IS NOT NEW.job_id OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT,'Round ID, linked JD and creation date are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_round_retire_with_candidate BEFORE UPDATE OF is_active ON jd_interview_rounds
WHEN OLD.is_active=1 AND NEW.is_active=0 AND
     EXISTS(SELECT 1 FROM jd_candidates WHERE round_id=OLD.id AND stage_code='ROUND')
BEGIN SELECT RAISE(ABORT,'Move candidate out of this round before retirement'); END;
CREATE TRIGGER IF NOT EXISTS trg_round_no_delete BEFORE DELETE ON jd_interview_rounds
BEGIN SELECT RAISE(ABORT,'Saved interview rounds cannot be deleted; retire instead'); END;
CREATE TRIGGER IF NOT EXISTS trg_round_added AFTER INSERT ON jd_interview_rounds
BEGIN
    INSERT INTO recruitment_events(job_id,event_type,workflow_version,after_json,payload_json)
    VALUES(NEW.job_id,'ROUND_ADDED',
       (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
       json_object('id', NEW.id, 'round_name', NEW.round_name, 'display_order', NEW.display_order, 'mode', NEW.mode, 'is_active', NEW.is_active, 'retired_at', NEW.retired_at),
       json_object('entity','jd_interview_round','round_id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_round_updated AFTER UPDATE ON jd_interview_rounds
WHEN OLD.round_name IS NOT NEW.round_name OR
    OLD.display_order IS NOT NEW.display_order OR
    OLD.mode IS NOT NEW.mode OR
    OLD.is_active IS NOT NEW.is_active OR
    OLD.retired_at IS NOT NEW.retired_at
BEGIN
    INSERT INTO recruitment_events(job_id,event_type,workflow_version,before_json,after_json,payload_json)
    VALUES(NEW.job_id,
       CASE WHEN OLD.is_active=1 AND NEW.is_active=0 THEN 'ROUND_RETIRED'
            WHEN OLD.is_active=0 AND NEW.is_active=1 THEN 'ROUND_RESTORED'
            ELSE 'ROUND_UPDATED' END,
       (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
       (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'round_name' AS field_name, json_quote(OLD.round_name) AS value_json WHERE OLD.round_name IS NOT NEW.round_name
        UNION ALL
        SELECT 'display_order' AS field_name, json_quote(OLD.display_order) AS value_json WHERE OLD.display_order IS NOT NEW.display_order
        UNION ALL
        SELECT 'mode' AS field_name, json_quote(OLD.mode) AS value_json WHERE OLD.mode IS NOT NEW.mode
        UNION ALL
        SELECT 'is_active' AS field_name, json_quote(OLD.is_active) AS value_json WHERE OLD.is_active IS NOT NEW.is_active
        UNION ALL
        SELECT 'retired_at' AS field_name, json_quote(OLD.retired_at) AS value_json WHERE OLD.retired_at IS NOT NEW.retired_at
    )),
       (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'round_name' AS field_name, json_quote(NEW.round_name) AS value_json WHERE OLD.round_name IS NOT NEW.round_name
        UNION ALL
        SELECT 'display_order' AS field_name, json_quote(NEW.display_order) AS value_json WHERE OLD.display_order IS NOT NEW.display_order
        UNION ALL
        SELECT 'mode' AS field_name, json_quote(NEW.mode) AS value_json WHERE OLD.mode IS NOT NEW.mode
        UNION ALL
        SELECT 'is_active' AS field_name, json_quote(NEW.is_active) AS value_json WHERE OLD.is_active IS NOT NEW.is_active
        UNION ALL
        SELECT 'retired_at' AS field_name, json_quote(NEW.retired_at) AS value_json WHERE OLD.retired_at IS NOT NEW.retired_at
    )),
       json_object('entity','jd_interview_round','round_id',NEW.id,'snapshot','changed_fields_only'));
END;

-- An association starts in POOL, only for ACTIVE JDs, one row per (job,candidate).
CREATE TRIGGER IF NOT EXISTS trg_pool_insert_active BEFORE INSERT ON jd_candidates
BEGIN
    SELECT CASE WHEN (SELECT status FROM job_descriptions WHERE id=NEW.job_id) <> 'ACTIVE'
        THEN RAISE(ABORT,'Only ACTIVE JDs accept candidates') END;
    SELECT CASE WHEN NEW.stage_code <> 'POOL' OR NEW.round_id IS NOT NULL
        THEN RAISE(ABORT,'New JD links must start at Candidate Pool') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_jd_candidate_identity_immutable BEFORE UPDATE OF job_id,candidate_id ON jd_candidates
WHEN OLD.job_id<>NEW.job_id OR OLD.candidate_id<>NEW.candidate_id
BEGIN SELECT RAISE(ABORT,'Candidate JD identity cannot be reassigned'); END;
CREATE TRIGGER IF NOT EXISTS trg_round_stage_valid BEFORE UPDATE OF stage_code,round_id ON jd_candidates
WHEN NEW.stage_code='ROUND'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM jd_interview_rounds r
        WHERE r.id=NEW.round_id AND r.job_id=NEW.job_id AND r.is_active=1
    ) THEN RAISE(ABORT,'Round is missing, inactive, or belongs to another JD') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_terminal_stage_lock BEFORE UPDATE OF stage_code,round_id ON jd_candidates
WHEN OLD.stage_code<>NEW.stage_code OR COALESCE(OLD.round_id,'')<>COALESCE(NEW.round_id,'')
BEGIN
    SELECT CASE WHEN OLD.stage_code IN ('JOINED','NOT_SELECTED')
        THEN RAISE(ABORT,'Terminal candidate outcome cannot be changed') END;
    SELECT CASE WHEN OLD.stage_code='SELECTED' AND NEW.stage_code<>'JOINED'
        THEN RAISE(ABORT,'Selected candidates can only advance to Joined') END;
    SELECT CASE WHEN NEW.stage_code='NOT_SELECTED' AND
        (NEW.rejected_from_stage IS NULL OR NEW.rejected_at IS NULL)
        THEN RAISE(ABORT,'Store rejection-stage snapshot before marking Not Selected') END;
END;
CREATE TRIGGER IF NOT EXISTS trg_rejection_snapshot_immutable
BEFORE UPDATE OF rejected_from_stage,rejected_round_name,rejected_round_index,rejected_at ON jd_candidates
WHEN OLD.stage_code='NOT_SELECTED' AND (
    OLD.rejected_from_stage IS NOT NEW.rejected_from_stage
    OR OLD.rejected_round_name IS NOT NEW.rejected_round_name
    OR OLD.rejected_round_index IS NOT NEW.rejected_round_index
    OR OLD.rejected_at IS NOT NEW.rejected_at
)
BEGIN SELECT RAISE(ABORT,'Rejected-stage snapshot cannot be edited after rejection'); END;
CREATE TRIGGER IF NOT EXISTS trg_pool_added AFTER INSERT ON jd_candidates
BEGIN
    INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,to_stage,to_label_snapshot,
                                    workflow_version,after_json,payload_json)
    VALUES(NEW.job_id,NEW.candidate_id,NEW.id,'ADDED','POOL','Candidate Pool',
           (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
           json_object('stage_code','POOL','round_id',NULL),
           json_object('entity','jd_candidate'));
END;
CREATE TRIGGER IF NOT EXISTS trg_pool_moved AFTER UPDATE OF stage_code,round_id ON jd_candidates
WHEN OLD.stage_code<>NEW.stage_code OR COALESCE(OLD.round_id,'')<>COALESCE(NEW.round_id,'')
BEGIN
    INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,from_stage,to_stage,
        from_label_snapshot,to_label_snapshot,workflow_version,before_json,after_json,payload_json)
    VALUES (NEW.job_id,NEW.candidate_id,NEW.id,
        CASE WHEN NEW.stage_code='NOT_SELECTED' THEN 'REJECTED' ELSE 'MOVED' END,
        OLD.stage_code,NEW.stage_code,
        CASE OLD.stage_code
          WHEN 'POOL' THEN 'Candidate Pool' WHEN 'CONTACT' THEN 'Candidate Contact'
          WHEN 'SCREENING' THEN 'Jobmitra Screening' WHEN 'COMPANY_SUBMISSION' THEN 'Company Submission'
          WHEN 'SELECTED' THEN 'Selected by Company' WHEN 'JOINED' THEN 'Joined'
          WHEN 'NOT_SELECTED' THEN 'Not Selected'
          WHEN 'ROUND' THEN COALESCE((SELECT round_name FROM jd_interview_rounds WHERE id=OLD.round_id),'Interview Round')
        END,
        CASE NEW.stage_code
          WHEN 'POOL' THEN 'Candidate Pool' WHEN 'CONTACT' THEN 'Candidate Contact'
          WHEN 'SCREENING' THEN 'Jobmitra Screening' WHEN 'COMPANY_SUBMISSION' THEN 'Company Submission'
          WHEN 'SELECTED' THEN 'Selected by Company' WHEN 'JOINED' THEN 'Joined'
          WHEN 'NOT_SELECTED' THEN 'Not Selected'
          WHEN 'ROUND' THEN COALESCE((SELECT round_name FROM jd_interview_rounds WHERE id=NEW.round_id),'Interview Round')
        END,
        (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
        json_object('stage_code',OLD.stage_code,'round_id',OLD.round_id,'stage_note',OLD.stage_note),
        json_object('stage_code',NEW.stage_code,'round_id',NEW.round_id,'stage_note',NEW.stage_note,
                    'rejected_from_stage',NEW.rejected_from_stage,
                    'rejected_round_name',NEW.rejected_round_name,
                    'rejected_round_index',NEW.rejected_round_index,'rejected_at',NEW.rejected_at),
        json_object('entity','jd_candidate','from_round_id',OLD.round_id,'to_round_id',NEW.round_id));
    UPDATE jd_candidates SET stage_updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_pool_note_changed AFTER UPDATE OF stage_note ON jd_candidates
WHEN OLD.stage_note IS NOT NEW.stage_note
     AND OLD.stage_code=NEW.stage_code AND COALESCE(OLD.round_id,'')=COALESCE(NEW.round_id,'')
BEGIN
    INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,workflow_version,
                                   before_json,after_json,payload_json)
    VALUES(NEW.job_id,NEW.candidate_id,NEW.id,'STAGE_NOTE_UPDATED',
       (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
       json_object('stage_note',OLD.stage_note),json_object('stage_note',NEW.stage_note),
       json_object('entity','jd_candidate'));
END;

-- One activity table also records its creation, rescheduling, completion, cancellation.
CREATE TRIGGER IF NOT EXISTS trg_activity_candidate_immutable BEFORE UPDATE OF id,candidate_id,created_at ON candidate_activities
WHEN OLD.id IS NOT NEW.id OR OLD.candidate_id IS NOT NEW.candidate_id OR OLD.created_at IS NOT NEW.created_at
BEGIN SELECT RAISE(ABORT,'Activity identity and linked candidate are immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_activity_no_delete BEFORE DELETE ON candidate_activities
BEGIN SELECT RAISE(ABORT,'Cancel activities instead of deleting history'); END;
CREATE TRIGGER IF NOT EXISTS trg_activity_created AFTER INSERT ON candidate_activities
BEGIN
    INSERT INTO recruitment_events(job_id,candidate_id,event_type,after_json,payload_json)
    VALUES(NEW.job_id,NEW.candidate_id,'ACTIVITY_CREATED',
        json_object('id', NEW.id, 'job_id', NEW.job_id, 'activity_type', NEW.activity_type, 'status', NEW.status, 'due_at', NEW.due_at, 'occurred_at', NEW.occurred_at, 'notes', NEW.notes, 'details_json', json(NEW.details_json)),
        json_object('entity','candidate_activity','activity_id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_activity_updated AFTER UPDATE ON candidate_activities
WHEN OLD.job_id IS NOT NEW.job_id OR
    OLD.activity_type IS NOT NEW.activity_type OR
    OLD.status IS NOT NEW.status OR
    OLD.due_at IS NOT NEW.due_at OR
    OLD.occurred_at IS NOT NEW.occurred_at OR
    OLD.notes IS NOT NEW.notes OR
    OLD.details_json IS NOT NEW.details_json
BEGIN
    INSERT INTO recruitment_events(job_id,candidate_id,event_type,before_json,after_json,payload_json)
    VALUES(NEW.job_id,NEW.candidate_id,'ACTIVITY_UPDATED',
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'job_id' AS field_name, json_quote(OLD.job_id) AS value_json WHERE OLD.job_id IS NOT NEW.job_id
        UNION ALL
        SELECT 'activity_type' AS field_name, json_quote(OLD.activity_type) AS value_json WHERE OLD.activity_type IS NOT NEW.activity_type
        UNION ALL
        SELECT 'status' AS field_name, json_quote(OLD.status) AS value_json WHERE OLD.status IS NOT NEW.status
        UNION ALL
        SELECT 'due_at' AS field_name, json_quote(OLD.due_at) AS value_json WHERE OLD.due_at IS NOT NEW.due_at
        UNION ALL
        SELECT 'occurred_at' AS field_name, json_quote(OLD.occurred_at) AS value_json WHERE OLD.occurred_at IS NOT NEW.occurred_at
        UNION ALL
        SELECT 'notes' AS field_name, json_quote(OLD.notes) AS value_json WHERE OLD.notes IS NOT NEW.notes
        UNION ALL
        SELECT 'details_json' AS field_name, OLD.details_json AS value_json WHERE OLD.details_json IS NOT NEW.details_json
    )),
        (SELECT json_group_object(field_name, json(value_json)) FROM (
        SELECT 'job_id' AS field_name, json_quote(NEW.job_id) AS value_json WHERE OLD.job_id IS NOT NEW.job_id
        UNION ALL
        SELECT 'activity_type' AS field_name, json_quote(NEW.activity_type) AS value_json WHERE OLD.activity_type IS NOT NEW.activity_type
        UNION ALL
        SELECT 'status' AS field_name, json_quote(NEW.status) AS value_json WHERE OLD.status IS NOT NEW.status
        UNION ALL
        SELECT 'due_at' AS field_name, json_quote(NEW.due_at) AS value_json WHERE OLD.due_at IS NOT NEW.due_at
        UNION ALL
        SELECT 'occurred_at' AS field_name, json_quote(NEW.occurred_at) AS value_json WHERE OLD.occurred_at IS NOT NEW.occurred_at
        UNION ALL
        SELECT 'notes' AS field_name, json_quote(NEW.notes) AS value_json WHERE OLD.notes IS NOT NEW.notes
        UNION ALL
        SELECT 'details_json' AS field_name, NEW.details_json AS value_json WHERE OLD.details_json IS NOT NEW.details_json
    )),
        json_object('entity','candidate_activity','activity_id',NEW.id,'snapshot','changed_fields_only'));
END;

CREATE VIEW IF NOT EXISTS v_jd_dashboard AS
WITH joined AS (
    SELECT job_id,COUNT(*) AS joined_count
    FROM jd_candidates WHERE stage_code='JOINED' GROUP BY job_id
), amounts AS (
    SELECT j.id,j.jd_code,j.company_id,j.title,j.status,j.created_at,j.target_date,j.vacancies,
           COALESCE(x.joined_count,0) AS joined_count
    FROM job_descriptions j LEFT JOIN joined x ON x.job_id=j.id
)
SELECT a.*,
  CASE
    WHEN status='CLOSED' THEN 'CLOSED'
    WHEN vacancies IS NOT NULL AND joined_count>=vacancies THEN 'FILLED'
    WHEN status<>'ACTIVE' OR target_date IS NULL THEN 'UNSET'
    WHEN target_date<date('now','+330 minutes') THEN 'OVERDUE'
    WHEN target_date<=date('now','+330 minutes','+2 days') THEN 'DUE'
    ELSE 'TRACK'
  END AS target_state,
  CAST(julianday(target_date)-julianday(date('now','+330 minutes')) AS INTEGER) AS days_remaining
FROM amounts a;

CREATE VIEW IF NOT EXISTS v_jd_stage_counts AS
SELECT job_id,stage_code,COALESCE(round_id,'') AS round_key,COUNT(*) AS candidate_count
FROM jd_candidates GROUP BY job_id,stage_code,COALESCE(round_id,'');

CREATE VIEW IF NOT EXISTS v_candidate_jd_history AS
SELECT l.id AS jd_candidate_id,l.candidate_id,c.full_name,j.id AS job_id,j.jd_code,
       j.title AS job_title,l.stage_code,l.round_id,l.added_at,
       l.rejected_from_stage,l.rejected_round_name,l.rejected_round_index,l.rejected_at
FROM jd_candidates l JOIN candidates c ON c.id=l.candidate_id
JOIN job_descriptions j ON j.id=l.job_id;

-- Company dropdown options are resolved through the existing PostgreSQL service.


PRAGMA application_id=1246576980;
PRAGMA user_version=1;
