BEGIN;

-- Running upgrade 0006_jd_catalog_links -> 0007_candidate_resumes

CREATE TABLE candidate_resumes (
    id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    original_filename TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_hash TEXT NOT NULL,
    extracted_text TEXT,
    parsed_json JSONB,
    parsing_status TEXT DEFAULT 'not_parsed' NOT NULL,
    parsing_error TEXT,
    is_active BOOLEAN DEFAULT true NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_candidate_resume_storage UNIQUE (storage_key),
    CONSTRAINT ck_candidate_resume_integrity CHECK (file_size > 0 AND file_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_candidate_resume_parsing CHECK (parsing_status IN ('not_parsed','processing','parsed','failed')),
    FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX uq_candidate_resume_active ON candidate_resumes (candidate_id) WHERE is_active;

CREATE INDEX ix_candidate_resume_history ON candidate_resumes (candidate_id, uploaded_at);

UPDATE alembic_version SET version_num='0007_candidate_resumes' WHERE alembic_version.version_num = '0006_jd_catalog_links';

COMMIT;
