"""Auditable accidental-attachment correction in the existing immutable event ledger.

No membership/profile/event deletion or new stage. The latest REMOVE/RESTORE event
controls participation; the original Contact membership remains available to history.
"""

import hashlib
import json
from uuid import UUID

from pydantic import Field
from sqlalchemy import text

from .common import AtsError, one
from .database import transaction
from .schemas import Input

REMOVE = "ATTACHMENT_REMOVED"
RESTORE = "ATTACHMENT_RESTORED"


def removed_sql(alias):
    if alias not in {"l", "jc"}:
        raise ValueError("Unsupported membership alias")
    return (
        "EXISTS (SELECT 1 FROM recruitment_events removed_event WHERE "
        f"removed_event.jd_candidate_id={alias}.id AND removed_event.event_type='{REMOVE}' "
        "AND NOT EXISTS (SELECT 1 FROM recruitment_events restored_event WHERE "
        "restored_event.jd_candidate_id=removed_event.jd_candidate_id AND "
        f"restored_event.event_type='{RESTORE}' AND restored_event.id>removed_event.id))"
    )


def is_removed(conn, link_id):
    return bool(
        conn.scalar(
            text("SELECT " + removed_sql("l") + " FROM jd_candidates l WHERE l.id=:l"),
            {"l": link_id},
        )
    )


def facts(conn, job_id, link_id):
    job, link = one(conn, "job_descriptions", job_id), one(conn, "jd_candidates", link_id)
    if link["job_id"] != job_id:
        raise AtsError("Candidate participation not found in this JD.", 404)
    events = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT id,event_type,from_stage,to_stage,feedback,payload_json "
                "FROM recruitment_events "
                "WHERE jd_candidate_id=:l OR (job_id=:j AND candidate_id=:c) ORDER BY id"
            ),
            {"l": link_id, "j": job_id, "c": link["candidate_id"]},
        ).mappings()
    ]
    activity = conn.scalar(
        text("SELECT count(*) FROM candidate_activities WHERE job_id=:j AND candidate_id=:c"),
        {"j": job_id, "c": link["candidate_id"]},
    )
    # Unknown/imported activity is deliberately not assumed to be an empty history.
    genuine = [
        e
        for e in events
        if not (
            e["event_type"] in {"ADDED", "POOL_ADDED", "REQUEST_COMPLETED", REMOVE, RESTORE}
            or (
                e["event_type"] == "MOVED"
                and e["from_stage"] == "POOL"
                and e["to_stage"] == "CONTACT"
                and not e["feedback"]
            )
        )
    ]
    initial = [e for e in events if e["event_type"] in {"ADDED", "POOL_ADDED"}]
    contact = [e for e in events if e["event_type"] == "MOVED"]
    safe = (
        link["stage_code"] == "CONTACT"
        and not link.get("round_id")
        and not link.get("selection_outcome")
        and not link.get("stage_note")
        and len(initial) == 1
        and len(contact) == 1
        and not genuine
        and not activity
    )
    removed = is_removed(conn, link_id)
    reason = (
        "This JD is not active; historical participation is retained."
        if job["status"] != "ACTIVE"
        else "Recruitment activity exists beyond attachment and automatic Contact entry. "
        "Use the appropriate recruitment outcome; ordinary removal is blocked."
        if not safe
        else ""
    )
    revision = hashlib.sha256(
        json.dumps([job["status"], link, events, activity], sort_keys=True, default=str).encode()
    ).hexdigest()
    return {
        "removed": removed,
        "allowed": not reason,
        "reason": reason,
        "revision": revision,
        "link_id": link_id,
        "candidate_id": link["candidate_id"],
    }


class Correction(Input):
    idempotency_key: UUID
    expected_revision: str = Field(min_length=64, max_length=64)
    action: str = Field(pattern="^(REMOVE|RESTORE)$")
    reason: str = Field(min_length=3, max_length=1000)


def correct(engine, job_id, link_id, data, role):
    from . import request_receipts as receipts
    from . import unified

    with transaction(engine) as conn:
        prior = conn.execute(
            text(
                "SELECT payload_json FROM recruitment_events WHERE "
                "json_extract(payload_json,'$.correction_key')=:k"
            ),
            {"k": str(data.idempotency_key)},
        ).scalar_one_or_none()
        fingerprint = receipts.digest(
            "attachment-correction", [job_id, link_id, data.model_dump(mode="json")]
        )
        if prior:
            if json.loads(prior).get("fingerprint") != fingerprint:
                raise AtsError("This action reference was used for a different correction.", 409)
            return facts(conn, job_id, link_id)
        current = facts(conn, job_id, link_id)
        if current["revision"] != data.expected_revision:
            raise AtsError("Participation changed. Reload and review before correcting it.", 409)
        if not current["allowed"]:
            raise AtsError(current["reason"], 409)
        if current["removed"] != (data.action == "RESTORE"):
            raise AtsError("The attachment already has this state. Reload before continuing.", 409)
        if data.action == "RESTORE":
            candidate = one(conn, "candidates", current["candidate_id"])
            if not candidate["is_active"]:
                raise AtsError("Inactive candidates cannot be restored to a JD.", 409)
            unified.require_available(conn, candidate["id"])
        conn.execute(
            text(
                "INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,"
                "event_type,payload_json) VALUES(:j,:c,:l,:type,:payload)"
            ),
            {
                "j": job_id,
                "c": current["candidate_id"],
                "l": link_id,
                "type": REMOVE if data.action == "REMOVE" else RESTORE,
                "payload": json.dumps(
                    {
                        "correction_key": str(data.idempotency_key),
                        "fingerprint": fingerprint,
                        "reason": data.reason,
                        "actor_role": role,
                        "employee_id": None,
                        "individual_authenticated": False,
                    }
                ),
            },
        )
        return facts(conn, job_id, link_id)


class CloseJD(Input):
    idempotency_key: UUID
    expected_revision: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=1000)
    confirmed: bool


def close_job(engine, job_id, data, role):
    from . import request_receipts as receipts
    from .workspace_store import revision

    with transaction(engine) as conn:
        fingerprint = receipts.digest("close-jd", [job_id, data.model_dump(mode="json")])
        prior = conn.scalar(
            text(
                "SELECT payload_json FROM recruitment_events WHERE "
                "json_extract(payload_json,'$.closure_key')=:k"
            ),
            {"k": str(data.idempotency_key)},
        )
        if prior:
            if json.loads(prior).get("fingerprint") != fingerprint:
                raise AtsError("This action reference was already used.", 409)
            return {"id": job_id, "status": "CLOSED", "replayed": True}
        job = one(conn, "job_descriptions", job_id)
        if not data.confirmed:
            raise AtsError("Explicit closure confirmation is required.")
        if revision(job) != data.expected_revision:
            raise AtsError("This JD changed. Reload and review before closing it.", 409)
        if job["status"] == "CLOSED":
            raise AtsError("This JD is already closed.", 409)
        conn.execute(text("UPDATE job_descriptions SET status='CLOSED' WHERE id=:j"), {"j": job_id})
        conn.execute(
            text(
                "INSERT INTO recruitment_events(job_id,event_type,payload_json) "
                "VALUES(:j,'JD_CLOSED',:p)"
            ),
            {
                "j": job_id,
                "p": json.dumps(
                    {
                        "closure_key": str(data.idempotency_key),
                        "fingerprint": fingerprint,
                        "reason": data.reason,
                        "actor_role": role,
                        "employee_id": None,
                        "individual_authenticated": False,
                    }
                ),
            },
        )
        return {"id": job_id, "status": "CLOSED", "replayed": False}
