"""Adapters for the immutable approved V12 interface; no schema or legacy writes."""

import base64
import hashlib
import json
import re
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from . import candidates, jobs, resumes, unified
from . import request_receipts as receipts
from .candidate_schemas import CandidateCreate, CandidatePatch
from .common import AtsError, event_record, one, utc_now
from .database import transaction


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Registration(Input):
    candidate: CandidateCreate
    allow_duplicate: bool = False
    source_label: str = Field(default="Other", max_length=100)
    notice_text: str = Field(default="", max_length=300)
    registration_purpose: str | None = Field(default=None, max_length=2000)
    filename: str | None = Field(default=None, max_length=255)
    file_base64: str | None = Field(default=None, max_length=14_000_000)


def register(engine, data, root):
    values = candidates._db_values(data.candidate)
    values["candidate_code"] = "ATS-" + uuid4().hex[:16].upper()
    path = None
    request_data = data.model_dump(mode="json")
    if data.file_base64:
        try:
            blob = base64.b64decode(data.file_base64, validate=True)
        except ValueError:
            raise AtsError("Invalid resume upload.") from None
        filename = resumes._filename(data.filename or "")
        suffix = resumes._validate(blob, filename, 10 * 1024 * 1024)
        private_root = resumes._root(root)
    try:
        with transaction(engine) as conn:
            from .registration_store import ensure_source

            ensure_source(conn, values)
            prior = receipts.replay(conn, "approved-registration", request_data)
            if prior is not None:
                return {"id": prior, "replayed": True}
            if not data.allow_duplicate:
                candidates._duplicates(conn, values)
            cid = conn.execute(
                text(
                    "INSERT INTO candidates("
                    + ",".join(values)
                    + ") VALUES("
                    + ",".join(":" + k for k in values)
                    + ")"
                ),
                values,
            ).lastrowid
            if data.file_base64:
                relative, path = resumes._publish(private_root, cid, "ORIGINAL", blob, suffix)
                resumes._version(
                    conn,
                    cid,
                    "ORIGINAL",
                    source_type="UPLOADED",
                    original_filename=filename,
                    storage_path=relative,
                    parsed_json=json.dumps(
                        {"sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob)}
                    ),
                )
            # Native registration facts live in immutable audit evidence, not legacy source JSON.
            conn.execute(
                text(
                    "INSERT INTO recruitment_events(candidate_id,event_type,payload_json) "
                    "VALUES(:id,'REGISTRATION_DETAILS',:payload)"
                ),
                {
                    "id": cid,
                    "payload": json.dumps(
                        {
                            "source_label": data.source_label,
                            "notice_text": data.notice_text,
                            "registration_purpose": data.registration_purpose or None,
                            "separate_identity_confirmed": data.allow_duplicate,
                        }
                    ),
                },
            )
            candidates.rebuild_search(conn, cid)
            receipts.record(conn, "approved-registration", request_data, cid, candidate_id=cid)
        return {"id": cid, "replayed": False}
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def company_revision(row):
    return hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()


def state(engine):
    with engine.connect() as conn:
        people = [
            candidates.candidate_dict(r)
            for r in conn.execute(text("SELECT * FROM candidates ORDER BY id")).mappings()
        ]
        for person in people:
            person.update(unified.eligibility(conn, person["id"]))
        from . import candidate_profiles, profile_store

        if profile_store.installed(conn):
            for person in people:
                person["reviewed_details"] = candidate_profiles._state(conn, person["id"])["extra"]
        visible_company_fields = (
            "id",
            "company_name",
            "address_line",
            "city",
            "state",
            "postal_code",
            "general_phone_numbers_json",
            "source_register_ids_json",
            "contacts_json",
            "is_active",
        )
        companies = [
            {**{k: row[k] for k in visible_company_fields}, "revision": company_revision(row)}
            for row in conn.execute(
                text("SELECT * FROM companies ORDER BY company_name_key,id")
            ).mappings()
        ]
        for company in companies:
            company["contacts"] = json.loads(company.pop("contacts_json"))
            company["phones"] = json.loads(company.pop("general_phone_numbers_json"))
            company["source_ids"] = json.loads(company.pop("source_register_ids_json"))
        jids = list(conn.scalars(text("SELECT id FROM job_descriptions ORDER BY id DESC")))
        versions = [
            resumes._resume_public(r)
            for r in conn.execute(
                text("SELECT * FROM candidate_resumes ORDER BY created_at DESC,id DESC")
            ).mappings()
        ]
        events = [
            event_record(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM recruitment_events WHERE event_type<>'REQUEST_COMPLETED' "
                    "ORDER BY created_at DESC,id DESC"
                )
            ).mappings()
        ]
        activities = [
            event_record(r)
            for r in conn.execute(
                text("SELECT * FROM candidate_activities ORDER BY id DESC")
            ).mappings()
        ]
        for event in events:
            event.update(
                payload=event.get("payload_json") or {}, after=event.get("after_json") or {}
            )
        for activity in activities:
            activity["details"] = activity.get("details_json") or {}
        placements = [
            dict(r)
            for r in conn.execute(text("SELECT * FROM v_company_placement_register")).mappings()
        ]
        from .candidate_registers import source_options

        candidate_sources = source_options(conn)
    requirements = []
    for jid in jids:
        job = jobs.get_job(engine, jid)
        job["workflow"] = jobs.get_workflow(engine, jid)
        job["pipeline"] = jobs.pipeline(engine, jid)
        requirements.append(job)
    return {
        "candidates": people,
        "candidate_sources": candidate_sources,
        "companies": companies,
        "resumes": versions,
        "jobs": requirements,
        "events": events,
        "activities": activities,
        "placements": placements,
        "today": unified.office_today().isoformat(),
    }


class Contact(Input):
    id: UUID | None = None
    name: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone: str = Field(default="", max_length=1000)
    primary: bool = False


class CompanyEdit(Input):
    idempotency_key: UUID
    expected_revision: str = Field(min_length=64, max_length=64)
    actor_name: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    phone: str = Field(default="", max_length=2000)
    address: str = Field(default="", max_length=2000)
    city: str = Field(default="", max_length=200)
    state: str = Field(default="", max_length=200)
    postal: str = Field(default="", max_length=40)
    contacts: list[Contact] = Field(default_factory=list, max_length=100)
    archive: bool = False


def edit_company(engine, company_id, data, role):
    from jobmitra.modules.companies.normalization import company_name_key

    digest = unified.request_hash(data, ["approved-company", company_id])
    with transaction(engine) as conn:
        row = (
            conn.execute(text("SELECT * FROM companies WHERE id=:id"), {"id": company_id})
            .mappings()
            .first()
        )
        if row is None:
            raise AtsError("Company not found.", 404)
        old = dict(row)
        if unified.prior_request(conn, data.idempotency_key, digest, company=True):
            return {"id": company_id, "replayed": True}
        if data.expected_revision != company_revision(old):
            raise AtsError("Company changed since this form was opened. Reload before saving.", 409)
        existing = json.loads(old["contacts_json"])
        known = {r["id"]: r for r in existing}
        ids = [str(r.id) for r in data.contacts if r.id]
        if len(ids) != len(set(ids)) or not set(ids) <= known.keys():
            raise AtsError("Contacts must belong to this canonical company.")
        updated = []
        for contact in data.contacts:
            email = unified.ContactEmail.valid_email(contact.email)
            if contact.primary and not email:
                raise AtsError("A primary email contact requires an email address.")
            row = (
                dict(known[str(contact.id)])
                if contact.id
                else {"id": str(uuid4()), "created_at": utc_now()}
            )
            # Retain original arrays exactly when the displayed field was not edited.
            phones = row.get("phone_numbers", [])
            if contact.phone not in {"\n".join(phones), ", ".join(phones)}:
                phones = [p.strip() for p in re.split(r"[,\n]+", contact.phone) if p.strip()]
            name = (
                row.get("contact_name")
                if contact.name == (row.get("contact_name") or "")
                else contact.name
            )
            designation = (
                row.get("designation")
                if contact.title == (row.get("designation") or "")
                else contact.title or None
            )
            row.update(
                contact_name=name,
                designation=designation,
                email=email,
                phone_numbers=phones,
                is_primary_email=contact.primary,
                is_archived=False,
            )
            updated.append(row)
        if sum(r.get("is_primary_email", False) for r in updated) > 1:
            raise AtsError("Choose at most one primary email contact.")
        # Remove in the UI means archive; never erase original contact evidence/identity.
        updated.extend(
            {**r, "is_archived": True, "is_primary_email": False}
            for r in existing
            if r["id"] not in ids
        )
        phones = json.loads(old["general_phone_numbers_json"])
        if data.phone != "\n".join(phones):
            phones = [p.strip() for p in data.phone.splitlines() if p.strip()]
        conn.execute(
            text(
                "UPDATE companies SET company_name=:name,company_name_key=:key,"
                "address_line=:address,city=:city,state=:state,postal_code=:postal,"
                "general_phone_numbers_json=:phones,contacts_json=:contacts,"
                "is_active=:active,audit_request_key=:request,audit_request_fingerprint=:digest,"
                "audit_actor_name=:actor,audit_actor_role=:role,updated_at=:now WHERE id=:id"
            ),
            {
                "id": company_id,
                "name": data.name,
                "key": company_name_key(data.name),
                "address": data.address or None,
                "city": data.city or None,
                "state": data.state or None,
                "postal": data.postal or None,
                "phones": json.dumps(phones),
                "contacts": json.dumps(updated),
                "active": 0 if data.archive else old["is_active"],
                "request": str(data.idempotency_key),
                "digest": digest,
                "actor": data.actor_name,
                "role": role,
                "now": utc_now(),
            },
        )
    return {"id": company_id, "replayed": False}


class ParsedApproval(Input):
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    source_resume_id: int = Field(ge=1)
    raw_json: str = Field(min_length=2, max_length=262144)
    filename: str = Field(default="Reviewed parsed JSON", max_length=255)
    approved: list[str] = Field(max_length=20)
    changes: CandidatePatch
    professional_extras: dict = Field(default_factory=dict)
    identity_confirmed: bool = False


def approve_parse(engine, cid, data, role):
    try:
        original = json.loads(data.raw_json)
    except ValueError:
        raise AtsError("Invalid JSON.") from None
    if not isinstance(original, dict):
        raise AtsError("Parsed JSON must be an object.")
    permitted = {
        "job_title",
        "current_employer",
        "professional_summary",
        "qualification",
        "current_city",
        "skills",
    }
    changes = data.changes.model_dump(exclude_unset=True)
    if not changes.keys() <= permitted or not set(changes) <= set(data.approved):
        raise AtsError("Only explicitly approved professional fields may change.")
    extras = {"employment_history", "certifications", "projects", "achievements", "qualifications"}
    if not data.professional_extras.keys() <= extras:
        raise AtsError("Unsupported professional evidence.")
    if not {"extra:" + k for k in data.professional_extras} <= set(data.approved):
        raise AtsError("Approve each additional professional field explicitly.")
    if len(json.dumps(data.professional_extras).encode()) > 256000:
        raise AtsError("Professional evidence is too large.")
    digest = unified.request_hash(data, ["approved-parsed", cid])
    with transaction(engine) as conn:
        person = one(conn, "candidates", cid)
        source = one(conn, "candidate_resumes", data.source_resume_id)
        if (
            source["candidate_id"] != cid
            or source["resume_kind"] != "ORIGINAL"
            or not source["is_current"]
        ):
            raise AtsError("Review the current original resume before applying JSON.", 409)
        if unified.prior_request(conn, data.idempotency_key, digest):
            return {"replayed": True}
        source_name = original.get("full_name") or original.get("name")
        if (
            source_name
            and str(source_name).casefold().strip() != person["full_name"].casefold().strip()
            and not data.identity_confirmed
        ):
            raise AtsError("Confirm the JSON belongs to this candidate.")
        profile = {**changes, **data.professional_extras}
        rid = resumes._version(
            conn,
            cid,
            "PARSED_TEXT",
            source_type="UPLOADED",
            original_filename=data.filename,
            parsed_json=json.dumps(
                {
                    "profile": profile,
                    "source_resume_id": source["id"],
                    "facts_reviewed": True,
                    "candidate_name_snapshot": person["full_name"],
                    "original_source_json": original,
                    "original_source_json_text": data.raw_json,
                    "approved_fields": data.approved,
                    "reviewed_by_declared_name": data.actor_name,
                }
            ),
        )
        if "skills" in changes:
            changes["skills_json"] = json.dumps(changes.pop("skills"))
        if changes:
            conn.execute(
                text(
                    "UPDATE candidates SET "
                    + ",".join(k + "=:" + k for k in changes)
                    + " WHERE id=:id"
                ),
                {**changes, "id": cid},
            )
        candidates.rebuild_search(conn, cid)
        conn.execute(
            text(
                "INSERT INTO recruitment_events(candidate_id,event_type,payload_json) "
                "VALUES(:id,'PARSED_PROFILE_APPROVED',:payload)"
            ),
            {
                "id": cid,
                "payload": json.dumps(
                    {
                        "idempotency_key": str(data.idempotency_key),
                        "request_fingerprint": digest,
                        "resume_id": rid,
                        "actor_name": data.actor_name,
                        "actor_verification_status": role,
                        "approved_fields": data.approved,
                    }
                ),
            },
        )
    return {"resume_id": rid, "replayed": False}
