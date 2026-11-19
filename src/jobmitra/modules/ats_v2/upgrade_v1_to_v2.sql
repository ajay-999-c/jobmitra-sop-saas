-- ATS schema version 2: local companies and provenance for explicit legacy imports.
-- Applies only after exact version-1 validation, inside the caller's transaction.
CREATE TABLE IF NOT EXISTS companies (
    id                          TEXT PRIMARY KEY CHECK(length(id)=36),
    legacy_postgres_id          TEXT UNIQUE,
    company_name                TEXT NOT NULL CHECK(length(trim(company_name))>0),
    company_name_key            TEXT NOT NULL UNIQUE CHECK(length(trim(company_name_key))>0),
    general_phone_numbers_json  TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(general_phone_numbers_json) AND json_type(general_phone_numbers_json)='array'),
    contacts_json               TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(contacts_json) AND json_type(contacts_json)='array'),
    address_line                TEXT,
    city                        TEXT,
    state                       TEXT,
    postal_code                 TEXT,
    source_register_ids_json    TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_register_ids_json) AND json_type(source_register_ids_json)='array'),
    is_active                   INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at                  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    source_json                 TEXT CHECK(source_json IS NULL OR json_valid(source_json)),
    source_fingerprint          TEXT,
    imported_at                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_ats_company_options ON companies(is_active,company_name_key,id);

ALTER TABLE candidates ADD COLUMN legacy_postgres_id TEXT;
ALTER TABLE candidates ADD COLUMN source_json TEXT CHECK(source_json IS NULL OR json_valid(source_json));
ALTER TABLE candidates ADD COLUMN source_fingerprint TEXT;
ALTER TABLE candidates ADD COLUMN imported_at TEXT;
CREATE UNIQUE INDEX uq_candidate_legacy_postgres ON candidates(legacy_postgres_id);

ALTER TABLE candidate_resumes ADD COLUMN legacy_source_table TEXT;
ALTER TABLE candidate_resumes ADD COLUMN legacy_postgres_id TEXT;
ALTER TABLE candidate_resumes ADD COLUMN source_json TEXT CHECK(source_json IS NULL OR json_valid(source_json));
ALTER TABLE candidate_resumes ADD COLUMN imported_at TEXT;
CREATE UNIQUE INDEX uq_resume_legacy_postgres ON candidate_resumes(legacy_source_table,legacy_postgres_id);

CREATE TRIGGER trg_local_company_identity_immutable BEFORE UPDATE OF id ON companies
WHEN OLD.id IS NOT NEW.id
BEGIN SELECT RAISE(ABORT,'Company identity cannot be reassigned'); END;
CREATE TRIGGER trg_local_company_no_referenced_delete BEFORE DELETE ON companies
WHEN EXISTS(SELECT 1 FROM job_descriptions WHERE company_id=OLD.id)
BEGIN SELECT RAISE(ABORT,'Referenced companies cannot be deleted; deactivate instead'); END;
CREATE TRIGGER trg_jd_local_company_valid BEFORE INSERT ON job_descriptions
WHEN NOT EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id AND is_active=1)
BEGIN SELECT RAISE(ABORT,'Select an existing active ATS company'); END;
CREATE TRIGGER trg_jd_local_company_change_valid BEFORE UPDATE OF company_id ON job_descriptions
WHEN OLD.company_id IS NOT NEW.company_id AND
     NOT EXISTS(SELECT 1 FROM companies WHERE id=NEW.company_id AND is_active=1)
BEGIN SELECT RAISE(ABORT,'Select an existing active ATS company'); END;

-- Imported identities and provenance remain attached to the imported master.
CREATE TRIGGER trg_candidate_legacy_identity_immutable
BEFORE UPDATE OF legacy_postgres_id ON candidates
WHEN OLD.legacy_postgres_id IS NOT NEW.legacy_postgres_id
BEGIN SELECT RAISE(ABORT,'Imported candidate source identity is immutable'); END;
CREATE TRIGGER trg_resume_legacy_identity_immutable
BEFORE UPDATE OF legacy_source_table,legacy_postgres_id,source_json,imported_at ON candidate_resumes
WHEN OLD.legacy_source_table IS NOT NEW.legacy_source_table OR
     OLD.legacy_postgres_id IS NOT NEW.legacy_postgres_id OR
     OLD.source_json IS NOT NEW.source_json OR OLD.imported_at IS NOT NEW.imported_at
BEGIN SELECT RAISE(ABORT,'Imported resume provenance is immutable'); END;

DROP TRIGGER trg_candidate_created;
CREATE TRIGGER IF NOT EXISTS trg_candidate_created AFTER INSERT ON candidates
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,after_json,payload_json)
    VALUES(NEW.id,CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN 'CANDIDATE_IMPORTED' ELSE 'CANDIDATE_CREATED' END,
        json_object('candidate_code', NEW.candidate_code, 'full_name', NEW.full_name, 'phone', NEW.phone, 'email', NEW.email, 'links_json', json(NEW.links_json), 'job_title', NEW.job_title, 'current_employer', NEW.current_employer, 'current_city', NEW.current_city, 'preferred_cities_json', json(NEW.preferred_cities_json), 'experience_years', NEW.experience_years, 'qualification', NEW.qualification, 'primary_domain', NEW.primary_domain, 'skills_json', json(NEW.skills_json), 'professional_summary', NEW.professional_summary, 'current_salary_inr', NEW.current_salary_inr, 'current_salary_period', NEW.current_salary_period, 'current_salary_basis', NEW.current_salary_basis, 'expected_salary_inr', NEW.expected_salary_inr, 'expected_salary_period', NEW.expected_salary_period, 'expected_salary_basis', NEW.expected_salary_basis, 'notice_days', NEW.notice_days, 'availability', NEW.availability, 'source', NEW.source, 'is_active', NEW.is_active),
        CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN
            json_object('entity','candidate','source','postgresql','source_table','candidates',
                        'source_id',NEW.legacy_postgres_id,'source_created_at',NEW.created_at,
                        'imported_at',NEW.imported_at)
        ELSE json_object('entity','candidate') END);
END;

DROP TRIGGER trg_resume_added;
CREATE TRIGGER IF NOT EXISTS trg_resume_added AFTER INSERT ON candidate_resumes
BEGIN
    INSERT INTO recruitment_events(candidate_id,event_type,after_json,payload_json)
    VALUES(NEW.candidate_id,CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN 'RESUME_IMPORTED' ELSE 'RESUME_ADDED' END,
        json_object('resume_id',NEW.id,'resume_kind',NEW.resume_kind,
                    'source_type',NEW.source_type,'original_filename',NEW.original_filename,
                    'is_current',NEW.is_current),
        CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN
            json_object('entity','candidate_resume','resume_id',NEW.id,'source','postgresql',
                        'source_table',NEW.legacy_source_table,'source_id',NEW.legacy_postgres_id,
                        'source_created_at',NEW.created_at,'imported_at',NEW.imported_at)
        ELSE json_object('entity','candidate_resume','resume_id',NEW.id) END);
END;

PRAGMA user_version=2;
