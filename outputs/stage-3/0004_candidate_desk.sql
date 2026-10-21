BEGIN;

-- Running upgrade 0003_jd_work_focus -> 0004_candidate_desk

CREATE TABLE work_domains (
    key TEXT NOT NULL, 
    name TEXT NOT NULL, 
    normalized_name TEXT NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_work_domain_name CHECK (length(btrim(name)) > 0 AND length(normalized_name)>0 AND length(key)>0), 
    CONSTRAINT uq_work_domain_key UNIQUE (key), 
    CONSTRAINT uq_work_domain_name UNIQUE (normalized_name)
);

CREATE TABLE work_subdomains (
    domain_id UUID NOT NULL, 
    key TEXT NOT NULL, 
    name TEXT NOT NULL, 
    normalized_name TEXT NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_work_subdomain_name CHECK (length(btrim(name))>0 AND length(normalized_name)>0 AND length(key)>0), 
    FOREIGN KEY(domain_id) REFERENCES work_domains (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_work_subdomain_key UNIQUE (domain_id, key), 
    CONSTRAINT uq_work_subdomain_name UNIQUE (domain_id, normalized_name), 
    CONSTRAINT uq_work_subdomain_parent UNIQUE (id, domain_id)
);

CREATE TABLE candidates (
    full_name TEXT NOT NULL, 
    mobile TEXT NOT NULL, 
    mobile_normalized TEXT NOT NULL, 
    email TEXT, 
    source TEXT NOT NULL, 
    role_title TEXT, 
    domain_id UUID, 
    subdomain_id UUID, 
    qualification TEXT, 
    experience_months INTEGER, 
    skills TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    current_location TEXT, 
    preferred_locations TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    hometown TEXT, 
    home_state TEXT, 
    ready_to_relocate BOOLEAN, 
    current_salary_amount NUMERIC(14, 2), 
    current_salary_period TEXT DEFAULT 'Unknown' NOT NULL, 
    current_salary_basis TEXT DEFAULT 'Unknown' NOT NULL, 
    expected_salary_amount NUMERIC(14, 2), 
    expected_salary_period TEXT DEFAULT 'Unknown' NOT NULL, 
    expected_salary_basis TEXT DEFAULT 'Unknown' NOT NULL, 
    last_salary_raw TEXT, 
    notice_period_text TEXT, 
    version INTEGER DEFAULT '1' NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_candidate_salary CHECK (current_salary_amount >= 0 AND current_salary_amount <> 'NaN'::numeric AND expected_salary_amount >= 0 AND expected_salary_amount <> 'NaN'::numeric), 
    CONSTRAINT ck_candidate_salary_basis CHECK (current_salary_basis IN ('CTC','Gross','Take-home','Unknown') AND expected_salary_basis IN ('CTC','Gross','Take-home','Unknown')), 
    CONSTRAINT ck_candidate_salary_period CHECK (current_salary_period IN ('Monthly','Annual','Unknown') AND expected_salary_period IN ('Monthly','Annual','Unknown')), 
    CONSTRAINT ck_candidate_mobile CHECK (mobile_normalized ~ '^[0-9]{8,15}$'), 
    CONSTRAINT ck_candidate_source CHECK (source IN ('Walk-in','Foundit','WhatsApp','Referral','Existing database','Other')), 
    CONSTRAINT ck_candidate_arrays CHECK (array_position(skills,NULL) IS NULL AND array_position(preferred_locations,NULL) IS NULL), 
    CONSTRAINT ck_candidate_experience CHECK (experience_months >= 0), 
    CONSTRAINT ck_candidate_name CHECK (length(btrim(full_name))>0), 
    CONSTRAINT ck_candidate_subdomain_domain CHECK (subdomain_id IS NULL OR domain_id IS NOT NULL), 
    CONSTRAINT ck_candidate_version CHECK (version > 0), 
    FOREIGN KEY(domain_id) REFERENCES work_domains (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_candidate_subdomain_parent FOREIGN KEY(subdomain_id, domain_id) REFERENCES work_subdomains (id, domain_id) ON DELETE RESTRICT
);

CREATE INDEX ix_candidate_domain ON candidates (domain_id, subdomain_id);

CREATE INDEX ix_candidate_email ON candidates (email);

CREATE INDEX ix_candidate_mobile ON candidates (mobile_normalized);

CREATE INDEX ix_candidate_name ON candidates (full_name);

CREATE TABLE candidate_documents (
    candidate_id UUID NOT NULL, 
    kind TEXT NOT NULL, 
    original_filename TEXT NOT NULL, 
    storage_key TEXT NOT NULL, 
    content_type TEXT NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    sha256 TEXT NOT NULL, 
    uploaded_by_staff_id UUID, 
    version INTEGER NOT NULL, 
    source_document_id UUID, 
    approval_status TEXT, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_document_lineage CHECK ((kind='MODIFIED_RESUME' AND source_document_id IS NOT NULL AND approval_status='Reviewed') OR (kind<>'MODIFIED_RESUME' AND source_document_id IS NULL)), 
    CONSTRAINT ck_document_content_type CHECK (content_type IN ('application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document')), 
    CONSTRAINT ck_document_kind CHECK (kind IN ('ORIGINAL_RESUME','MODIFIED_RESUME','AUTHORITY')), 
    CONSTRAINT ck_document_integrity CHECK (size_bytes>0 AND version>0 AND sha256 ~ '^[0-9a-f]{64}$'), 
    CONSTRAINT ck_document_not_self CHECK (source_document_id IS NULL OR source_document_id<>id), 
    FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_document_source_candidate FOREIGN KEY(source_document_id, candidate_id) REFERENCES candidate_documents (id, candidate_id) ON DELETE RESTRICT, 
    FOREIGN KEY(uploaded_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    CONSTRAINT uq_document_version UNIQUE (candidate_id, kind, version), 
    CONSTRAINT uq_document_candidate UNIQUE (id, candidate_id), 
    CONSTRAINT uq_document_kind UNIQUE (id, kind), 
    CONSTRAINT uq_document_storage UNIQUE (storage_key)
);

CREATE TABLE candidate_visits (
    candidate_id UUID NOT NULL, 
    visited_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    purpose TEXT NOT NULL, 
    recorded_by_staff_id UUID, 
    authority_status TEXT DEFAULT 'Not recorded' NOT NULL, 
    note TEXT, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_candidate_visit_authority CHECK (authority_status IN ('Not recorded','Pending','Signed (reported)','Not signed')), 
    CONSTRAINT ck_candidate_visit_purpose CHECK (length(btrim(purpose))>0), 
    FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE RESTRICT, 
    FOREIGN KEY(recorded_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT
);

CREATE INDEX ix_candidate_visit_day ON candidate_visits (visited_at);

CREATE INDEX ix_candidate_visit_timeline ON candidate_visits (candidate_id, visited_at);

CREATE TABLE job_search_requests (
    candidate_id UUID NOT NULL, 
    desired_role TEXT NOT NULL, 
    preferred_locations TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    assigned_staff_id UUID NOT NULL, 
    status TEXT DEFAULT 'Searching' NOT NULL, 
    next_action TEXT, 
    follow_up_date DATE, 
    note TEXT, 
    opened_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    closed_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER DEFAULT '1' NOT NULL, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_search_closed CHECK ((status IN ('Placed','Closed')) = (closed_at IS NOT NULL)), 
    CONSTRAINT ck_search_status CHECK (status IN ('Searching','Interviewing','On Hold','Placed','Closed')), 
    CONSTRAINT ck_search_locations CHECK (array_position(preferred_locations,NULL) IS NULL), 
    CONSTRAINT ck_search_role_version CHECK (length(btrim(desired_role))>0 AND version>0), 
    FOREIGN KEY(assigned_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE RESTRICT
);

CREATE INDEX ix_search_assignee_due ON job_search_requests (assigned_staff_id, status, follow_up_date);

CREATE INDEX ix_search_candidate ON job_search_requests (candidate_id);

CREATE TABLE resume_parse_results (
    document_id UUID NOT NULL, 
    document_kind TEXT DEFAULT 'ORIGINAL_RESUME' NOT NULL, 
    provider TEXT NOT NULL, 
    model_label TEXT, 
    schema_version INTEGER DEFAULT '1' NOT NULL, 
    parsed_json JSONB NOT NULL, 
    validation_status TEXT DEFAULT 'Structurally checked' NOT NULL, 
    review_status TEXT DEFAULT 'Unreviewed' NOT NULL, 
    pasted_by_staff_id UUID, 
    reviewed_by_staff_id UUID, 
    reviewed_at TIMESTAMP WITH TIME ZONE, 
    id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_parse_review CHECK ((review_status='Unreviewed' AND reviewed_at IS NULL AND reviewed_by_staff_id IS NULL) OR (review_status IN ('Reviewed','Rejected') AND reviewed_at IS NOT NULL AND reviewed_by_staff_id IS NOT NULL)), 
    CONSTRAINT ck_parse_original CHECK (document_kind='ORIGINAL_RESUME'), 
    CONSTRAINT ck_parse_object CHECK (jsonb_typeof(parsed_json)='object'), 
    CONSTRAINT ck_parse_provider CHECK (provider IN ('ChatGPT','Claude')), 
    CONSTRAINT ck_parse_validation CHECK (validation_status='Structurally checked'), 
    CONSTRAINT ck_parse_schema CHECK (schema_version=1), 
    CONSTRAINT fk_parse_original_document FOREIGN KEY(document_id, document_kind) REFERENCES candidate_documents (id, kind) ON DELETE RESTRICT, 
    FOREIGN KEY(pasted_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(reviewed_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT
);

CREATE INDEX ix_parse_document_time ON resume_parse_results (document_id, created_at);

UPDATE alembic_version SET version_num='0004_candidate_desk' WHERE alembic_version.version_num = '0003_jd_work_focus';

COMMIT;

