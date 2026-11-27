-- Explicit isolated SQLite extension, preserving canonical StaffMember UUIDs.
CREATE TABLE staff_members (
 id CHAR(32) PRIMARY KEY NOT NULL, display_name TEXT NOT NULL CHECK(length(trim(display_name))>0),
 is_active BOOLEAN NOT NULL DEFAULT 1,created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,email TEXT,mobile TEXT,designation TEXT
);
CREATE TABLE staff_change_events (
 id CHAR(32) PRIMARY KEY NOT NULL,staff_id CHAR(32) NOT NULL REFERENCES staff_members(id) ON DELETE RESTRICT,
 request_hash TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,actor_role TEXT NOT NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
);
CREATE TABLE jd_workspace_versions(version INTEGER PRIMARY KEY,definition_sha256 TEXT NOT NULL,staff_schema TEXT NOT NULL);
ALTER TABLE job_descriptions ADD COLUMN assigned_recruiter_id TEXT REFERENCES staff_members(id) ON DELETE RESTRICT;
CREATE VIEW v_employee_directory AS SELECT
 substr(id,1,8)||'-'||substr(id,9,4)||'-'||substr(id,13,4)||'-'||substr(id,17,4)||'-'||substr(id,21) AS id,
 display_name,is_active,email,mobile,designation,updated_at FROM staff_members;
CREATE TRIGGER workspace_recruiter_insert BEFORE INSERT ON job_descriptions
 WHEN NEW.assigned_recruiter_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM staff_members WHERE id=NEW.assigned_recruiter_id AND is_active=1)
 BEGIN SELECT RAISE(ABORT,'Select an existing active employee'); END;
CREATE TRIGGER workspace_recruiter_update BEFORE UPDATE OF assigned_recruiter_id ON job_descriptions
 WHEN NEW.assigned_recruiter_id IS NOT OLD.assigned_recruiter_id AND NEW.assigned_recruiter_id IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM staff_members WHERE id=NEW.assigned_recruiter_id AND is_active=1)
 BEGIN SELECT RAISE(ABORT,'Select an existing active employee'); END;
CREATE TRIGGER workspace_recruiter_audit_insert AFTER INSERT ON job_descriptions WHEN NEW.assigned_recruiter_id IS NOT NULL
 BEGIN INSERT INTO recruitment_events(job_id,event_type,payload_json) VALUES(NEW.id,'JD_RECRUITER_ASSIGNED',json_object('employee_id',NEW.assigned_recruiter_id,'employee_name',(SELECT display_name FROM staff_members WHERE id=NEW.assigned_recruiter_id))); END;
CREATE TRIGGER workspace_recruiter_audit AFTER UPDATE OF assigned_recruiter_id ON job_descriptions WHEN NEW.assigned_recruiter_id IS NOT OLD.assigned_recruiter_id
 BEGIN INSERT INTO recruitment_events(job_id,event_type,payload_json) VALUES(NEW.id,'JD_RECRUITER_ASSIGNED',json_object('previous_employee_id',OLD.assigned_recruiter_id,'employee_id',NEW.assigned_recruiter_id,'previous_employee_name',(SELECT display_name FROM staff_members WHERE id=OLD.assigned_recruiter_id),'employee_name',(SELECT display_name FROM staff_members WHERE id=NEW.assigned_recruiter_id))); END;
CREATE TRIGGER workspace_staff_no_delete BEFORE DELETE ON staff_members BEGIN SELECT RAISE(ABORT,'Deactivate employees; preserve identity and history'); END;
CREATE TRIGGER workspace_staff_history_update BEFORE UPDATE ON staff_change_events BEGIN SELECT RAISE(ABORT,'Employee history is immutable'); END;
CREATE TRIGGER workspace_staff_history_delete BEFORE DELETE ON staff_change_events BEGIN SELECT RAISE(ABORT,'Employee history is immutable'); END;
CREATE TRIGGER workspace_manifest_update BEFORE UPDATE ON jd_workspace_versions BEGIN SELECT RAISE(ABORT,'Workspace schema identity is immutable'); END;
CREATE TRIGGER workspace_manifest_delete BEFORE DELETE ON jd_workspace_versions BEGIN SELECT RAISE(ABORT,'Workspace schema identity is immutable'); END;
