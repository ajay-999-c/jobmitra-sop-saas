"""Durable send claims/results in the existing immutable recruitment event log.

One logical history entry per reference, represented by an attempt and at most
one result fact. No schema migration, event update, or recruitment transition.
"""

import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from jobmitra.modules.ats_v2.common import AtsError, one, utc_now
from jobmitra.modules.ats_v2.database import transaction

from . import gmail_service as gmail

TEMPLATES = frozenset(
    {
        "jobmitra_screening",
        "screening_completed",
        "screening_cleared",
        "interview_scheduled",
        "technical_interview",
        "custom_round",
        "round1_completed",
        "round1_cleared",
        "round2_completed",
        "round2_cleared",
        "final_completed",
        "selected",
        "offer_received",
        "joined",
        "not_selected",
    }
)
ATTEMPT, RESULT = "EMAIL_SEND_ATTEMPT", "EMAIL_SEND_RESULT"


class SendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: UUID
    candidate_id: int = Field(gt=0)
    job_id: int | None = Field(default=None, gt=0)
    company_id: UUID | None = None
    template_id: str = Field(max_length=60)
    intended_recipient: str = Field(max_length=254)
    actual_recipient: str = Field(max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    html: str = Field(min_length=1, max_length=200_000)
    plain: str = Field(min_length=1, max_length=30_000)
    # Accepted for defensive stripping; never become MIME headers or history data.
    cc: list[str] = Field(default_factory=list, max_length=100)
    bcc: list[str] = Field(default_factory=list, max_length=100)
    resend_of: UUID | None = None
    confirm_resend: bool = False

    @field_validator("subject")
    @classmethod
    def single_subject(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a single-line email subject.")
        return value


def history(conn, candidate_id=None):
    rows = conn.execute(
        text(
            "SELECT * FROM recruitment_events WHERE event_type IN "
            "('EMAIL_SEND_ATTEMPT','EMAIL_SEND_RESULT') "
            + ("AND candidate_id=:candidate " if candidate_id else "")
            + "ORDER BY id"
        ),
        {"candidate": candidate_id},
    ).mappings()
    entries = {}
    for row in rows:
        payload = json.loads(row["payload_json"])
        ref = payload["email_reference"]
        if row["event_type"] == ATTEMPT:
            entries[ref] = {
                **payload,
                "created_at": row["created_at"],
                "candidate_id": row["candidate_id"],
                "job_id": row["job_id"],
                "jd_candidate_id": row["jd_candidate_id"],
            }
        elif ref in entries:
            entries[ref].update(payload)
    for entry in entries.values():
        # Crash after the durable claim is never permission to retry. Network calls
        # are bounded to 15s each; after two minutes a missing result is ambiguous.
        if entry["status"] == "Sending":
            age = datetime.now(UTC) - datetime.fromisoformat(
                entry["created_at"].replace("Z", "+00:00")
            )
            if age.total_seconds() > 120:
                entry.update(
                    status="Send outcome unknown",
                    failure_reason="Interrupted send; no automatic retry.",
                )
    return list(entries.values())


def public(entry):
    return {k: v for k, v in entry.items() if k != "fingerprint"}


def _append(conn, event_type, entry):
    conn.execute(
        text(
            "INSERT INTO recruitment_events(candidate_id,job_id,jd_candidate_id,event_type,"
            "payload_json) VALUES(:candidate,:job,:link,:type,:payload)"
        ),
        {
            "candidate": entry["candidate_id"],
            "job": entry["job_id"],
            "link": entry["jd_candidate_id"],
            "type": event_type,
            "payload": json.dumps(entry),
        },
    )


def _context(conn, settings, data):
    if data.template_id not in TEMPLATES:
        raise AtsError("This template remains manual in Gmail Phase 1.")
    candidate = one(conn, "candidates", data.candidate_id)
    # A test-recipient redirect must never leak a real candidate's data.
    if (candidate.get("email") or "").lower() != settings.gmail_test_recipient.lower() or candidate[
        "full_name"
    ].casefold().strip() != "pooja jobmitra":
        raise AtsError("Phase 1 sends require the existing Pooja Jobmitra sample candidate.", 403)
    if gmail.address(data.intended_recipient) != gmail.address(candidate["email"]):
        raise AtsError("The intended recipient must match the existing sample candidate.")
    if gmail.address(data.actual_recipient) != gmail.address(settings.gmail_test_recipient):
        raise AtsError("The confirmed test recipient cannot be overridden.", 403)
    if "pooja" not in data.plain.casefold() or "pooja" not in data.html.casefold():
        raise AtsError("Review the existing sample candidate's populated email preview.")
    link, company = None, None
    if data.job_id:
        allowed = {int(x) for x in settings.gmail_test_job_ids.split(",") if x.strip()}
        if data.job_id not in allowed:
            raise AtsError(
                "This JD is not explicitly approved as synthetic Gmail test context.", 403
            )
        job = one(conn, "job_descriptions", data.job_id)
        company = job["company_id"]
        link = conn.execute(
            text("SELECT id FROM jd_candidates WHERE job_id=:j AND candidate_id=:c"),
            {"j": data.job_id, "c": data.candidate_id},
        ).scalar_one_or_none()
        if link is None:
            raise AtsError("Candidate must belong to the specified test JD.", 409)
    if (str(data.company_id) if data.company_id else None) != company:
        raise AtsError("Company context must match the canonical test JD.")
    return link, company


def dispatch(engine, settings, data):
    gmail.validate_configuration(settings)
    if not settings.gmail_enabled:
        raise AtsError("Gmail sending is disabled.", 403)
    ref, digest = str(data.reference), gmail.fingerprint(data)
    # Serialize only the short claim transaction, never hold it over Gmail I/O.
    with transaction(engine) as conn:
        entries = history(conn)
        existing = next((e for e in entries if e["email_reference"] == ref), None)
        if existing:
            if existing["fingerprint"] != digest:
                raise AtsError("This send reference was already used for different content.", 409)
            return public(existing)
        previous = next((e for e in reversed(entries) if e["fingerprint"] == digest), None)
        if data.resend_of:
            prior = next((e for e in entries if e["email_reference"] == str(data.resend_of)), None)
            if (
                not data.confirm_resend
                or not prior
                or prior["candidate_id"] != data.candidate_id
                or prior["job_id"] != data.job_id
                or prior["status"] == "Sending"
            ):
                raise AtsError(
                    "Resend needs a separate confirmation of a completed/unknown attempt.", 409
                )
            # Two concurrent resend clicks with different references still share
            # one parent claim. Another resend must explicitly reference its result.
            child = next((e for e in entries if e.get("resend_of") == str(data.resend_of)), None)
            if child:
                if child["fingerprint"] != digest:
                    raise AtsError("This resend was already claimed with different content.", 409)
                return public(child)
        elif previous:
            return public(previous)
        link, company = _context(conn, settings, data)
        raw = gmail.message(settings, data, ref)  # validate before persisting a claim
        entry = {
            "email_reference": ref,
            "fingerprint": digest,
            "template_id": data.template_id,
            "candidate_id": data.candidate_id,
            "job_id": data.job_id,
            "company_id": company,
            "jd_candidate_id": link,
            "intended_recipient": data.intended_recipient,
            "actual_recipient": settings.gmail_test_recipient,
            "subject": data.subject,
            "test_mode": True,
            "sent_by": None,
            "actor_context": "Local Mac development; individual identity unverified",
            "status": "Sending",
            "sent_at": None,
            "gmail_message_id": None,
            "gmail_thread_id": None,
            "failure_reason": None,
            "resend_of": str(data.resend_of) if data.resend_of else None,
        }
        _append(conn, ATTEMPT, entry)
    # The claim is committed even if the process dies or the client disconnects.
    try:
        result = gmail.send(settings, raw)
        entry.update(
            status="Accepted by Gmail",
            sent_at=utc_now(),
            gmail_message_id=result["message_id"],
            gmail_thread_id=result["thread_id"],
        )
    except gmail.GmailError as error:
        entry.update(
            status="Send outcome unknown" if error.unknown else "Failed",
            failure_reason=error.reason,
            reconnect_required=error.reconnect,
        )
    with transaction(engine) as conn:
        _append(conn, RESULT, entry)
    return public(entry)
