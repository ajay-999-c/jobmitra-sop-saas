-- Consolidated, responsibility-based equivalents of the 58 audited SQLite triggers.
-- All references resolve inside the explicitly provisioned development schema.
CREATE FUNCTION __V12_SCHEMA__.fail(message TEXT) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE=message; END; $$;

CREATE FUNCTION __V12_SCHEMA__.now_text() RETURNS TEXT
LANGUAGE SQL VOLATILE SET search_path=pg_catalog AS $$
SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'); $$;

CREATE FUNCTION __V12_SCHEMA__.row_fields(value JSONB, fields TEXT[]) RETURNS JSONB
LANGUAGE SQL IMMUTABLE SET search_path=pg_catalog AS $$
SELECT coalesce(jsonb_object_agg(k, CASE WHEN right(k,5)='_json'
 THEN (value->>k)::jsonb ELSE value->k END),'{}'::jsonb) FROM unnest(fields) k; $$;

CREATE FUNCTION __V12_SCHEMA__.changed_fields(before_row JSONB, after_row JSONB, fields TEXT[], old_values BOOLEAN)
RETURNS JSONB LANGUAGE SQL IMMUTABLE SET search_path=pg_catalog AS $$
SELECT coalesce(jsonb_object_agg(k, CASE WHEN right(k,5)='_json'
 THEN (CASE WHEN old_values THEN before_row ELSE after_row END->>k)::jsonb
 ELSE CASE WHEN old_values THEN before_row ELSE after_row END->k END),'{}'::jsonb)
FROM unnest(fields) k WHERE before_row->k IS DISTINCT FROM after_row->k; $$;

CREATE FUNCTION __V12_SCHEMA__.guard_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE old_row JSONB; new_row JSONB; candidate BIGINT; job BIGINT; today TEXT;
 current_status TEXT; field TEXT; immutable TEXT[];
BEGIN
 PERFORM pg_advisory_xact_lock(hashtext(TG_TABLE_SCHEMA),12012);
 IF TG_OP='TRUNCATE' OR (TG_TABLE_NAME IN ('recruitment_events','company_audit_events',
 'candidate_profile_versions','company_proposals','company_proposal_signed_documents',
 'company_proposal_status_events','backend_versions','development_source_records')
 AND TG_OP IN ('UPDATE','DELETE')) THEN
 PERFORM __V12_SCHEMA__.fail('Historical evidence and schema identity are append-only'); END IF;
 IF TG_OP='DELETE' THEN
 PERFORM __V12_SCHEMA__.fail('Historical entities must be deactivated or retired, not deleted');
 END IF;
 IF TG_OP='UPDATE' THEN old_row=to_jsonb(OLD); END IF;
 new_row=to_jsonb(NEW);
 IF TG_OP='UPDATE' THEN
 immutable=CASE TG_TABLE_NAME
 WHEN 'candidates' THEN ARRAY['id','created_at','legacy_postgres_id']
 WHEN 'companies' THEN ARRAY['id']
 WHEN 'job_descriptions' THEN ARRAY['id','jd_code','created_at','is_legacy_import']
 WHEN 'jd_candidates' THEN ARRAY['job_id','candidate_id']
 WHEN 'jd_interview_rounds' THEN ARRAY['id','job_id','created_at']
 WHEN 'candidate_activities' THEN ARRAY['id','candidate_id','created_at']
 WHEN 'candidate_resumes' THEN ARRAY['id','candidate_id','source_type','resume_kind',
 'original_filename','storage_path','raw_text','parsed_json','created_at',
 'legacy_source_table','legacy_postgres_id','source_json','imported_at']
 ELSE ARRAY[]::text[] END;
 FOREACH field IN ARRAY immutable LOOP
 IF old_row->field IS DISTINCT FROM new_row->field THEN
 PERFORM __V12_SCHEMA__.fail('Entity identity, original provenance and retained evidence are immutable');
 END IF; END LOOP;
 END IF;

 IF TG_TABLE_NAME='job_descriptions' THEN
 IF (TG_OP='INSERT' OR NEW.company_id IS DISTINCT FROM OLD.company_id) AND NOT EXISTS(
 SELECT 1 FROM __V12_SCHEMA__.companies WHERE id=NEW.company_id AND is_active=1) THEN
 PERFORM __V12_SCHEMA__.fail('Select an existing active ATS company'); END IF;
 IF NEW.company_contact_id IS NOT NULL AND NOT EXISTS(SELECT 1
 FROM __V12_SCHEMA__.companies c, json_array_elements(c.contacts_json::json) x
 WHERE c.id=NEW.company_id AND x->>'id'=NEW.company_contact_id) THEN
 PERFORM __V12_SCHEMA__.fail('Selected contact does not belong to this company'); END IF;
 IF TG_OP='UPDATE' THEN
 IF NEW.workflow_version<OLD.workflow_version THEN
 PERFORM __V12_SCHEMA__.fail('JD workflow version cannot decrease'); END IF;
 IF NEW.company_id<>OLD.company_id AND EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_candidates
 WHERE job_id=OLD.id AND stage_code IN ('SELECTED','JOINED')) THEN
 PERFORM __V12_SCHEMA__.fail('A JD with historical selections must retain its company'); END IF;
 IF old_row IS DISTINCT FROM new_row THEN NEW.updated_at=__V12_SCHEMA__.now_text(); END IF;
 END IF;
 ELSIF TG_TABLE_NAME='candidates' AND TG_OP='UPDATE' THEN
 IF old_row IS DISTINCT FROM new_row THEN NEW.updated_at=__V12_SCHEMA__.now_text(); END IF;
 ELSIF TG_TABLE_NAME='jd_interview_rounds' THEN
 PERFORM 1 FROM __V12_SCHEMA__.job_descriptions WHERE id=NEW.job_id FOR UPDATE;
 IF TG_OP='UPDATE' AND OLD.is_active=1 AND NEW.is_active=0 AND EXISTS(
 SELECT 1 FROM __V12_SCHEMA__.jd_candidates WHERE round_id=OLD.id AND stage_code='ROUND') THEN
 PERFORM __V12_SCHEMA__.fail('Move candidate out of this round before retirement'); END IF;
 ELSIF TG_TABLE_NAME='jd_candidates' THEN
 -- One candidate row serializes global eligibility across different JDs.
 PERFORM 1 FROM __V12_SCHEMA__.candidates WHERE id=NEW.candidate_id FOR UPDATE;
 PERFORM 1 FROM __V12_SCHEMA__.job_descriptions WHERE id=NEW.job_id FOR UPDATE;
 IF TG_OP='INSERT' THEN
 IF (SELECT status FROM __V12_SCHEMA__.job_descriptions WHERE id=NEW.job_id)<>'ACTIVE'
 OR NEW.stage_code<>'POOL' OR NEW.round_id IS NOT NULL THEN
 PERFORM __V12_SCHEMA__.fail('Only ACTIVE JDs accept new Candidate Pool links'); END IF;
 IF EXISTS(SELECT 1 FROM __V12_SCHEMA__.v_candidate_allocation_eligibility
 WHERE candidate_id=NEW.candidate_id AND allocation_eligibility IN ('PLACED_LOCKED','SELECTED_ON_HOLD')) THEN
 PERFORM __V12_SCHEMA__.fail('Candidate has an unresolved global selection or joining lock'); END IF;
 ELSE
 IF OLD.stage_code='NOT_SELECTED' AND (OLD.rejected_from_stage,OLD.rejected_round_name,
 OLD.rejected_round_index,OLD.rejected_at) IS DISTINCT FROM (NEW.rejected_from_stage,
 NEW.rejected_round_name,NEW.rejected_round_index,NEW.rejected_at) THEN
 PERFORM __V12_SCHEMA__.fail('Rejected-stage snapshot cannot be edited after rejection'); END IF;
 IF (OLD.stage_code,OLD.round_id) IS DISTINCT FROM (NEW.stage_code,NEW.round_id) THEN
 IF OLD.stage_code IN ('JOINED','NOT_SELECTED') OR (OLD.stage_code='SELECTED' AND NEW.stage_code<>'JOINED') THEN
 PERFORM __V12_SCHEMA__.fail('Terminal candidate outcomes cannot be changed'); END IF;
 IF NEW.stage_code='NOT_SELECTED' AND (NEW.rejected_from_stage IS NULL OR NEW.rejected_at IS NULL) THEN
 PERFORM __V12_SCHEMA__.fail('Store rejection-stage snapshot before marking Not Selected'); END IF;
 NEW.stage_updated_at=__V12_SCHEMA__.now_text();
 END IF;
 today=(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date::text;
 IF (NEW.selected_on IS NOT NULL AND (NOT __V12_SCHEMA__.valid_date(NEW.selected_on) OR NEW.selected_on>today))
 OR (NEW.joined_on IS NOT NULL AND (NOT __V12_SCHEMA__.valid_date(NEW.joined_on) OR NEW.joined_on<NEW.selected_on OR NEW.joined_on>today))
 OR (NEW.outcome_closed_on IS NOT NULL AND (NOT __V12_SCHEMA__.valid_date(NEW.outcome_closed_on) OR NEW.outcome_closed_on<NEW.selected_on OR NEW.outcome_closed_on>today)) THEN
 PERFORM __V12_SCHEMA__.fail('Outcome dates must be valid, ordered and not in the future'); END IF;
 IF NEW.selection_outcome IS NULL AND NEW.stage_code IN ('SELECTED','JOINED') AND NEW.stage_code<>OLD.stage_code THEN
 PERFORM __V12_SCHEMA__.fail('Record explicit selection or confirmed joining facts'); END IF;
 IF NEW.selection_outcome IS NOT NULL AND (NEW.selected_on IS NULL OR NEW.selected_at_utc IS NULL
 OR length(trim(coalesce(NEW.action_actor_name,'')))=0) THEN
 PERFORM __V12_SCHEMA__.fail('Selection requires effective date, recorded time and actor'); END IF;
 IF NEW.selection_outcome IN ('PENDING_JOINING','NOT_JOINED','SELECTION_CANCELLED') AND NEW.stage_code<>'SELECTED' THEN
 PERFORM __V12_SCHEMA__.fail('Selection outcome must retain the SELECTED milestone'); END IF;
 IF NEW.selection_outcome='JOINED_CONFIRMED' AND (NEW.stage_code<>'JOINED' OR NEW.joined_on IS NULL
 OR NEW.joining_confirmed_at_utc IS NULL OR length(trim(coalesce(NEW.confirmation_evidence,'')))=0) THEN
 PERFORM __V12_SCHEMA__.fail('Joining requires actual date and explicit confirmation evidence'); END IF;
 IF NEW.selection_outcome<>'JOINED_CONFIRMED' AND (NEW.joined_on IS NOT NULL OR NEW.joining_confirmed_at_utc IS NOT NULL) THEN
 PERFORM __V12_SCHEMA__.fail('A joining date is not a confirmed placement by itself'); END IF;
 IF NEW.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') AND (NEW.outcome_closed_on IS NULL
 OR length(trim(coalesce(NEW.outcome_reason,'')))=0) THEN
 PERFORM __V12_SCHEMA__.fail('Selection closure requires date and reason'); END IF;
 IF NEW.eligibility_released_at_utc IS NOT NULL AND (NEW.selection_outcome IS DISTINCT FROM 'JOINED_CONFIRMED'
 OR length(trim(coalesce(NEW.eligibility_release_reason,'')))=0 OR NEW.action_actor_role IS DISTINCT FROM 'SUPERVISOR_TOKEN') THEN
 PERFORM __V12_SCHEMA__.fail('Reactivation requires supervisor authorization and reason'); END IF;
 IF OLD.eligibility_released_at_utc IS NOT NULL AND (NEW.eligibility_released_at_utc,NEW.eligibility_release_reason)
 IS DISTINCT FROM (OLD.eligibility_released_at_utc,OLD.eligibility_release_reason) THEN
 PERFORM __V12_SCHEMA__.fail('Recorded reactivation evidence is immutable'); END IF;
 IF OLD.selected_on IS NOT NULL AND (NEW.selected_on,NEW.selected_at_utc) IS DISTINCT FROM (OLD.selected_on,OLD.selected_at_utc) THEN
 PERFORM __V12_SCHEMA__.fail('Historical selection dates are immutable'); END IF;
 IF OLD.joined_on IS NOT NULL AND (NEW.joined_on,NEW.joining_confirmed_at_utc) IS DISTINCT FROM (OLD.joined_on,OLD.joining_confirmed_at_utc) THEN
 PERFORM __V12_SCHEMA__.fail('Historical joining dates are immutable'); END IF;
 IF OLD.confirmation_evidence IS NOT NULL AND NEW.confirmation_evidence IS DISTINCT FROM OLD.confirmation_evidence THEN
 PERFORM __V12_SCHEMA__.fail('Historical joining evidence is immutable'); END IF;
 IF OLD.selection_outcome IN ('NOT_JOINED','SELECTION_CANCELLED') AND
 (NEW.selection_outcome,NEW.outcome_closed_on,NEW.outcome_reason) IS DISTINCT FROM
 (OLD.selection_outcome,OLD.outcome_closed_on,OLD.outcome_reason) THEN
 PERFORM __V12_SCHEMA__.fail('Closed selections retain their original outcome'); END IF;
 END IF;
 IF NEW.stage_code='ROUND' AND NOT EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_interview_rounds
 WHERE id=NEW.round_id AND job_id=NEW.job_id AND is_active=1) THEN
 PERFORM __V12_SCHEMA__.fail('Round is missing, inactive, or belongs to another JD'); END IF;
 ELSIF TG_TABLE_NAME='recruitment_events' THEN
 IF NEW.job_id IS NULL AND NEW.candidate_id IS NULL THEN
 PERFORM __V12_SCHEMA__.fail('Audit event requires job_id or candidate_id'); END IF;
 IF NEW.jd_candidate_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM __V12_SCHEMA__.jd_candidates jc
 WHERE jc.id=NEW.jd_candidate_id AND jc.job_id=NEW.job_id
 AND (NEW.candidate_id IS NULL OR jc.candidate_id=NEW.candidate_id)) THEN
 PERFORM __V12_SCHEMA__.fail('JD candidate event must match linked job and candidate'); END IF;
 ELSIF TG_TABLE_NAME='company_proposal_status_events' THEN
 PERFORM 1 FROM __V12_SCHEMA__.company_proposals WHERE id=NEW.proposal_id FOR UPDATE;
 SELECT status INTO current_status FROM __V12_SCHEMA__.company_proposal_status_events
 WHERE proposal_id=NEW.proposal_id ORDER BY _record_order DESC LIMIT 1;
 IF current_status IN ('ACCEPTED','DECLINED') OR current_status=NEW.status THEN
 PERFORM __V12_SCHEMA__.fail('Closed/duplicate proposal statuses require a new proposal version'); END IF;
 IF NOT __V12_SCHEMA__.valid_date(NEW.effective_date)
 OR NEW.effective_date<(SELECT issue_date FROM __V12_SCHEMA__.company_proposals WHERE id=NEW.proposal_id)
 OR NEW.effective_date>(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date::text THEN
 PERFORM __V12_SCHEMA__.fail('Invalid proposal evidence date'); END IF;
 IF NEW.status='ACCEPTED' AND (length(trim(coalesce(NEW.authorized_signatory,'')))=0
 OR NOT EXISTS(SELECT 1 FROM __V12_SCHEMA__.company_proposal_signed_documents
 WHERE id=NEW.signed_document_id AND proposal_id=NEW.proposal_id)) THEN
 PERFORM __V12_SCHEMA__.fail('Acceptance requires owned signed PDF and authorized signatory'); END IF;
 END IF;
 RETURN NEW;
END; $$;

CREATE FUNCTION __V12_SCHEMA__.emit_event(j BIGINT,c BIGINT,l BIGINT,kind TEXT,
 before_value JSONB,after_value JSONB,payload JSONB,version BIGINT DEFAULT NULL,
 from_code TEXT DEFAULT NULL,to_code TEXT DEFAULT NULL,from_label TEXT DEFAULT NULL,
 to_label TEXT DEFAULT NULL,feedback_value TEXT DEFAULT NULL) RETURNS void
LANGUAGE SQL SET search_path=pg_catalog AS $$
INSERT INTO __V12_SCHEMA__.recruitment_events(job_id,candidate_id,jd_candidate_id,event_type,
 before_json,after_json,payload_json,workflow_version,from_stage,to_stage,
 from_label_snapshot,to_label_snapshot,feedback)
VALUES(j,c,l,kind,before_value::text,after_value::text,payload::text,version,from_code,to_code,
 from_label,to_label,feedback_value); $$;

CREATE FUNCTION __V12_SCHEMA__.company_snapshot(value JSONB) RETURNS JSONB
LANGUAGE SQL IMMUTABLE SET search_path=pg_catalog AS $$
SELECT jsonb_build_object('company_name',value->'company_name','general_phone_numbers',
 (value->>'general_phone_numbers_json')::jsonb,'contacts',(value->>'contacts_json')::jsonb,
 'address_line',value->'address_line','city',value->'city','state',value->'state',
 'postal_code',value->'postal_code','is_active',value->'is_active'); $$;

CREATE FUNCTION __V12_SCHEMA__.audit_record() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE n JSONB; o JSONB; fields TEXT[]; b JSONB; a JSONB; p JSONB; kind TEXT; version BIGINT;
 actor_payload JSONB; from_label TEXT; to_label TEXT;
BEGIN
 n=to_jsonb(NEW); IF TG_OP='UPDATE' THEN o=to_jsonb(OLD); END IF;
 IF TG_TABLE_NAME='companies' THEN
 fields=ARRAY['company_name','general_phone_numbers_json','contacts_json','address_line','city',
 'state','postal_code','is_active','audit_request_key'];
 IF TG_OP='INSERT' OR __V12_SCHEMA__.changed_fields(o,n,fields,false)<>'{}'::jsonb THEN
 INSERT INTO __V12_SCHEMA__.company_audit_events(company_id,action,before_json,after_json,
 actor_name_snapshot,actor_verification_status,source_system,source_event_id,request_fingerprint)
 VALUES(NEW.id,CASE WHEN TG_OP='UPDATE' THEN 'COMPANY_UPDATED'
 WHEN NEW.legacy_postgres_id IS NULL THEN 'COMPANY_CREATED' ELSE 'COMPANY_IMPORTED' END,
 CASE WHEN TG_OP='UPDATE' THEN __V12_SCHEMA__.company_snapshot(o)::text END,
 __V12_SCHEMA__.company_snapshot(n)::text,NEW.audit_actor_name,NEW.audit_actor_role,'v12',
 NEW.audit_request_key,NEW.audit_request_fingerprint);
 END IF;
 ELSIF TG_TABLE_NAME='candidates' THEN
 fields=ARRAY['candidate_code','full_name','phone','email','links_json','job_title','current_employer',
 'current_city','preferred_cities_json','experience_years','qualification','primary_domain','skills_json',
 'professional_summary','current_salary_inr','current_salary_period','current_salary_basis',
 'expected_salary_inr','expected_salary_period','expected_salary_basis','notice_days','availability','source','is_active'];
 IF TG_OP='INSERT' THEN
 p=CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN jsonb_build_object('entity','candidate',
 'source','postgresql','source_table','candidates','source_id',NEW.legacy_postgres_id,
 'source_created_at',NEW.created_at,'imported_at',NEW.imported_at) ELSE jsonb_build_object('entity','candidate') END;
 PERFORM __V12_SCHEMA__.emit_event(NULL,NEW.id,NULL,
 CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN 'CANDIDATE_IMPORTED' ELSE 'CANDIDATE_CREATED' END,
 NULL,__V12_SCHEMA__.row_fields(n,fields),p);
 ELSE
 b=__V12_SCHEMA__.changed_fields(o,n,fields,true); a=__V12_SCHEMA__.changed_fields(o,n,fields,false);
 IF a<>'{}'::jsonb THEN PERFORM __V12_SCHEMA__.emit_event(NULL,NEW.id,NULL,'CANDIDATE_UPDATED',b,a,
 jsonb_build_object('entity','candidate','snapshot','changed_fields_only')); END IF;
 END IF;
 ELSIF TG_TABLE_NAME='job_descriptions' THEN
 fields=ARRAY['company_id','title','company_contact','location','work_mode','vacancies','status',
 'target_date','skills_json','experience_min','experience_max','qualification','salary_min_inr',
 'salary_max_inr','salary_period','salary_basis','requirement_notes','full_jd'];
 p=jsonb_build_object('entity','job_description','jd_code',NEW.jd_code);
 IF TG_OP='INSERT' THEN
 PERFORM __V12_SCHEMA__.emit_event(NEW.id,NULL,NULL,'JD_CREATED',NULL,
 __V12_SCHEMA__.row_fields(n,fields||ARRAY['workflow_mode','workflow_version']),p,NEW.workflow_version);
 ELSE
 IF (OLD.company_contact_id,OLD.company_contact_email_snapshot,OLD.company_contact_name_snapshot,OLD.contact_request_key)
 IS DISTINCT FROM (NEW.company_contact_id,NEW.company_contact_email_snapshot,NEW.company_contact_name_snapshot,NEW.contact_request_key) THEN
 PERFORM __V12_SCHEMA__.emit_event(NEW.id,NULL,NULL,'JD_CONTACT_SELECTED',
 jsonb_build_object('company_contact_id',OLD.company_contact_id,'name',OLD.company_contact_name_snapshot,'email',OLD.company_contact_email_snapshot),
 jsonb_build_object('company_contact_id',NEW.company_contact_id,'name',NEW.company_contact_name_snapshot,'email',NEW.company_contact_email_snapshot),
 jsonb_build_object('idempotency_key',NEW.contact_request_key,'request_fingerprint',NEW.contact_request_fingerprint,
 'actor_name',NEW.contact_actor_name,'actor_verification_status',NEW.contact_actor_role)); END IF;
 a=__V12_SCHEMA__.changed_fields(o,n,ARRAY['workflow_mode','workflow_version'],false);
 IF a<>'{}'::jsonb THEN PERFORM __V12_SCHEMA__.emit_event(NEW.id,NULL,NULL,'JD_WORKFLOW_UPDATED',
 __V12_SCHEMA__.changed_fields(o,n,ARRAY['workflow_mode','workflow_version'],true),a,
 p||jsonb_build_object('snapshot','changed_fields_only'),NEW.workflow_version); END IF;
 a=__V12_SCHEMA__.changed_fields(o,n,fields,false);
 IF a<>'{}'::jsonb THEN PERFORM __V12_SCHEMA__.emit_event(NEW.id,NULL,NULL,'JD_UPDATED',
 __V12_SCHEMA__.changed_fields(o,n,fields,true),a,p||jsonb_build_object('snapshot','changed_fields_only'),NEW.workflow_version); END IF;
 END IF;
 ELSIF TG_TABLE_NAME='jd_interview_rounds' THEN
 SELECT workflow_version INTO version FROM __V12_SCHEMA__.job_descriptions WHERE id=NEW.job_id;
 fields=ARRAY['round_name','display_order','mode','is_active','retired_at'];
 p=jsonb_build_object('entity','jd_interview_round','round_id',NEW.id);
 IF TG_OP='INSERT' THEN
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NULL,NULL,'ROUND_ADDED',NULL,
 __V12_SCHEMA__.row_fields(n,ARRAY['id']||fields),p,version);
 ELSE
 a=__V12_SCHEMA__.changed_fields(o,n,fields,false);
 IF a<>'{}'::jsonb THEN
 kind=CASE WHEN OLD.is_active=1 AND NEW.is_active=0 THEN 'ROUND_RETIRED'
 WHEN OLD.is_active=0 AND NEW.is_active=1 THEN 'ROUND_RESTORED' ELSE 'ROUND_UPDATED' END;
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NULL,NULL,kind,__V12_SCHEMA__.changed_fields(o,n,fields,true),a,
 p||jsonb_build_object('snapshot','changed_fields_only'),version); END IF;
 END IF;
 ELSIF TG_TABLE_NAME='candidate_activities' THEN
 fields=ARRAY['job_id','activity_type','status','due_at','occurred_at','notes','details_json'];
 p=jsonb_build_object('entity','candidate_activity','activity_id',NEW.id);
 IF TG_OP='INSERT' THEN PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NULL,
 'ACTIVITY_CREATED',NULL,__V12_SCHEMA__.row_fields(n,ARRAY['id']||fields),p);
 ELSE
 a=__V12_SCHEMA__.changed_fields(o,n,fields,false);
 IF a<>'{}'::jsonb THEN PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NULL,
 'ACTIVITY_UPDATED',__V12_SCHEMA__.changed_fields(o,n,fields,true),a,
 p||jsonb_build_object('snapshot','changed_fields_only')); END IF;
 END IF;
 ELSIF TG_TABLE_NAME='candidate_resumes' THEN
 p=jsonb_build_object('entity','candidate_resume','resume_id',NEW.id);
 IF TG_OP='INSERT' THEN
 IF NEW.legacy_postgres_id IS NOT NULL THEN p=p||jsonb_build_object('source','postgresql',
 'source_table',NEW.legacy_source_table,'source_id',NEW.legacy_postgres_id,
 'source_created_at',NEW.created_at,'imported_at',NEW.imported_at); END IF;
 PERFORM __V12_SCHEMA__.emit_event(NULL,NEW.candidate_id,NULL,
 CASE WHEN NEW.legacy_postgres_id IS NOT NULL THEN 'RESUME_IMPORTED' ELSE 'RESUME_ADDED' END,
 NULL,__V12_SCHEMA__.row_fields(n,ARRAY['id','resume_kind','source_type','original_filename','is_current'])
 -'id'||jsonb_build_object('resume_id',NEW.id),p);
 ELSIF OLD.is_current IS DISTINCT FROM NEW.is_current THEN
 PERFORM __V12_SCHEMA__.emit_event(NULL,NEW.candidate_id,NULL,'RESUME_STATUS_CHANGED',
 jsonb_build_object('resume_id',OLD.id,'resume_kind',OLD.resume_kind,'is_current',OLD.is_current),
 jsonb_build_object('resume_id',NEW.id,'resume_kind',NEW.resume_kind,'is_current',NEW.is_current),p); END IF;
 ELSIF TG_TABLE_NAME='jd_candidates' THEN
 SELECT workflow_version INTO version FROM __V12_SCHEMA__.job_descriptions WHERE id=NEW.job_id;
 p=jsonb_build_object('entity','jd_candidate');
 IF TG_OP='INSERT' THEN
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NEW.id,'ADDED',NULL,
 jsonb_build_object('stage_code','POOL','round_id',NULL),p,version,NULL,'POOL',NULL,'Candidate Pool');
 ELSE
 actor_payload=jsonb_build_object('idempotency_key',NEW.action_request_key,'request_fingerprint',
 NEW.action_request_fingerprint,'actor_name',NEW.action_actor_name,'actor_verification_status',NEW.action_actor_role);
 IF (OLD.stage_code,OLD.round_id) IS DISTINCT FROM (NEW.stage_code,NEW.round_id) THEN
 from_label=CASE WHEN OLD.stage_code='ROUND' THEN coalesce((SELECT round_name FROM __V12_SCHEMA__.jd_interview_rounds WHERE id=OLD.round_id),'Interview Round') ELSE OLD.stage_code END;
 to_label=CASE WHEN NEW.stage_code='ROUND' THEN coalesce((SELECT round_name FROM __V12_SCHEMA__.jd_interview_rounds WHERE id=NEW.round_id),'Interview Round') ELSE NEW.stage_code END;
 kind=CASE WHEN NEW.selection_outcome='JOINED_CONFIRMED' THEN 'JOINING_CONFIRMED'
 WHEN NEW.selection_outcome='PENDING_JOINING' THEN 'COMPANY_SELECTED'
 WHEN NEW.stage_code='NOT_SELECTED' THEN 'REJECTED' ELSE 'MOVED' END;
 b=__V12_SCHEMA__.row_fields(o,ARRAY['stage_code','round_id','selection_outcome','selected_on','joined_on','stage_note']);
 a=__V12_SCHEMA__.row_fields(n,ARRAY['stage_code','round_id','selection_outcome','selected_on',
 'selected_at_utc','joined_on','joining_confirmed_at_utc','confirmation_evidence','stage_note',
 'rejected_from_stage','rejected_round_name','rejected_round_index','rejected_at']);
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NEW.id,kind,b,a,p||actor_payload||
 jsonb_build_object('from_round_id',OLD.round_id,'to_round_id',NEW.round_id),version,
 OLD.stage_code,NEW.stage_code,from_label,to_label,NEW.stage_note);
 ELSE
 IF (OLD.selection_outcome,OLD.eligibility_released_at_utc) IS DISTINCT FROM
 (NEW.selection_outcome,NEW.eligibility_released_at_utc) THEN
 kind=CASE WHEN NEW.eligibility_released_at_utc IS NOT NULL THEN 'SOURCING_REACTIVATED' ELSE NEW.selection_outcome END;
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NEW.id,kind,
 __V12_SCHEMA__.row_fields(o,ARRAY['selection_outcome','eligibility_released_at_utc']),
 __V12_SCHEMA__.row_fields(n,ARRAY['selection_outcome','outcome_closed_on','outcome_reason',
 'eligibility_released_at_utc','eligibility_release_reason']),p||actor_payload,NULL,OLD.stage_code,NEW.stage_code);
 END IF;
 IF OLD.stage_note IS DISTINCT FROM NEW.stage_note THEN
 PERFORM __V12_SCHEMA__.emit_event(NEW.job_id,NEW.candidate_id,NEW.id,'STAGE_NOTE_UPDATED',
 jsonb_build_object('stage_note',OLD.stage_note),jsonb_build_object('stage_note',NEW.stage_note),p,version); END IF;
 END IF;
 END IF;
 END IF;
 RETURN NEW;
END; $$;
