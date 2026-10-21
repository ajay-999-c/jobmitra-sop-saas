BEGIN;

-- Running upgrade 0002_jd_tracking -> 0003_jd_work_focus

ALTER TABLE job_requirements ADD COLUMN current_work_focus TEXT;

ALTER TABLE job_requirements ADD CONSTRAINT ck_job_work_focus CHECK (current_work_focus IN ('CANDIDATE_POOL','CANDIDATE_CONTACT','JOBMITRA_SCREENING','COMPANY_SUBMISSION','INTERVIEWS','SELECTION','JOINING'));

UPDATE alembic_version SET version_num='0003_jd_work_focus' WHERE alembic_version.version_num = '0002_jd_tracking';

COMMIT;

