"""Reviewed full-profile changes; identity, source evidence and history remain canonical."""

import hashlib
import json
import re
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text

from . import candidates, profile_store
from .candidate_schemas import CandidateCreate, CandidatePatch
from .common import AtsError, one, utc_now
from .database import insert_result, transaction


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Employment(Strict):
    employer: str = Field(max_length=300)
    job_title: str = Field(max_length=300)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    responsibilities: str = Field(default="", max_length=10000)
    achievements: str = Field(default="", max_length=10000)
    experience_months: int | None = Field(default=None, ge=0, le=1200)

    @field_validator("start_date", "end_date")
    @classmethod
    def partial_date(cls, value):
        if value:
            if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", value):
                raise ValueError("Use YYYY, YYYY-MM or YYYY-MM-DD")
            date.fromisoformat(
                value + ("-01-01" if len(value) == 4 else "-01" if len(value) == 7 else "")
            )
        return value

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date[: len(self.end_date)]
        ):
            raise ValueError("Employment end precedes start")
        return self


class Education(Strict):
    institution: str = Field(default="", max_length=300)
    qualification: str = Field(max_length=300)
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("Education end precedes start")
        return self


class Certification(Strict):
    name: str = Field(max_length=300)
    issuer: str = Field(default="", max_length=300)
    issued_on: str | None = Field(default=None, max_length=10)

    @field_validator("issued_on")
    @classmethod
    def issued(cls, value):
        return Employment.partial_date(value)


class Project(Strict):
    name: str = Field(max_length=300)
    role: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=10000)


class Extra(Strict):
    registration_purpose: str | None = Field(default=None, max_length=2000)
    hometown: str | None = Field(default=None, max_length=200)
    home_state: str | None = Field(default=None, max_length=200)
    subdomain: str | None = Field(default=None, max_length=200)
    ready_to_relocate: bool | None = None
    experience_months: int | None = Field(default=None, ge=0, le=1200)
    notice_period_text: str | None = Field(default=None, max_length=1000)
    employment_history: list[Employment] = Field(default_factory=list, max_length=100)
    education_history: list[Education] = Field(default_factory=list, max_length=100)
    certifications: list[Certification] = Field(default_factory=list, max_length=100)
    projects: list[Project] = Field(default_factory=list, max_length=100)


class CompletePatch(CandidatePatch):
    current_salary_inr: Decimal | None = Field(
        default=None, ge=0, le=10**10, max_digits=16, decimal_places=4
    )
    expected_salary_inr: Decimal | None = Field(
        default=None, ge=0, le=10**10, max_digits=16, decimal_places=4
    )


class CompleteCreate(CandidateCreate):
    current_salary_inr: Decimal | None = Field(
        default=None, ge=0, le=10**10, max_digits=16, decimal_places=4
    )
    expected_salary_inr: Decimal | None = Field(
        default=None, ge=0, le=10**10, max_digits=16, decimal_places=4
    )


class Review(Strict):
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    expected_revision: str = Field(min_length=64, max_length=64)
    changes: CompletePatch
    extra: Extra = Field(default_factory=Extra)
    approved_fields: list[str] = Field(max_length=100)
    notice_days_verified: bool = False
    source_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Intake(Strict):
    idempotency_key: UUID
    actor_name: str = Field(min_length=1, max_length=120)
    candidate: CompleteCreate
    extra: Extra = Field(default_factory=Extra)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    separate_person_reason: str = Field(default="", max_length=2000)
    confirmed: Literal[True]


def ensure(conn):
    if not profile_store.installed(conn):
        raise AtsError(
            "Full Candidate Details requires the explicit isolated profile extension.", 503
        )


def _latest(conn, cid):
    return (
        conn.execute(
            text(
                "SELECT * FROM candidate_profile_versions WHERE candidate_id=:c ORDER "
                "BY id DESC LIMIT 1"
            ),
            {"c": cid},
        )
        .mappings()
        .first()
    )


def _reviewed_extra(candidate, profile_json, registration_json, evidence):
    extra = {
        k: candidate.get(k)
        for k in [
            "hometown",
            "home_state",
            "ready_to_relocate",
            "experience_months",
            "notice_period_text",
        ]
        if candidate.get(k) is not None
    }
    if profile_json:
        extra.update(json.loads(profile_json))
    if registration_json:
        original = json.loads(registration_json)
        if "registration_purpose" not in extra:
            extra["registration_purpose"] = original.get("registration_purpose")
        if "notice_period_text" not in extra and original.get("notice_text"):
            extra["notice_period_text"] = original["notice_text"]
    for item in evidence:
        for name, aliases in {
            "employment_history": ["employment_history", "work_experience"],
            "education_history": ["education_history", "education", "qualifications"],
            "projects": ["projects"],
            "certifications": ["certifications"],
        }.items():
            if name in extra:
                continue
            for alias in aliases:
                if alias not in item:
                    continue
                try:
                    extra[name] = Extra.model_validate({name: item[alias]}).model_dump(mode="json")[
                        name
                    ]
                except ValueError:
                    pass  # Preserve incompatible historical evidence without coercion.
                break
    return extra


def _state(conn, cid):
    ensure(conn)
    row = one(conn, "candidates", cid)
    candidate = candidates.candidate_dict(row)
    latest = _latest(conn, cid)
    original = conn.execute(
        text(
            "SELECT payload_json FROM recruitment_events WHERE candidate_id=:c "
            "AND event_type='REGISTRATION_DETAILS' ORDER BY id LIMIT 1"
        ),
        {"c": cid},
    ).scalar()
    evidence = []
    for (parsed,) in conn.execute(
        text(
            "SELECT parsed_json FROM candidate_resumes WHERE candidate_id=:c "
            "AND resume_kind='PARSED_TEXT' AND is_current=1"
        ),
        {"c": cid},
    ):
        value = json.loads(parsed or "{}")
        if value.get("facts_reviewed"):
            evidence.append(value.get("profile", {}))
    extra = _reviewed_extra(
        candidate, latest["profile_json"] if latest else None, original, evidence
    )
    for key in ["current_salary_inr", "expected_salary_inr"]:
        if candidate[key] is not None:
            candidate[key] = str(candidate[key])
    revision = hashlib.sha256(
        json.dumps([row, latest["id"] if latest else None], sort_keys=True, default=str).encode()
    ).hexdigest()
    return {
        "candidate": candidate,
        "extra": extra,
        "revision": revision,
        "reviewed_resume_evidence": evidence,
        "profile_version_id": latest["id"] if latest else None,
    }


def postgres_bootstrap_extras(conn, people):
    """Three bounded reads replace the per-person queries over a networked store."""
    if conn.dialect.name != "postgresql":
        raise ValueError("PostgreSQL bootstrap only")
    latest = dict(
        conn.execute(
            text(
                "SELECT DISTINCT ON (candidate_id) candidate_id,profile_json "
                "FROM candidate_profile_versions "
                "ORDER BY candidate_id,id DESC"
            )
        ).all()
    )
    registrations = dict(
        conn.execute(
            text(
                "SELECT DISTINCT ON (candidate_id) candidate_id,payload_json "
                "FROM recruitment_events "
                "WHERE event_type='REGISTRATION_DETAILS' ORDER BY candidate_id,id"
            )
        ).all()
    )
    evidence = {}
    for cid, parsed in conn.execute(
        text(
            "SELECT candidate_id,parsed_json FROM candidate_resumes "
            "WHERE resume_kind='PARSED_TEXT' AND is_current=1 ORDER BY id"
        )
    ):
        value = json.loads(parsed or "{}")
        if value.get("facts_reviewed"):
            evidence.setdefault(cid, []).append(value.get("profile", {}))
    return {
        p["id"]: _reviewed_extra(
            p, latest.get(p["id"]), registrations.get(p["id"]), evidence.get(p["id"], [])
        )
        for p in people
    }


def get(engine, cid):
    with engine.connect() as conn:
        return _state(conn, cid)


def matches(conn, person):
    values = candidates._db_values(person)
    parts = []
    params = {}
    for field in ["phone_normalized", "email_normalized"]:
        if values.get(field):
            parts.append(field + "=:" + field)
            params[field] = values[field]
    if not parts:
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT id,candidate_code,full_name,phone,email FROM candidates WHERE "
                + " OR ".join(parts)
            ),
            params,
        ).mappings()
    ]


def _digest(data, scope):
    return hashlib.sha256(
        json.dumps([scope, data.model_dump(mode="json")], sort_keys=True).encode()
    ).hexdigest()


def _prior(conn, data, digest):
    row = conn.execute(
        text(
            "SELECT candidate_id,request_hash FROM candidate_profile_versions WHERE request_key=:k"
        ),
        {"k": str(data.idempotency_key)},
    ).first()
    if row and row[1] != digest:
        raise AtsError("Request key already used for different profile changes.", 409)
    return row[0] if row else None


def _values(person):
    values = candidates._db_values(person)
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in values.items()}


def _salary_check(conn, cid, person):
    row = one(conn, "candidates", cid)
    for key in ["current_salary_inr", "expected_salary_inr"]:
        if key in person.model_fields_set and getattr(person, key) is not None:
            if Decimal(str(row[key])) != getattr(person, key):
                raise AtsError(
                    "This salary could not be stored without losing precision. "
                    "No changes were saved."
                )


def _record(conn, cid, data, role, before, extra, provenance, digest):
    core = candidates.candidate_dict(one(conn, "candidates", cid))
    after = {"candidate": core, "extra": extra}
    conn.execute(
        text(
            "INSERT INTO "
            "candidate_profile_versions(candidate_id,profile_json,before_json,after_json,"
            "provenance_json,actor_name,actor_role,created_at,request_key,request_hash) "
            "VALUES(:cid,:profile,:before,:after,:provenance,:actor,:role,:now,:key,:digest)"
        ),
        {
            "cid": cid,
            "profile": json.dumps(extra),
            "before": json.dumps(before, default=str),
            "after": json.dumps(after, default=str),
            "provenance": json.dumps(provenance),
            "actor": data.actor_name,
            "role": role,
            "now": utc_now(),
            "key": str(data.idempotency_key),
            "digest": digest,
        },
    )
    conn.execute(
        text(
            "INSERT INTO "
            "recruitment_events(candidate_id,event_type,before_json,after_json,payload_json) "
            "VALUES(:id,'CANDIDATE_PROFILE_REVIEWED',:before,:after,:payload)"
        ),
        {
            "id": cid,
            "before": json.dumps(before, default=str),
            "after": json.dumps(after, default=str),
            "payload": json.dumps(
                {
                    "actor_name": data.actor_name,
                    "actor_role": role,
                    "idempotency_key": str(data.idempotency_key),
                    "provenance": provenance,
                }
            ),
        },
    )
    candidates.rebuild_search(conn, cid)


def save(engine, cid, data, role, *, connection=None):
    digest = _digest(data, ["profile", cid])
    with nullcontext(connection) if connection is not None else transaction(engine) as conn:
        ensure(conn)
        if _prior(conn, data, digest):
            return _state(conn, cid)
        old = _state(conn, cid)
        if old["revision"] != data.expected_revision:
            raise AtsError(
                "Candidate changed. Reload before saving; no fields were overwritten.", 409
            )
        changes = data.changes.model_dump(exclude_unset=True)
        extra_changes = data.extra.model_dump(mode="json", exclude_unset=True)
        required = set(changes) | {"extra:" + k for k in extra_changes}
        if not required <= set(data.approved_fields):
            raise AtsError("Approve every changed field explicitly.")
        if (
            "notice_days" in changes
            and changes["notice_days"] is not None
            and not data.notice_days_verified
        ):
            raise AtsError(
                "Confirm normalized notice days separately; original notice text is retained."
            )
        values = _values(data.changes)
        candidates._duplicates(conn, values, cid)
        if values:
            conn.execute(
                text(
                    "UPDATE candidates SET "
                    + ",".join(k + "=:" + k for k in values)
                    + " WHERE id=:cid"
                ),
                {**values, "cid": cid},
            )
        _salary_check(conn, cid, data.changes)
        extra = {**old["extra"], **extra_changes}
        if (
            "experience_years" in changes
            and "experience_months" not in extra_changes
            and extra.get("experience_months") is not None
            and (
                changes["experience_years"] is None
                or abs(changes["experience_years"] - extra["experience_months"] / 12) > 1e-9
            )
        ):
            raise AtsError(
                "Update or explicitly clear verified experience months with the years value."
            )
        if "experience_months" in extra_changes and extra_changes["experience_months"] is not None:
            if "experience_years" not in changes:
                conn.execute(
                    text("UPDATE candidates SET experience_years=:y WHERE id=:c"),
                    {"y": extra_changes["experience_months"] / 12, "c": cid},
                )
            elif abs(changes["experience_years"] - extra_changes["experience_months"] / 12) > 1e-9:
                raise AtsError("Reviewed experience years and months disagree.")
        _record(
            conn,
            cid,
            data,
            role,
            old,
            extra,
            {
                "source_digest": data.source_digest,
                "approved_fields": sorted(required),
                "method": "RECRUITER_REVIEW",
            },
            digest,
        )
        return _state(conn, cid)


def intake(engine, data, role):
    digest = _digest(data, "foundit-register")
    with transaction(engine) as conn:
        ensure(conn)
        prior = _prior(conn, data, digest)
        if prior:
            return _state(conn, prior)
        if data.candidate.source != "FOUNDIT_PASTE":
            raise AtsError("Foundit intake must retain Foundit provenance.")
        if not (data.candidate.phone or data.candidate.email):
            raise AtsError("Review at least one verified contact before registration.")
        possible = matches(conn, data.candidate)
        if possible and len(data.separate_person_reason.strip()) < 10:
            raise AtsError(
                "Review matching identities or give a separate-person justification.", 409
            )
        values = _values(data.candidate)
        values["candidate_code"] = "ATS-" + uuid4().hex[:16].upper()
        cid = insert_result(
            conn,
            text(
                "INSERT INTO candidates("
                + ",".join(values)
                + ") VALUES("
                + ",".join(":" + k for k in values)
                + ")"
            ),
            values,
        ).lastrowid
        _salary_check(conn, cid, data.candidate)
        extra = data.extra.model_dump(mode="json", exclude_unset=True)
        if extra.get("experience_months") is not None:
            conn.execute(
                text("UPDATE candidates SET experience_years=:y WHERE id=:c"),
                {"y": extra["experience_months"] / 12, "c": cid},
            )
        _record(
            conn,
            cid,
            data,
            role,
            {},
            extra,
            {
                "source_digest": data.source_digest,
                "method": "FOUNDIT_REVIEWED",
                "separate_person_reason": data.separate_person_reason,
                "matched_ids": [p["id"] for p in possible],
            },
            digest,
        )
        return _state(conn, cid)
