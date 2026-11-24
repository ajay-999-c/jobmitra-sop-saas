"""V12 facts, company analytics and idempotent actions on canonical ATS entities."""

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .candidate_schemas import ParsedResumeInput
from .common import AtsError, event_record, one, utc_now
from .database import schema_version, transaction


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["SELECT", "JOIN", "NOT_JOINED", "CANCEL", "REACTIVATE"]
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    effective_on: date
    reason: str = Field(default="", max_length=5000)
    confirmation_evidence: str = Field(default="", max_length=5000)
    expected_stage: str | None = None
    workflow_version: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def facts(self):
        if self.effective_on > office_today():
            raise ValueError("A recorded outcome cannot be in the future")
        if self.action in {"NOT_JOINED", "CANCEL", "REACTIVATE"} and not self.reason:
            raise ValueError("A reason is required")
        if self.action == "JOIN" and not self.confirmation_evidence:
            raise ValueError("Confirm actual joining with evidence or confirmation details")
        return self


class ContactEmail(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: UUID
    email: str | None = Field(default=None, max_length=254)
    is_primary_email: bool = False

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value and not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", value):
            raise ValueError("Enter a valid contact email")
        return value or None


class NewContact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contact_name: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(default=None, max_length=200)
    phone_numbers: list[str] = Field(default_factory=list, max_length=20)
    email: str | None = Field(default=None, max_length=254)
    is_primary_email: bool = False

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return ContactEmail.valid_email(value)


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    company_name: str = Field(min_length=1, max_length=300)
    address_line: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=200)
    state: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=40)
    contacts: list[NewContact] = Field(default_factory=list, max_length=50)


class CompanyEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    company_name: str | None = Field(default=None, min_length=1, max_length=300)
    address_line: str | None = Field(default=None, max_length=2000)
    city: str | None = Field(default=None, max_length=200)
    state: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=40)
    contacts: list[ContactEmail] | None = Field(default=None, max_length=300)
    new_contacts: list[NewContact] = Field(default_factory=list, max_length=50)


class ContactChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    contact_id: UUID
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)


class ParsedReview(ParsedResumeInput):
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    approved_fields: list[
        Literal["job_title", "current_employer", "professional_summary", "qualification", "skills"]
    ] = Field(default_factory=list, max_length=5)


def parsed_diff(candidate, profile):
    values = profile.model_dump(exclude_unset=True, exclude_none=True)
    mapping = {
        "current_job_title": "job_title",
        "current_employer": "current_employer",
        "professional_summary": "professional_summary",
        "qualification": "qualification",
        "skills": "skills",
    }
    result = []
    for source, target in mapping.items():
        if source not in values:
            continue
        old = json.loads(candidate["skills_json"]) if target == "skills" else candidate[target]
        new = values[source]
        result.append(
            {
                "field": target,
                "before": old,
                "after": new,
                "status": "SAME" if old == new else "NEW" if old in (None, "", []) else "CONFLICT",
            }
        )
    return result


def review_parse(engine, candidate_id, data: ParsedReview, role):
    from .candidates import rebuild_search
    from .resumes import _version

    digest = request_hash(data, ["parsed-review", candidate_id])
    with transaction(engine) as conn:
        candidate = one(conn, "candidates", candidate_id)
        if prior_request(conn, data.idempotency_key, digest):
            row = conn.execute(
                text(
                    "SELECT payload_json FROM recruitment_events WHERE "
                    "json_extract(payload_json,'$.idempotency_key')=:key"
                ),
                {"key": str(data.idempotency_key)},
            ).scalar_one()
            return {"resume_id": json.loads(row)["resume_id"], "replayed": True}
        source = one(conn, "candidate_resumes", data.source_resume_id)
        if (
            source["candidate_id"] != candidate_id
            or source["resume_kind"] != "ORIGINAL"
            or not source["is_current"]
        ):
            raise AtsError("Review the current original resume for this candidate.", 409)
        diff = parsed_diff(candidate, data.profile)
        available = {row["field"] for row in diff}
        if (
            len(set(data.approved_fields)) != len(data.approved_fields)
            or not set(data.approved_fields) <= available
        ):
            raise AtsError("Approve only fields present in the reviewed JSON.")
        payload = {
            "profile": data.profile.model_dump(exclude_none=True),
            "source_resume_id": source["id"],
            "facts_reviewed": True,
            "candidate_name_snapshot": candidate["full_name"],
            "approved_fields": data.approved_fields,
            "reviewed_by_declared_name": data.actor_name,
            "review_capability": role,
        }
        resume_id = _version(
            conn,
            candidate_id,
            "PARSED_TEXT",
            source_type="UPLOADED",
            parsed_json=json.dumps(payload, ensure_ascii=False),
        )
        changes = {
            row["field"]: row["after"] for row in diff if row["field"] in data.approved_fields
        }
        if "skills" in changes:
            changes["skills_json"] = json.dumps(changes.pop("skills"), ensure_ascii=False)
        if changes:
            conn.execute(
                text(
                    "UPDATE candidates SET "
                    + ",".join(k + "=:" + k for k in changes)
                    + " WHERE id=:id"
                ),
                {**changes, "id": candidate_id},
            )
        rebuild_search(conn, candidate_id)
        conn.execute(
            text(
                "INSERT INTO "
                "recruitment_events(candidate_id,event_type,before_json,after_json,payload_json)"
                " VALUES(:id,'PARSED_PROFILE_APPROVED',:before,:after,:payload)"
            ),
            {
                "id": candidate_id,
                "before": json.dumps(
                    {r["field"]: r["before"] for r in diff if r["field"] in data.approved_fields}
                ),
                "after": json.dumps(
                    {r["field"]: r["after"] for r in diff if r["field"] in data.approved_fields}
                ),
                "payload": json.dumps(
                    {
                        "idempotency_key": str(data.idempotency_key),
                        "request_fingerprint": digest,
                        "resume_id": resume_id,
                        "actor_name": data.actor_name,
                        "actor_verification_status": role,
                    }
                ),
            },
        )
        return {"resume_id": resume_id, "replayed": False, "diff": diff}


def office_today():
    return datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()


def is_v3(conn):
    return schema_version(conn) == 3


def eligibility(conn, candidate_id, exclude_link=None):
    locks = (
        conn.execute(
            text(
                "SELECT id,job_id,stage_code FROM jd_candidates WHERE candidate_id=:id "
                "AND (CAST(:exclude AS BIGINT) IS NULL OR id<>:exclude) AND "
                "((stage_code='JOINED' AND eligibility_released_at_utc IS NULL) OR "
                "(stage_code='SELECTED' AND (selection_outcome IS NULL OR "
                "selection_outcome='PENDING_JOINING'))) "
                "ORDER BY CASE stage_code WHEN 'JOINED' THEN 0 ELSE 1 END,id"
            ),
            {"id": candidate_id, "exclude": exclude_link},
        )
        .mappings()
        .all()
    )
    if locks:
        placed = locks[0]["stage_code"] == "JOINED"
        return eligibility_value("PLACED_LOCKED" if placed else "SELECTED_ON_HOLD")
    status = conn.scalar(
        text(
            "SELECT allocation_eligibility FROM "
            "v_candidate_allocation_eligibility WHERE candidate_id=:id"
        ),
        {"id": candidate_id},
    )
    # The view includes the candidate's own current milestone. With exclude_link,
    # no OTHER unresolved link was found, so selection -> joining remains allowed.
    return {
        "allocation_eligibility": status or "AVAILABLE",
        "can_allocate": True,
        "reason_code": None,
    }


def eligibility_value(status):
    reason = {"PLACED_LOCKED": "CANDIDATE_PLACED", "SELECTED_ON_HOLD": "CANDIDATE_SELECTED_ON_HOLD"}
    return {
        "allocation_eligibility": status or "AVAILABLE",
        "can_allocate": status not in reason,
        "reason_code": reason.get(status),
    }


def require_available(conn, candidate_id, exclude_link=None):
    result = eligibility(conn, candidate_id, exclude_link)
    if not result["can_allocate"]:
        raise AtsError(
            "Candidate has an unresolved selection or confirmed joining in another JD.",
            409,
            result["reason_code"],
        )


def request_hash(data, scope):
    return hashlib.sha256(
        json.dumps(
            {"scope": scope, "data": data.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def prior_request(conn, key, digest, company=False):
    query = (
        "SELECT request_fingerprint FROM company_audit_events WHERE "
        "source_system='v12' AND source_event_id=:key"
        if company
        else "SELECT json_extract(payload_json,'$.request_fingerprint') FROM "
        "recruitment_events WHERE "
        "json_extract(payload_json,'$.idempotency_key')=:key"
    )
    row = conn.execute(text(query), {"key": str(key)}).first()
    if row is not None:
        if row[0] != digest:
            raise AtsError(
                "This request key was already used for a different action.",
                409,
                "IDEMPOTENCY_CONFLICT",
            )
        return True
    return False


def outcome(engine, job_id, link_id, data: Action, role):
    from .jobs import linked, next_stage, workflow

    digest = request_hash(data, ["outcome", job_id, link_id])
    with nullcontext(engine) if isinstance(engine, Connection) else transaction(engine) as conn:
        link = linked(conn, job_id, link_id)
        if prior_request(conn, data.idempotency_key, digest):
            return link
        job = one(conn, "job_descriptions", job_id)
        if data.expected_stage and link["stage_code"] != data.expected_stage:
            raise AtsError("The candidate stage changed; reload before confirming.", 409)
        if data.workflow_version is not None and data.workflow_version != job["workflow_version"]:
            raise AtsError("The workflow changed; reload before confirming.", 409)
        changes = {
            "action_request_key": str(data.idempotency_key),
            "action_request_fingerprint": digest,
            "action_actor_name": data.actor_name,
            "action_actor_role": role,
        }
        effective = data.effective_on.isoformat()
        if data.action == "SELECT":
            if job["status"] != "ACTIVE" or next_stage(link, workflow(conn, job_id)) != (
                "SELECTED",
                None,
            ):
                raise AtsError(
                    "Selection must follow the configured hiring workflow in an active JD.", 409
                )
            require_available(conn, link["candidate_id"], link_id)
            changes.update(
                stage_code="SELECTED",
                round_id=None,
                selection_outcome="PENDING_JOINING",
                selected_on=effective,
                selected_at_utc=utc_now(),
            )
        elif data.action == "JOIN":
            if job["status"] != "ACTIVE" or link["selection_outcome"] != "PENDING_JOINING":
                raise AtsError(
                    "Confirm joining only for an unresolved selection in an active JD.", 409
                )
            require_available(conn, link["candidate_id"], link_id)
            if effective < link["selected_on"]:
                raise AtsError("Joining cannot precede selection.")
            changes.update(
                stage_code="JOINED",
                round_id=None,
                selection_outcome="JOINED_CONFIRMED",
                joined_on=effective,
                joining_confirmed_at_utc=utc_now(),
                confirmation_evidence=data.confirmation_evidence,
            )
        elif data.action in {"NOT_JOINED", "CANCEL"}:
            if link["selection_outcome"] != "PENDING_JOINING":
                raise AtsError("Only an unresolved selection can be closed.", 409)
            if effective < link["selected_on"]:
                raise AtsError("Closure cannot precede selection.")
            changes.update(
                selection_outcome="NOT_JOINED"
                if data.action == "NOT_JOINED"
                else "SELECTION_CANCELLED",
                outcome_closed_on=effective,
                outcome_reason=data.reason,
            )
        else:
            if role not in {"SUPERVISOR_TOKEN", "LOCAL_DEVELOPMENT", "OFFICE_LAN"}:
                raise AtsError(
                    "Reactivation requires a separately configured supervisor capability.", 403
                )
            if (
                link["selection_outcome"] != "JOINED_CONFIRMED"
                or link["eligibility_released_at_utc"]
            ):
                raise AtsError("Only an unreleased confirmed placement can be reactivated.", 409)
            if effective < link["joined_on"]:
                raise AtsError("Reactivation cannot precede joining.")
            changes.update(
                eligibility_released_at_utc=utc_now(), eligibility_release_reason=data.reason
            )
            if role == "OFFICE_LAN":
                # Existing immutable SQLite/PG guards require this capability tag.
                # Record the real authorization policy explicitly; no token/staff
                # authentication is claimed and no trigger/schema is weakened.
                changes["action_actor_role"] = "SUPERVISOR_TOKEN"
                conn.execute(
                    text(
                        "INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,"
                        "event_type,payload_json) "
                        "VALUES(:j,:c,:l,'OFFICE_LAN_SUPERVISOR_AUTHORIZED',:p)"
                    ),
                    {
                        "j": job_id,
                        "c": link["candidate_id"],
                        "l": link_id,
                        "p": json.dumps(
                            {
                                "authorization_policy": "OFFICE_LAN",
                                "individual_authenticated": False,
                                "database_capability_tag": "SUPERVISOR_TOKEN",
                                "actor_name": data.actor_name,
                                "request_key": str(data.idempotency_key),
                            }
                        ),
                    },
                )
        conn.execute(
            text(
                "UPDATE jd_candidates SET "
                + ",".join(k + "=:" + k for k in changes)
                + " WHERE id=:id"
            ),
            {**changes, "id": link_id},
        )
        # The coordinated V3 triggers append exactly one canonical outcome event.
        result = one(conn, "jd_candidates", link_id)
        result.update(eligibility(conn, link["candidate_id"]))
        return result


def directory(engine, query="", page=1, page_size=50):
    with engine.connect() as conn:
        where = " WHERE company_name LIKE :q ESCAPE '\\' COLLATE NOCASE"
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params = {"q": "%" + escaped + "%", "limit": page_size, "offset": (page - 1) * page_size}
        total = conn.scalar(text("SELECT count(*) FROM companies" + where), params)
        rows = conn.execute(
            text(
                "SELECT "
                "id,company_name,city,state,is_active,json_array_length(contacts_json)"
                " contact_count FROM companies"
                + where
                + " ORDER BY company_name_key,id LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def edit_company(engine, company_id, data: CompanyEdit, role):
    from jobmitra.modules.companies.normalization import company_name_key

    from .companies import CompanyGateway

    digest = request_hash(data, ["company", company_id])
    with transaction(engine) as conn:
        old = (
            conn.execute(text("SELECT * FROM companies WHERE id=:id"), {"id": company_id})
            .mappings()
            .first()
        )
        if not old:
            raise AtsError("Company not found.", 404)
        if not prior_request(conn, data.idempotency_key, digest, company=True):
            values = data.model_dump(
                exclude_unset=True,
                exclude={"idempotency_key", "actor_name", "contacts", "new_contacts"},
            )
            if "company_name" in values:
                if values["company_name"] is None:
                    raise AtsError("Company name cannot be empty.")
                values["company_name_key"] = company_name_key(values["company_name"])
            if data.contacts is not None or data.new_contacts:
                contacts = json.loads(old["contacts_json"])
                updates = {str(r.id): r for r in data.contacts or []}
                if len(updates) != len(data.contacts or []) or not updates.keys() <= {
                    r["id"] for r in contacts
                }:
                    raise AtsError("Contact IDs must be unique and belong to this company.")
                for contact in contacts:
                    update = updates.get(contact["id"])
                    if update is not None:
                        contact.update(email=update.email, is_primary_email=update.is_primary_email)
                contacts.extend(new_contact_record(r) for r in data.new_contacts)
                if sum(bool(r.get("is_primary_email")) for r in contacts) > 1:
                    raise AtsError("Choose at most one primary email contact.")
                if any(r.get("is_primary_email") and not r.get("email") for r in contacts):
                    raise AtsError("A primary email contact must have an email address.")
                values["contacts_json"] = json.dumps(contacts, ensure_ascii=False)
            values.update(
                audit_request_key=str(data.idempotency_key),
                audit_request_fingerprint=digest,
                audit_actor_name=data.actor_name,
                audit_actor_role=role,
                updated_at=utc_now(),
            )
            conn.execute(
                text(
                    "UPDATE companies SET "
                    + ",".join(k + "=:" + k for k in values)
                    + " WHERE id=:id"
                ),
                {**values, "id": company_id},
            )
    return CompanyGateway(engine).detail(company_id)


def new_contact_record(data):
    from uuid import uuid4

    return {
        "id": str(uuid4()),
        **data.model_dump(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def create_company(engine, data: CompanyCreate, role):
    from uuid import uuid4

    from jobmitra.modules.companies.normalization import company_name_key

    from .companies import CompanyGateway

    digest = request_hash(data, ["new-company"])
    with transaction(engine) as conn:
        if prior_request(conn, data.idempotency_key, digest, company=True):
            identifier = conn.scalar(
                text(
                    "SELECT company_id FROM company_audit_events WHERE "
                    "source_system='v12' AND source_event_id=:key"
                ),
                {"key": str(data.idempotency_key)},
            )
        else:
            identifier = str(uuid4())
            contacts = [new_contact_record(c) for c in data.contacts]
            if sum(bool(c["is_primary_email"]) for c in contacts) > 1 or any(
                c["is_primary_email"] and not c["email"] for c in contacts
            ):
                raise AtsError("Choose at most one primary contact with a recorded email.")
            values = data.model_dump(exclude={"idempotency_key", "actor_name", "contacts"})
            values.update(
                id=identifier,
                company_name_key=company_name_key(data.company_name),
                contacts_json=json.dumps(contacts),
                audit_request_key=str(data.idempotency_key),
                audit_request_fingerprint=digest,
                audit_actor_name=data.actor_name,
                audit_actor_role=role,
            )
            conn.execute(
                text(
                    "INSERT INTO companies("
                    + ",".join(values)
                    + ") VALUES("
                    + ",".join(":" + k for k in values)
                    + ")"
                ),
                values,
            )
    return CompanyGateway(engine).detail(identifier)


def period_bounds(period, start=None, end=None, today=None):
    today = today or office_today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    elif period == "year":
        start, end = date(today.year, 1, 1), date(today.year, 12, 31)
    elif not start or not end:
        raise AtsError("Choose both custom date boundaries.")
    if start > end or (end - start).days > 3660:
        raise AtsError("Use an ordered date range of at most ten years.")
    return start, end


def report(engine, period="month", start=None, end=None, company_id=None):
    start, end = period_bounds(period, start, end)
    params = {"start": start.isoformat(), "end": end.isoformat(), "company": company_id}
    with engine.connect() as conn:
        records = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM v_company_placement_register "
                    "WHERE (CAST(:company AS TEXT) IS NULL "
                    "OR company_id=:company) ORDER BY COALESCE(joined_on,selected_on) "
                    "DESC,jd_candidate_id DESC"
                ),
                params,
            ).mappings()
        ]
        selected = [
            r
            for r in records
            if r["selected_on"] and params["start"] <= r["selected_on"] <= params["end"]
        ]
        joined = [
            r
            for r in records
            if r["selection_outcome"] == "JOINED_CONFIRMED"
            and r["joining_confirmed_at_utc"]
            and r["joined_on"]
            and params["start"] <= r["joined_on"] <= params["end"]
        ]
        daily = (end - start).days <= 62
        buckets = {}
        day = start
        while day <= end:
            key = day.isoformat() if daily else day.strftime("%Y-%m")
            buckets[key] = 0
            day += timedelta(days=1)
        for row in joined:
            key = row["joined_on"] if daily else row["joined_on"][:7]
            buckets[key] += 1
        register = [r for r in records if r in selected or r in joined]
        return {
            "start": params["start"],
            "end": params["end"],
            "timezone": "Asia/Kolkata",
            "week_starts": "Monday",
            "metrics": {
                "confirmed_placements": len(joined),
                "unique_candidates_placed": len({r["candidate_id"] for r in joined}),
                "company_selections": len(selected),
                "awaiting_joining": sum(
                    r["selection_outcome"] == "PENDING_JOINING" for r in selected
                ),
                "companies_with_joinings": len({r["company_id"] for r in joined}),
                "open_backlog": sum(r["selection_outcome"] == "PENDING_JOINING" for r in records),
            },
            "trend": [{"date": k, "confirmed_placements": v} for k, v in buckets.items()],
            "items": register,
            "selection_metric": "One latest selection per canonical candidate/JD association; "
            "repeated episodes are not supported.",
        }


def company_records(engine, company_id):
    from .companies import CompanyGateway

    result = CompanyGateway(engine).detail(company_id)
    with engine.connect() as conn:
        result["placements"] = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM v_company_placement_register WHERE company_id=:id "
                    "ORDER BY jd_candidate_id DESC"
                ),
                {"id": company_id},
            ).mappings()
        ]
        result["jobs"] = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT id,jd_code,title,status,target_date FROM job_descriptions "
                    "WHERE company_id=:id ORDER BY id DESC"
                ),
                {"id": company_id},
            ).mappings()
        ]
        result["audit"] = [
            event_record(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM company_audit_events WHERE company_id=:id ORDER BY id "
                    "DESC LIMIT 100"
                ),
                {"id": company_id},
            ).mappings()
        ]
    return result


def choose_contact(engine, job_id, data: ContactChoice, role):
    digest = request_hash(data, ["contact", job_id])
    with transaction(engine) as conn:
        job = one(conn, "job_descriptions", job_id)
        if prior_request(conn, data.idempotency_key, digest):
            return job
        contacts = json.loads(
            conn.scalar(
                text("SELECT contacts_json FROM companies WHERE id=:id"), {"id": job["company_id"]}
            )
        )
        contact = next(
            (r for r in contacts if r["id"] == str(data.contact_id) and not r.get("is_archived")),
            None,
        )
        if contact is None:
            raise AtsError("Choose an active contact belonging to the JD company.")
        conn.execute(
            text(
                "UPDATE job_descriptions SET "
                "company_contact_id=:contact,company_contact_name_snapshot=:name,company_contact_email_snapshot=:email,contact_request_key=:key,contact_request_fingerprint=:digest,contact_actor_name=:actor,contact_actor_role=:role"
                " WHERE id=:id"
            ),
            {
                "contact": str(data.contact_id),
                "name": contact.get("contact_name"),
                "email": contact.get("email"),
                "key": str(data.idempotency_key),
                "digest": digest,
                "actor": data.actor_name,
                "role": role,
                "id": job_id,
            },
        )
        return one(conn, "job_descriptions", job_id)


def email_context(engine, candidate_id, job_id, audience, contact_id=None):
    with engine.connect() as conn:
        candidate = one(conn, "candidates", candidate_id)
        job = one(conn, "job_descriptions", job_id)
        link = (
            conn.execute(
                text("SELECT * FROM jd_candidates WHERE candidate_id=:c AND job_id=:j"),
                {"c": candidate_id, "j": job_id},
            )
            .mappings()
            .first()
        )
        if not link:
            raise AtsError("Choose an existing candidate membership in this JD.", 404)
        company = (
            conn.execute(text("SELECT * FROM companies WHERE id=:id"), {"id": job["company_id"]})
            .mappings()
            .one()
        )
        contacts = [r for r in json.loads(company["contacts_json"]) if not r.get("is_archived")]
        selected_id = contact_id or job.get("company_contact_id")
        if selected_id:
            contact = next((r for r in contacts if r["id"] == selected_id), None)
            if contact is None:
                if audience == "COMPANY":
                    raise AtsError("Choose an active recipient contact belonging to this company.")
                contact = {}
        else:
            contact = next(
                (r for r in contacts if r.get("is_primary_email") and r.get("email")), None
            ) or next((r for r in contacts if r.get("email")), {})
        disclosed = audience == "COMPANY" or link["stage_code"] in {"SELECTED", "JOINED"}
        company_name = company["company_name"] if disclosed else None
        greeting = (
            (contact.get("contact_name") or "Hiring team")
            if audience == "COMPANY"
            else candidate["full_name"]
        )
        subject = "Jobmitra · " + job["title"]
        body = (
            f"Dear {greeting},\n\n"
            + (
                f"Please review {candidate['full_name']} for {job['title']}."
                if audience == "COMPANY"
                else f"Your recruitment update for {job['title']} is ready for review."
            )
            + (
                f"\nCompany: {company_name}"
                if company_name
                else "\nClient company details remain confidential at this stage."
            )
            + "\n\nRegards,\nTeam Jobmitra"
        )
        job_title = job["title"]
        if not disclosed:

            def redact(value):
                return re.sub(
                    re.escape(company["company_name"]),
                    "the hiring company",
                    value,
                    flags=re.IGNORECASE,
                )

            body, subject, job_title = redact(body), redact(subject), redact(job_title)
        return {
            "audience": audience,
            "candidate_id": candidate_id,
            "job_id": job_id,
            "recipient_email": contact.get("email")
            if audience == "COMPANY"
            else candidate["email"],
            "recipient_name": greeting,
            "company_name": company_name,
            "candidate_name": candidate["full_name"],
            "experience_years": candidate["experience_years"],
            "notice_days": candidate["notice_days"],
            "current_salary_inr": candidate["current_salary_inr"],
            "current_salary_period": candidate["current_salary_period"],
            "current_salary_basis": candidate["current_salary_basis"],
            "expected_salary_inr": candidate["expected_salary_inr"],
            "expected_salary_period": candidate["expected_salary_period"],
            "expected_salary_basis": candidate["expected_salary_basis"],
            "job_title": job_title,
            "location": job["location"] if disclosed else None,
            "stage": link["stage_code"],
            "selection_outcome": link.get("selection_outcome"),
            "joined_on": link.get("joined_on"),
            "subject": subject,
            "body": body,
            "contacts": [
                {"id": r["id"], "name": r.get("contact_name"), "email": r.get("email")}
                for r in contacts
            ]
            if audience == "COMPANY"
            else [],
            "selected_contact_id": contact.get("id") if audience == "COMPANY" else None,
            "company_disclosed": disclosed,
            "sent": False,
            "delivery_enabled": False,
        }
