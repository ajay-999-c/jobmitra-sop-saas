-- Explicit, transactional ATS V2 -> V3 upgrade. Never run at application startup.
-- The eight canonical tables and every existing row remain in place.
ALTER TABLE jd_candidates ADD COLUMN selection_outcome TEXT CHECK(selection_outcome IS NULL OR selection_outcome IN ('PENDING_JOINING','JOINED_CONFIRMED','NOT_JOINED','SELECTION_CANCELLED'));
ALTER TABLE jd_candidates ADD COLUMN selected_on TEXT;
ALTER TABLE jd_candidates ADD COLUMN selected_at_utc TEXT;
ALTER TABLE jd_candidates ADD COLUMN joined_on TEXT;
ALTER TABLE jd_candidates ADD COLUMN joining_confirmed_at_utc TEXT;
ALTER TABLE jd_candidates ADD COLUMN outcome_closed_on TEXT;
ALTER TABLE jd_candidates ADD COLUMN outcome_reason TEXT;
ALTER TABLE jd_candidates ADD COLUMN eligibility_released_at_utc TEXT;
ALTER TABLE jd_candidates ADD COLUMN eligibility_release_reason TEXT;
ALTER TABLE jd_candidates ADD COLUMN confirmation_evidence TEXT;
ALTER TABLE jd_candidates ADD COLUMN action_actor_name TEXT;
ALTER TABLE jd_candidates ADD COLUMN action_actor_role TEXT;
ALTER TABLE jd_candidates ADD COLUMN action_request_key TEXT;
ALTER TABLE jd_candidates ADD COLUMN action_request_fingerprint TEXT;

ALTER TABLE job_descriptions ADD COLUMN company_contact_id TEXT;
ALTER TABLE job_descriptions ADD COLUMN company_contact_name_snapshot TEXT;
ALTER TABLE job_descriptions ADD COLUMN company_contact_email_snapshot TEXT;
ALTER TABLE job_descriptions ADD COLUMN contact_request_key TEXT;
ALTER TABLE job_descriptions ADD COLUMN contact_request_fingerprint TEXT;
ALTER TABLE job_descriptions ADD COLUMN contact_actor_name TEXT;
ALTER TABLE job_descriptions ADD COLUMN contact_actor_role TEXT;
ALTER TABLE companies ADD COLUMN audit_request_key TEXT;
ALTER TABLE companies ADD COLUMN audit_request_fingerprint TEXT;
ALTER TABLE companies ADD COLUMN audit_actor_name TEXT;
ALTER TABLE companies ADD COLUMN audit_actor_role TEXT;

CREATE TABLE company_audit_events (
    id INTEGER PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
    action TEXT NOT NULL,
    before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
    after_json TEXT CHECK(after_json IS NULL OR json_valid(after_json)),
    actor_staff_id TEXT,
    actor_name_snapshot TEXT,
    actor_verification_status TEXT,
    source_system TEXT,
    source_event_id TEXT,
    request_fingerprint TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source_system,source_event_id)
);
CREATE INDEX idx_company_audit_time ON company_audit_events(company_id,created_at DESC,id DESC);
CREATE INDEX idx_selection_date ON jd_candidates(selected_on,job_id);
CREATE INDEX idx_confirmed_joining_date ON jd_candidates(joined_on,job_id) WHERE selection_outcome='JOINED_CONFIRMED';
CREATE UNIQUE INDEX uq_v12_event_request ON recruitment_events(json_extract(payload_json,'$.idempotency_key')) WHERE json_extract(payload_json,'$.idempotency_key') IS NOT NULL;

CREATE TRIGGER trg_company_audit_no_update BEFORE UPDATE ON company_audit_events
BEGIN SELECT RAISE(ABORT,'Company audit events are append-only'); END;
CREATE TRIGGER trg_company_audit_no_delete BEFORE DELETE ON company_audit_events
BEGIN SELECT RAISE(ABORT,'Company audit events cannot be deleted'); END;
CREATE TRIGGER trg_company_v3_created AFTER INSERT ON companies
BEGIN
 INSERT INTO company_audit_events(company_id,action,after_json,actor_name_snapshot,actor_verification_status,source_system,source_event_id,request_fingerprint)
 VALUES(NEW.id,CASE WHEN NEW.legacy_postgres_id IS NULL THEN 'COMPANY_CREATED' ELSE 'COMPANY_IMPORTED' END,
 json_object('company_name',NEW.company_name,'general_phone_numbers',json(NEW.general_phone_numbers_json),'contacts',json(NEW.contacts_json),'address_line',NEW.address_line,'city',NEW.city,'state',NEW.state,'postal_code',NEW.postal_code,'is_active',NEW.is_active),NEW.audit_actor_name,NEW.audit_actor_role,'v12',NEW.audit_request_key,NEW.audit_request_fingerprint);
END;
CREATE TRIGGER trg_company_v3_updated AFTER UPDATE ON companies
WHEN OLD.company_name IS NOT NEW.company_name OR OLD.general_phone_numbers_json IS NOT NEW.general_phone_numbers_json
 OR OLD.contacts_json IS NOT NEW.contacts_json OR OLD.address_line IS NOT NEW.address_line OR OLD.city IS NOT NEW.city
 OR OLD.state IS NOT NEW.state OR OLD.postal_code IS NOT NEW.postal_code OR OLD.is_active IS NOT NEW.is_active
 OR OLD.audit_request_key IS NOT NEW.audit_request_key
BEGIN
 INSERT INTO company_audit_events(company_id,action,before_json,after_json,actor_name_snapshot,actor_verification_status,source_system,source_event_id,request_fingerprint)
 VALUES(NEW.id,'COMPANY_UPDATED',
 json_object('company_name',OLD.company_name,'general_phone_numbers',json(OLD.general_phone_numbers_json),'contacts',json(OLD.contacts_json),'address_line',OLD.address_line,'city',OLD.city,'state',OLD.state,'postal_code',OLD.postal_code,'is_active',OLD.is_active),
 json_object('company_name',NEW.company_name,'general_phone_numbers',json(NEW.general_phone_numbers_json),'contacts',json(NEW.contacts_json),'address_line',NEW.address_line,'city',NEW.city,'state',NEW.state,'postal_code',NEW.postal_code,'is_active',NEW.is_active),
 NEW.audit_actor_name,NEW.audit_actor_role,'v12',NEW.audit_request_key,NEW.audit_request_fingerprint);
END;

CREATE VIEW v_candidate_allocation_eligibility AS
SELECT c.id AS candidate_id,
 CASE
 WHEN EXISTS(SELECT 1 FROM jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='JOINED' AND l.eligibility_released_at_utc IS NULL) THEN 'PLACED_LOCKED'
 WHEN EXISTS(SELECT 1 FROM jd_candidates l WHERE l.candidate_id=c.id AND l.stage_code='SELECTED' AND (l.selection_outcome IS NULL OR l.selection_outcome='PENDING_JOINING')) THEN 'SELECTED_ON_HOLD'
 WHEN EXISTS(SELECT 1 FROM jd_candidates l WHERE l.candidate_id=c.id AND l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED','JOINED_CONFIRMED')) THEN 'AVAILABLE_AGAIN'
 ELSE 'AVAILABLE' END AS allocation_eligibility
FROM candidates c;

CREATE TRIGGER trg_v3_pool_eligibility BEFORE INSERT ON jd_candidates
WHEN EXISTS(SELECT 1 FROM v_candidate_allocation_eligibility e WHERE e.candidate_id=NEW.candidate_id AND e.allocation_eligibility IN ('PLACED_LOCKED','SELECTED_ON_HOLD'))
BEGIN SELECT RAISE(ABORT,'Candidate has an unresolved global selection or joining lock'); END;

CREATE TRIGGER trg_v3_outcome_valid BEFORE UPDATE ON jd_candidates
BEGIN
 SELECT CASE WHEN (NEW.selected_on IS NOT NULL AND (date(NEW.selected_on,'+0 days') IS NOT NEW.selected_on OR NEW.selected_on>date('now','+330 minutes')))
 OR (NEW.joined_on IS NOT NULL AND (date(NEW.joined_on,'+0 days') IS NOT NEW.joined_on OR NEW.joined_on<NEW.selected_on OR NEW.joined_on>date('now','+330 minutes')))
 OR (NEW.outcome_closed_on IS NOT NULL AND (date(NEW.outcome_closed_on,'+0 days') IS NOT NEW.outcome_closed_on OR NEW.outcome_closed_on<NEW.selected_on OR NEW.outcome_closed_on>date('now','+330 minutes')))
 THEN RAISE(ABORT,'Outcome dates must be valid, ordered and not in the future') END;
 SELECT CASE WHEN NEW.selection_outcome IS NULL AND NEW.stage_code IN ('SELECTED','JOINED') AND NEW.stage_code<>OLD.stage_code
 THEN RAISE(ABORT,'Record explicit selection or confirmed joining facts') END;
 SELECT CASE WHEN NEW.selection_outcome IS NOT NULL AND
   (NEW.selected_on IS NULL OR NEW.selected_at_utc IS NULL OR length(trim(COALESCE(NEW.action_actor_name,'')))=0)
 THEN RAISE(ABORT,'Selection requires its effective date, recorded time and actor') END;
 SELECT CASE WHEN NEW.selection_outcome IN ('PENDING_JOINING','NOT_JOINED','SELECTION_CANCELLED') AND NEW.stage_code<>'SELECTED'
 THEN RAISE(ABORT,'Selection outcome must retain the SELECTED milestone') END;
 SELECT CASE WHEN NEW.selection_outcome='JOINED_CONFIRMED' AND
   (NEW.stage_code<>'JOINED' OR NEW.joined_on IS NULL OR NEW.joining_confirmed_at_utc IS NULL OR length(trim(COALESCE(NEW.confirmation_evidence,'')))=0)
 THEN RAISE(ABORT,'Joining requires actual date and explicit confirmation evidence') END;
 SELECT CASE WHEN NEW.selection_outcome<>'JOINED_CONFIRMED' AND (NEW.joined_on IS NOT NULL OR NEW.joining_confirmed_at_utc IS NOT NULL)
 THEN RAISE(ABORT,'A joining date is not a confirmed placement by itself') END;
 SELECT CASE WHEN NEW.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') AND
   (NEW.outcome_closed_on IS NULL OR length(trim(COALESCE(NEW.outcome_reason,'')))=0)
 THEN RAISE(ABORT,'Selection closure requires date and reason') END;
 SELECT CASE WHEN NEW.eligibility_released_at_utc IS NOT NULL AND
   (NEW.selection_outcome IS NOT 'JOINED_CONFIRMED' OR length(trim(COALESCE(NEW.eligibility_release_reason,'')))=0 OR NEW.action_actor_role IS NOT 'SUPERVISOR_TOKEN')
 THEN RAISE(ABORT,'Reactivation requires supervisor authorization and reason') END;
 SELECT CASE WHEN OLD.eligibility_released_at_utc IS NOT NULL AND
   (NEW.eligibility_released_at_utc IS NOT OLD.eligibility_released_at_utc OR NEW.eligibility_release_reason IS NOT OLD.eligibility_release_reason)
 THEN RAISE(ABORT,'Recorded reactivation evidence is immutable') END;
 SELECT CASE WHEN OLD.selected_on IS NOT NULL AND (NEW.selected_on IS NOT OLD.selected_on OR NEW.selected_at_utc IS NOT OLD.selected_at_utc)
 THEN RAISE(ABORT,'Historical selection dates are immutable') END;
 SELECT CASE WHEN OLD.joined_on IS NOT NULL AND (NEW.joined_on IS NOT OLD.joined_on OR NEW.joining_confirmed_at_utc IS NOT OLD.joining_confirmed_at_utc)
 THEN RAISE(ABORT,'Historical joining dates are immutable') END;
 SELECT CASE WHEN OLD.confirmation_evidence IS NOT NULL AND NEW.confirmation_evidence IS NOT OLD.confirmation_evidence
 THEN RAISE(ABORT,'Historical joining evidence is immutable') END;
 SELECT CASE WHEN OLD.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') AND
   (NEW.selection_outcome IS NOT OLD.selection_outcome OR NEW.outcome_closed_on IS NOT OLD.outcome_closed_on OR NEW.outcome_reason IS NOT OLD.outcome_reason)
 THEN RAISE(ABORT,'Closed selections retain their original outcome') END;
END;

CREATE TRIGGER trg_v3_selection_exclusivity BEFORE UPDATE OF stage_code,selection_outcome ON jd_candidates
WHEN (NEW.stage_code='JOINED' AND NEW.eligibility_released_at_utc IS NULL)
 OR (NEW.stage_code='SELECTED' AND (NEW.selection_outcome IS NULL OR NEW.selection_outcome='PENDING_JOINING'))
BEGIN
 SELECT CASE WHEN EXISTS(SELECT 1 FROM jd_candidates l WHERE l.candidate_id=NEW.candidate_id AND l.id<>NEW.id AND
   ((l.stage_code='JOINED' AND l.eligibility_released_at_utc IS NULL) OR (l.stage_code='SELECTED' AND (l.selection_outcome IS NULL OR l.selection_outcome='PENDING_JOINING'))))
 THEN RAISE(ABORT,'Candidate is already selected or joined in another JD') END;
END;

CREATE TRIGGER trg_v3_placement_company_immutable BEFORE UPDATE OF company_id ON job_descriptions
WHEN OLD.company_id<>NEW.company_id AND EXISTS(SELECT 1 FROM jd_candidates WHERE job_id=OLD.id AND stage_code IN ('SELECTED','JOINED'))
BEGIN SELECT RAISE(ABORT,'A JD with historical selections must retain its company'); END;
CREATE TRIGGER trg_v3_jd_contact_insert BEFORE INSERT ON job_descriptions
WHEN NEW.company_contact_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM companies c,json_each(c.contacts_json) x WHERE c.id=NEW.company_id AND json_extract(x.value,'$.id')=NEW.company_contact_id)
BEGIN SELECT RAISE(ABORT,'Selected contact does not belong to this company'); END;
CREATE TRIGGER trg_v3_jd_contact_update BEFORE UPDATE OF company_id,company_contact_id ON job_descriptions
WHEN NEW.company_contact_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM companies c,json_each(c.contacts_json) x WHERE c.id=NEW.company_id AND json_extract(x.value,'$.id')=NEW.company_contact_id)
BEGIN SELECT RAISE(ABORT,'Selected contact does not belong to this company'); END;
CREATE TRIGGER trg_v3_contact_audit AFTER UPDATE OF company_contact_id,company_contact_email_snapshot,company_contact_name_snapshot,contact_request_key ON job_descriptions
WHEN OLD.company_contact_id IS NOT NEW.company_contact_id OR OLD.company_contact_email_snapshot IS NOT NEW.company_contact_email_snapshot
 OR OLD.company_contact_name_snapshot IS NOT NEW.company_contact_name_snapshot OR OLD.contact_request_key IS NOT NEW.contact_request_key
BEGIN
 INSERT INTO recruitment_events(job_id,event_type,before_json,after_json,payload_json)
 VALUES(NEW.id,'JD_CONTACT_SELECTED',
 json_object('company_contact_id',OLD.company_contact_id,'name',OLD.company_contact_name_snapshot,'email',OLD.company_contact_email_snapshot),
 json_object('company_contact_id',NEW.company_contact_id,'name',NEW.company_contact_name_snapshot,'email',NEW.company_contact_email_snapshot),
 json_object('idempotency_key',NEW.contact_request_key,'request_fingerprint',NEW.contact_request_fingerprint,'actor_name',NEW.contact_actor_name,'actor_verification_status',NEW.contact_actor_role));
END;

DROP TRIGGER trg_pool_moved;
CREATE TRIGGER trg_pool_moved AFTER UPDATE OF stage_code,round_id ON jd_candidates
WHEN OLD.stage_code<>NEW.stage_code OR COALESCE(OLD.round_id,'')<>COALESCE(NEW.round_id,'')
BEGIN
 INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,from_stage,to_stage,from_label_snapshot,to_label_snapshot,workflow_version,before_json,after_json,feedback,payload_json)
 VALUES(NEW.job_id,NEW.candidate_id,NEW.id,
 CASE WHEN NEW.selection_outcome='JOINED_CONFIRMED' THEN 'JOINING_CONFIRMED' WHEN NEW.selection_outcome='PENDING_JOINING' THEN 'COMPANY_SELECTED' WHEN NEW.stage_code='NOT_SELECTED' THEN 'REJECTED' ELSE 'MOVED' END,
 OLD.stage_code,NEW.stage_code,
 CASE WHEN OLD.stage_code='ROUND' THEN COALESCE((SELECT round_name FROM jd_interview_rounds WHERE id=OLD.round_id),'Interview Round') ELSE OLD.stage_code END,
 CASE WHEN NEW.stage_code='ROUND' THEN COALESCE((SELECT round_name FROM jd_interview_rounds WHERE id=NEW.round_id),'Interview Round') ELSE NEW.stage_code END,
 (SELECT workflow_version FROM job_descriptions WHERE id=NEW.job_id),
 json_object('stage_code',OLD.stage_code,'round_id',OLD.round_id,'selection_outcome',OLD.selection_outcome,'selected_on',OLD.selected_on,'joined_on',OLD.joined_on,'stage_note',OLD.stage_note),
 json_object('stage_code',NEW.stage_code,'round_id',NEW.round_id,'selection_outcome',NEW.selection_outcome,'selected_on',NEW.selected_on,'selected_at_utc',NEW.selected_at_utc,'joined_on',NEW.joined_on,'joining_confirmed_at_utc',NEW.joining_confirmed_at_utc,'confirmation_evidence',NEW.confirmation_evidence,'stage_note',NEW.stage_note,'rejected_from_stage',NEW.rejected_from_stage,'rejected_round_name',NEW.rejected_round_name,'rejected_round_index',NEW.rejected_round_index,'rejected_at',NEW.rejected_at),
 NEW.stage_note,
 json_object('entity','jd_candidate','from_round_id',OLD.round_id,'to_round_id',NEW.round_id,'idempotency_key',NEW.action_request_key,'request_fingerprint',NEW.action_request_fingerprint,'actor_name',NEW.action_actor_name,'actor_verification_status',NEW.action_actor_role));
 UPDATE jd_candidates SET stage_updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
END;

CREATE TRIGGER trg_v3_outcome_audit AFTER UPDATE OF selection_outcome,eligibility_released_at_utc ON jd_candidates
WHEN OLD.stage_code=NEW.stage_code AND (OLD.selection_outcome IS NOT NEW.selection_outcome OR OLD.eligibility_released_at_utc IS NOT NEW.eligibility_released_at_utc)
BEGIN
 INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,from_stage,to_stage,before_json,after_json,payload_json)
 VALUES(NEW.job_id,NEW.candidate_id,NEW.id,
 CASE WHEN NEW.eligibility_released_at_utc IS NOT NULL THEN 'SOURCING_REACTIVATED' ELSE NEW.selection_outcome END,
 OLD.stage_code,NEW.stage_code,
 json_object('selection_outcome',OLD.selection_outcome,'eligibility_released_at_utc',OLD.eligibility_released_at_utc),
 json_object('selection_outcome',NEW.selection_outcome,'outcome_closed_on',NEW.outcome_closed_on,'outcome_reason',NEW.outcome_reason,'eligibility_released_at_utc',NEW.eligibility_released_at_utc,'eligibility_release_reason',NEW.eligibility_release_reason),
 json_object('entity','jd_candidate','idempotency_key',NEW.action_request_key,'request_fingerprint',NEW.action_request_fingerprint,'actor_name',NEW.action_actor_name,'actor_verification_status',NEW.action_actor_role));
END;

CREATE VIEW v_company_placement_register AS
SELECT l.id AS jd_candidate_id,j.company_id,j.id AS job_id,j.jd_code,j.title AS job_title,
 c.id AS candidate_id,c.full_name,l.stage_code,l.selection_outcome,l.selected_on,l.joined_on,
 l.joining_confirmed_at_utc,l.outcome_closed_on,l.outcome_reason,l.eligibility_released_at_utc,
 CASE WHEN l.selection_outcome IS NOT NULL THEN l.selection_outcome WHEN l.stage_code='JOINED' THEN 'JOINED_UNVERIFIED' ELSE 'SELECTED_UNVERIFIED' END AS effective_status,
 e.allocation_eligibility
FROM jd_candidates l JOIN job_descriptions j ON j.id=l.job_id JOIN candidates c ON c.id=l.candidate_id
JOIN v_candidate_allocation_eligibility e ON e.candidate_id=c.id
WHERE l.stage_code IN ('SELECTED','JOINED');

DROP VIEW v_jd_stage_counts;
CREATE VIEW v_jd_stage_counts AS
SELECT job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END AS stage_code,
COALESCE(round_id,'') AS round_key,COUNT(*) AS candidate_count
FROM jd_candidates GROUP BY job_id,CASE WHEN selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN selection_outcome ELSE stage_code END,COALESCE(round_id,'');
DROP VIEW v_candidate_jd_history;
CREATE VIEW v_candidate_jd_history AS
SELECT l.id AS jd_candidate_id,l.candidate_id,c.full_name,j.id AS job_id,j.jd_code,j.title AS job_title,
l.stage_code,l.round_id,l.added_at,l.rejected_from_stage,l.rejected_round_name,l.rejected_round_index,l.rejected_at,
l.selection_outcome,l.selected_on,l.joined_on,l.joining_confirmed_at_utc,
CASE WHEN l.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') THEN l.selection_outcome ELSE l.stage_code END AS effective_status
FROM jd_candidates l JOIN candidates c ON c.id=l.candidate_id JOIN job_descriptions j ON j.id=l.job_id;

DROP VIEW v_jd_dashboard;
CREATE VIEW v_jd_dashboard AS
WITH joined AS (SELECT job_id,count(*) joined_count FROM jd_candidates WHERE selection_outcome='JOINED_CONFIRMED' AND joined_on IS NOT NULL AND joining_confirmed_at_utc IS NOT NULL GROUP BY job_id),
 amounts AS (SELECT j.id,j.jd_code,j.company_id,j.title,j.status,j.created_at,j.target_date,j.vacancies,COALESCE(x.joined_count,0) joined_count FROM job_descriptions j LEFT JOIN joined x ON x.job_id=j.id)
SELECT a.*,CASE WHEN status='CLOSED' THEN 'CLOSED' WHEN vacancies IS NOT NULL AND joined_count>=vacancies THEN 'FILLED' WHEN status<>'ACTIVE' OR target_date IS NULL THEN 'UNSET' WHEN target_date<date('now','+330 minutes') THEN 'OVERDUE' WHEN target_date<=date('now','+330 minutes','+2 days') THEN 'DUE' ELSE 'TRACK' END AS target_state,
CAST(julianday(target_date)-julianday(date('now','+330 minutes')) AS INTEGER) AS days_remaining FROM amounts a;
PRAGMA user_version=3;
