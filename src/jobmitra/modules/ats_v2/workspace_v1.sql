-- Explicit additive migration; legacy identity remains the existing staff UUID.
CREATE TABLE __V12_SCHEMA__.jd_workspace_versions (
 version INTEGER PRIMARY KEY CHECK(version=1), definition_sha256 TEXT NOT NULL,
 staff_schema TEXT NOT NULL
);
ALTER TABLE __V12_SCHEMA__.job_descriptions ADD COLUMN assigned_recruiter_id UUID
 REFERENCES __STAFF_SCHEMA__.staff_members(id) ON DELETE RESTRICT;
CREATE VIEW __V12_SCHEMA__.v_employee_directory AS
 SELECT id::text AS id,display_name,is_active,email,mobile,designation,updated_at
 FROM __STAFF_SCHEMA__.staff_members;
CREATE FUNCTION __V12_SCHEMA__.check_recruiter() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' OR NEW.assigned_recruiter_id IS DISTINCT FROM OLD.assigned_recruiter_id THEN
  PERFORM pg_advisory_xact_lock(12012,11);
  IF NEW.assigned_recruiter_id IS NOT NULL THEN
   PERFORM id FROM __STAFF_SCHEMA__.staff_members WHERE id=NEW.assigned_recruiter_id AND is_active FOR SHARE;
   IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Select an existing active employee'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER workspace_recruiter_check BEFORE INSERT OR UPDATE ON __V12_SCHEMA__.job_descriptions
 FOR EACH ROW EXECUTE FUNCTION __V12_SCHEMA__.check_recruiter();
CREATE FUNCTION __V12_SCHEMA__.audit_recruiter() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE previous UUID;
BEGIN
 IF TG_OP='UPDATE' THEN previous=OLD.assigned_recruiter_id; END IF;
 IF NEW.assigned_recruiter_id IS DISTINCT FROM previous THEN
 INSERT INTO __V12_SCHEMA__.recruitment_events(job_id,event_type,payload_json)
 VALUES(NEW.id,'JD_RECRUITER_ASSIGNED',json_build_object(
 'previous_employee_id',previous,'employee_id',NEW.assigned_recruiter_id,
 'previous_employee_name',(SELECT display_name FROM __STAFF_SCHEMA__.staff_members WHERE id=previous),
 'employee_name',(SELECT display_name FROM __STAFF_SCHEMA__.staff_members WHERE id=NEW.assigned_recruiter_id),
 'attribution','Responsible recruiter assignment; no authenticated employee identity asserted')::text);
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER workspace_recruiter_audit AFTER INSERT OR UPDATE ON __V12_SCHEMA__.job_descriptions
 FOR EACH ROW EXECUTE FUNCTION __V12_SCHEMA__.audit_recruiter();
CREATE FUNCTION __V12_SCHEMA__.protect_workspace_manifest() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514',MESSAGE='Workspace schema identity is immutable'; END; $$;
CREATE TRIGGER workspace_manifest_guard BEFORE UPDATE OR DELETE OR TRUNCATE ON __V12_SCHEMA__.jd_workspace_versions
 FOR EACH STATEMENT EXECUTE FUNCTION __V12_SCHEMA__.protect_workspace_manifest();
