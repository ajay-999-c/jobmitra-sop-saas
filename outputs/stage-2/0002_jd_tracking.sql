BEGIN;

-- Running upgrade 0001_company_management -> 0002_jd_tracking

CREATE TABLE staff_members (
    id UUID NOT NULL, 
    display_name TEXT NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_staff_name_nonblank CHECK (length(btrim(display_name)) > 0)
);

CREATE INDEX ix_staff_active_name ON staff_members (is_active, display_name);

CREATE TABLE job_requirements (
    id UUID NOT NULL, 
    company_id UUID NOT NULL, 
    company_contact_id UUID, 
    created_by_staff_id UUID NOT NULL, 
    job_title TEXT NOT NULL, 
    raw_requirement TEXT, 
    received_at TIMESTAMP WITH TIME ZONE, 
    domain_key TEXT, 
    subdomain_key TEXT, 
    location_text TEXT, 
    work_mode TEXT, 
    experience_min_months INTEGER, 
    experience_max_months INTEGER, 
    salary_min NUMERIC(12, 2), 
    salary_max NUMERIC(12, 2), 
    salary_period TEXT DEFAULT 'Unknown' NOT NULL, 
    salary_basis TEXT DEFAULT 'Unknown' NOT NULL, 
    salary_currency TEXT, 
    vacancies INTEGER, 
    qualification TEXT, 
    required_skills TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    preferred_skills TEXT[] DEFAULT '{}'::text[] NOT NULL, 
    specific_skill TEXT, 
    specific_skill_min_months INTEGER, 
    status TEXT DEFAULT 'Draft' NOT NULL, 
    target_date DATE, 
    target_milestone TEXT, 
    target_completed_at TIMESTAMP WITH TIME ZONE, 
    target_completed_by_staff_id UUID, 
    ats_json JSONB, 
    ats_schema_version SMALLINT, 
    ats_status TEXT DEFAULT 'Not Added' NOT NULL, 
    closed_at TIMESTAMP WITH TIME ZONE, 
    closed_by_staff_id UUID, 
    closure_reason TEXT, 
    version INTEGER DEFAULT '1' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_job_ats_state CHECK ((ats_json IS NULL AND ats_schema_version IS NULL AND ats_status='Not Added') OR (ats_json IS NOT NULL AND ats_schema_version IS NOT NULL AND ats_schema_version=1 AND ats_status IN ('Draft','Reviewed','Stale'))), 
    CONSTRAINT ck_job_closure CHECK ((status='Closed' AND closed_at IS NOT NULL AND closed_by_staff_id IS NOT NULL AND closure_reason IS NOT NULL AND length(btrim(closure_reason))>0) OR (status<>'Closed' AND closed_at IS NULL AND closed_by_staff_id IS NULL AND closure_reason IS NULL)), 
    CONSTRAINT ck_job_shortlist_confirmation CHECK ((target_completed_at IS NULL AND target_completed_by_staff_id IS NULL) OR (target_completed_at IS NOT NULL AND target_completed_by_staff_id IS NOT NULL AND target_milestone IS NOT NULL AND target_milestone='SHORTLIST')), 
    CONSTRAINT ck_job_salary_basis CHECK (salary_basis IN ('CTC','Gross','Take-home','Unknown')), 
    CONSTRAINT ck_job_salary_nonnegative CHECK (salary_min >= 0 AND salary_max >= 0 AND salary_min <> 'NaN'::numeric AND salary_max <> 'NaN'::numeric), 
    CONSTRAINT ck_job_salary_period CHECK (salary_period IN ('Monthly','Annual','Unknown')), 
    CONSTRAINT ck_job_status CHECK (status IN ('Draft','Active','On Hold','Closed')), 
    CONSTRAINT ck_job_target_milestone CHECK (target_milestone IN ('SHORTLIST','SELECTION','JOINING')), 
    CONSTRAINT ck_job_target_pair CHECK ((target_date IS NULL) = (target_milestone IS NULL)), 
    CONSTRAINT ck_job_skills_no_nulls CHECK (array_position(required_skills,NULL) IS NULL AND array_position(preferred_skills,NULL) IS NULL), 
    CONSTRAINT ck_job_experience_order CHECK (experience_min_months <= experience_max_months), 
    CONSTRAINT ck_job_experience_nonnegative CHECK (experience_min_months >= 0 AND experience_max_months >= 0), 
    CONSTRAINT ck_job_title_nonblank CHECK (length(btrim(job_title)) > 0), 
    CONSTRAINT ck_job_salary_order CHECK (salary_min <= salary_max), 
    CONSTRAINT ck_job_specific_months CHECK (specific_skill_min_months >= 0), 
    CONSTRAINT ck_job_vacancies_positive CHECK (vacancies > 0), 
    CONSTRAINT ck_job_version CHECK (version > 0), 
    FOREIGN KEY(closed_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_job_contact FOREIGN KEY(company_contact_id) REFERENCES company_contacts (id) ON DELETE RESTRICT, 
    CONSTRAINT fk_job_company FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE RESTRICT, 
    FOREIGN KEY(created_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(target_completed_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT
);

CREATE INDEX ix_job_company_status ON job_requirements (company_id, status);

CREATE INDEX ix_job_status ON job_requirements (status);

CREATE INDEX ix_job_target ON job_requirements (target_date) WHERE target_date IS NOT NULL;

CREATE TABLE activities (
    id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    event_type TEXT NOT NULL, 
    note TEXT, 
    changes JSONB, 
    actor_staff_id UUID, 
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_activity_type CHECK (length(btrim(event_type))>0), 
    FOREIGN KEY(actor_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(job_id) REFERENCES job_requirements (id) ON DELETE RESTRICT
);

CREATE INDEX ix_activity_job_timeline ON activities (job_id, occurred_at, id);

CREATE TABLE job_recruiters (
    job_id UUID NOT NULL, 
    staff_id UUID NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    removed_at TIMESTAMP WITH TIME ZONE, 
    PRIMARY KEY (job_id, staff_id), 
    CONSTRAINT ck_recruiter_dates CHECK (removed_at IS NULL OR removed_at >= assigned_at), 
    FOREIGN KEY(job_id) REFERENCES job_requirements (id) ON DELETE RESTRICT, 
    FOREIGN KEY(staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT
);

CREATE INDEX ix_recruiter_active_staff ON job_recruiters (staff_id, job_id) WHERE removed_at IS NULL;

CREATE TABLE tasks (
    id UUID NOT NULL, 
    job_id UUID NOT NULL, 
    title TEXT NOT NULL, 
    note TEXT, 
    assigned_staff_id UUID NOT NULL, 
    created_by_staff_id UUID NOT NULL, 
    due_date DATE, 
    status TEXT DEFAULT 'Pending' NOT NULL, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    completed_by_staff_id UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_task_completion CHECK ((status='Done' AND completed_at IS NOT NULL AND completed_by_staff_id IS NOT NULL) OR (status<>'Done' AND completed_at IS NULL AND completed_by_staff_id IS NULL)), 
    CONSTRAINT ck_task_status CHECK (status IN ('Pending','Done','Cancelled')), 
    CONSTRAINT ck_task_title CHECK (length(btrim(title))>0), 
    FOREIGN KEY(assigned_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(completed_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(created_by_staff_id) REFERENCES staff_members (id) ON DELETE RESTRICT, 
    FOREIGN KEY(job_id) REFERENCES job_requirements (id) ON DELETE RESTRICT
);

CREATE INDEX ix_task_assignee_due ON tasks (assigned_staff_id, status, due_date);

CREATE INDEX ix_task_job ON tasks (job_id);

UPDATE alembic_version SET version_num='0002_jd_tracking' WHERE alembic_version.version_num = '0001_company_management';

COMMIT;

