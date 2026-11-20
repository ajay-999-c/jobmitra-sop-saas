"""Immutable company proposal versions and explicit, attributed evidence events."""

import base64
import hashlib
import io
import json
import os
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pypdf import PdfReader
from sqlalchemy import text

from . import proposal, proposal_pdf, proposal_store, unified
from .common import AtsError, utc_now
from .database import transaction

MAX_PDF = 10 * 1024 * 1024


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    actor_name: str = Field(min_length=1, max_length=120)
    idempotency_key: UUID

    @field_validator("*", mode="before")
    @classmethod
    def no_controls(cls, value):
        if isinstance(value, str) and re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value):
            raise ValueError("Control characters are not allowed.")
        return value


class Generate(Input):
    company_contact_id: UUID | None = None
    recipient_email: str | None = Field(default=None, max_length=254)
    consultant: str = Field(default=proposal_pdf.CONSULTANT, min_length=1, max_length=200)
    issue_date: date
    reference: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9 /_.-]*$")
    fee_percent: Literal["6", "8.33"]
    annual_ctc: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2)

    @field_validator("recipient_email")
    @classmethod
    def email(cls, value):
        if value is None:
            return None
        return unified.ContactEmail.valid_email(value) or ""


class SignedUpload(Input):
    filename: str = Field(min_length=1, max_length=200)
    file_base64: str = Field(min_length=1, max_length=14_000_000)


class StatusChange(Input):
    status: Literal["SENT", "ACCEPTED", "DECLINED"]
    expected_event_id: UUID | None = None
    evidence: str = Field(min_length=5, max_length=3000)
    effective_date: date
    signed_document_id: UUID | None = None
    authorized_signatory: str = Field(default="", max_length=200)
    confirmed: Literal[True]


def ready(engine, settings):
    if not settings.unified_v12_proposals_enabled or not settings.unified_v12_proposal_storage_root:
        raise AtsError("PDF proposal workflow is not enabled for this store.", 503)
    with engine.connect() as conn:
        if not proposal_store.installed(conn):
            raise AtsError(
                "The optional proposal extension needs an explicit isolated install.", 503
            )


def _fingerprint(data, scope):
    return hashlib.sha256(
        json.dumps(
            [scope, data.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _retry(conn, table, data, digest):
    row = (
        conn.execute(
            text(f"SELECT * FROM {table} WHERE request_key=:k"), {"k": str(data.idempotency_key)}
        )
        .mappings()
        .first()
    )
    if row and row["request_hash"] != digest:
        raise AtsError("This request key was already used for different proposal details.", 409)
    return dict(row) if row else None


def _insert(conn, table, values):
    conn.execute(
        text(
            f"INSERT INTO {table}("
            + ",".join(values)
            + ") VALUES("
            + ",".join(":" + key for key in values)
            + ")"
        ),
        values,
    )


def _root(root):
    root = Path(root).absolute()
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise AtsError("Proposal storage must not contain symlinks.", 503)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise AtsError("Proposal storage must be a private directory (mode 700).", 503)
    return root


def _publish(root, key, blob):
    root = _root(root)
    if not re.fullmatch(r"[a-f0-9-]{36}\.pdf", key):
        raise AtsError("Invalid private proposal key.", 503)
    path = root / key
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _discard_unreferenced(engine, path):
    # A commit I/O error can leave its outcome uncertain. Retain bytes unless a
    # fresh read proves there is no committed reference; never delete on doubt.
    try:
        with engine.connect() as conn:
            referenced = conn.execute(
                text(
                    "SELECT 1 FROM company_proposals WHERE pdf_key=:key UNION ALL "
                    "SELECT 1 FROM company_proposal_signed_documents WHERE storage_key=:key"
                ),
                {"key": path.name},
            ).first()
    except Exception:
        return
    if not referenced:
        path.unlink(missing_ok=True)


def _read(root, key, checksum, size):
    root = _root(root)
    if not re.fullmatch(r"[a-f0-9-]{36}\.pdf", key):
        raise AtsError("Invalid private document reference.", 503)
    path = root / key
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_nlink != 1 or stat.st_size != size:
                raise AtsError("Stored PDF verification failed.", 503)
            blob = stream.read(MAX_PDF + 1)
    except OSError:
        raise AtsError("Private PDF is unavailable.", 503) from None
    if len(blob) > MAX_PDF or hashlib.sha256(blob).hexdigest() != checksum:
        raise AtsError("Stored PDF checksum verification failed.", 503)
    return blob


def _get(conn, company_id, proposal_id):
    row = (
        conn.execute(
            text("SELECT * FROM company_proposals WHERE id=:p AND company_id=:c"),
            {"p": proposal_id, "c": company_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise AtsError("Proposal not found for this company.", 404)
    return dict(row)


def _public(conn, row):
    events = [
        dict(e)
        for e in conn.execute(
            text(
                "SELECT * FROM company_proposal_status_events WHERE proposal_id=:id ORDER BY rowid"
            ),
            {"id": row["id"]},
        ).mappings()
    ]
    signed = [
        dict(s)
        for s in conn.execute(
            text(
                "SELECT * FROM company_proposal_signed_documents "
                "WHERE proposal_id=:id ORDER BY rowid"
            ),
            {"id": row["id"]},
        ).mappings()
    ]
    private = {"storage_key", "request_hash", "request_key"}
    return {
        **{k: v for k, v in row.items() if k not in private | {"pdf_key", "snapshot_json"}},
        "snapshot": json.loads(row["snapshot_json"]),
        "status": events[-1]["status"] if events else "PREPARED",
        "latest_event_id": events[-1]["id"] if events else None,
        "events": [{k: v for k, v in e.items() if k not in private} for e in events],
        "signed_documents": [{k: v for k, v in s.items() if k not in private} for s in signed],
    }


def history(engine, company_id):
    proposal.context(engine, company_id)
    with engine.connect() as conn:
        return {
            "company_id": company_id,
            "items": [
                _public(conn, dict(r))
                for r in conn.execute(
                    text(
                        "SELECT * FROM company_proposals WHERE company_id=:c "
                        "ORDER BY created_at DESC,rowid DESC"
                    ),
                    {"c": company_id},
                ).mappings()
            ],
        }


def generate(engine, company_id, data, role, root):
    digest = _fingerprint(data, ["generate", company_id])
    path = None
    try:
        with transaction(engine) as conn:
            prior = _retry(conn, "company_proposals", data, digest)
            if prior:
                _read(root, prior["pdf_key"], prior["pdf_sha256"], prior["pdf_size"])
                return _public(conn, prior)
            ctx = proposal.context(
                engine,
                company_id,
                str(data.company_contact_id) if data.company_contact_id else None,
            )
            if not data.company_contact_id and ctx["company_contact_id"]:
                # Explicitly snapshot the actual default active contact, never an identity by name.
                data_contact = ctx["company_contact_id"]
            else:
                data_contact = str(data.company_contact_id) if data.company_contact_id else None
            pid = str(uuid4())
            reference = data.reference or f"JM-{data.issue_date:%Y%m%d}-{pid[:8].upper()}"
            snap = {
                "company_id": company_id,
                "company_name": ctx["company_name"],
                "company_contact_id": data_contact,
                "contact_name": ctx["contact_name"],
                "recipient_email": (
                    data.recipient_email
                    if data.recipient_email is not None
                    else ctx["recipient_email"]
                ),
                "consultant": data.consultant,
                "reference": reference,
                "issue_date": data.issue_date.isoformat(),
                "fee_percent": data.fee_percent,
                "annual_ctc": str(data.annual_ctc) if data.annual_ctc else None,
                "fee_amount": str(
                    (data.annual_ctc * Decimal(data.fee_percent) / 100).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                )
                if data.annual_ctc
                else None,
                "clauses": proposal_pdf.clauses(data.fee_percent),
                "terms_source_sha256": proposal_pdf.TERMS["source_sha256"],
                "pdf_renderer": 1,
            }
            blob = proposal_pdf.render(snap)
            key = pid + ".pdf"
            path = _publish(root, key, blob)
            row = {
                "id": pid,
                "company_id": company_id,
                "contact_id": data_contact,
                "reference": reference,
                "issue_date": snap["issue_date"],
                "fee_basis_points": int(Decimal(data.fee_percent) * 100),
                "snapshot_json": json.dumps(snap),
                "pdf_key": key,
                "pdf_sha256": hashlib.sha256(blob).hexdigest(),
                "pdf_size": len(blob),
                "created_at": utc_now(),
                "prepared_by": data.actor_name,
                "actor_role": role,
                "request_key": str(data.idempotency_key),
                "request_hash": digest,
            }
            _insert(conn, "company_proposals", row)
            result = _public(conn, row)
        return result
    except Exception:
        if path is not None:
            _discard_unreferenced(engine, path)
        raise


def validate_pdf(blob, filename):
    if (
        not filename.lower().endswith(".pdf")
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or not 1 <= len(blob) <= MAX_PDF
    ):
        raise AtsError("Choose a PDF up to 10 MB with a plain filename.")
    if not blob.startswith(b"%PDF-") or b"%%EOF" not in blob[-2048:]:
        raise AtsError("The upload is not a complete PDF.")
    try:
        reader = PdfReader(io.BytesIO(blob), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
            raise ValueError("Unsupported PDF")
        # Preserve signed bytes. Reject active content rather than rewrite/sanitize a signature.
        seen = set()

        def inspect(node, depth=0):
            if depth > 50:
                raise ValueError("Overly complex PDF")
            if hasattr(node, "get_object"):
                node = node.get_object()
            marker = id(node)
            if marker in seen:
                return
            seen.add(marker)
            if isinstance(node, dict):
                if any(
                    k in node for k in ["/JS", "/JavaScript", "/EmbeddedFiles", "/RichMediaContent"]
                ):
                    raise ValueError("Active content")
                if str(node.get("/S", "")) in {
                    "/Launch",
                    "/JavaScript",
                    "/SubmitForm",
                    "/ImportData",
                }:
                    raise ValueError("Active action")
                for v in node.values():
                    inspect(v, depth + 1)
            elif isinstance(node, list):
                for v in node:
                    inspect(v, depth + 1)

        inspect(reader.trailer)
    except Exception:
        raise AtsError(
            "PDF could not be validated; encrypted, active or damaged files are refused."
        ) from None


def upload_signed(engine, company_id, proposal_id, data, role, root):
    try:
        blob = base64.b64decode(data.file_base64, validate=True)
    except ValueError:
        raise AtsError("Invalid PDF upload encoding.") from None
    validate_pdf(blob, data.filename)
    digest = _fingerprint(data, ["signed", company_id, proposal_id])
    path = None
    try:
        with transaction(engine) as conn:
            _get(conn, company_id, proposal_id)
            prior = _retry(conn, "company_proposal_signed_documents", data, digest)
            if not prior:
                sid = str(uuid4())
                key = sid + ".pdf"
                path = _publish(root, key, blob)
                _insert(
                    conn,
                    "company_proposal_signed_documents",
                    {
                        "id": sid,
                        "proposal_id": proposal_id,
                        "storage_key": key,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "size": len(blob),
                        "original_filename": data.filename,
                        "uploaded_at": utc_now(),
                        "uploaded_by": data.actor_name,
                        "actor_role": role,
                        "request_key": str(data.idempotency_key),
                        "request_hash": digest,
                    },
                )
            result = _public(conn, _get(conn, company_id, proposal_id))
        return result
    except Exception:
        if path is not None:
            _discard_unreferenced(engine, path)
        raise


def set_status(engine, company_id, proposal_id, data, role):
    digest = _fingerprint(data, ["status", company_id, proposal_id])
    with transaction(engine) as conn:
        row = _get(conn, company_id, proposal_id)
        if _retry(conn, "company_proposal_status_events", data, digest):
            return _public(conn, row)
        current = _public(conn, row)
        expected = str(data.expected_event_id) if data.expected_event_id else None
        if current["latest_event_id"] != expected:
            raise AtsError("Proposal history changed. Reload before recording a status.", 409)
        if current["status"] in {"ACCEPTED", "DECLINED"} or current["status"] == data.status:
            raise AtsError(
                "This proposal status transition is not available. Prepare a new version.", 409
            )
        if (
            not date.fromisoformat(row["issue_date"])
            <= data.effective_date
            <= unified.office_today()
        ):
            raise AtsError("Evidence date must be between issue date and today.")
        if data.status == "ACCEPTED":
            signed = conn.execute(
                text(
                    "SELECT id FROM company_proposal_signed_documents "
                    "WHERE id=:id AND proposal_id=:p"
                ),
                {"id": str(data.signed_document_id), "p": proposal_id},
            ).first()
            if not signed or not data.authorized_signatory:
                raise AtsError(
                    "Acceptance requires this proposal's signed PDF and authorized signatory."
                )
        elif data.signed_document_id or data.authorized_signatory:
            raise AtsError("Signed acceptance details belong only to an Accepted action.")
        _insert(
            conn,
            "company_proposal_status_events",
            {
                "id": str(uuid4()),
                "proposal_id": proposal_id,
                "status": data.status,
                "evidence": data.evidence,
                "effective_date": data.effective_date.isoformat(),
                "authorized_signatory": data.authorized_signatory or None,
                "signed_document_id": str(data.signed_document_id)
                if data.signed_document_id
                else None,
                "created_at": utc_now(),
                "recorded_by": data.actor_name,
                "actor_role": role,
                "request_key": str(data.idempotency_key),
                "request_hash": digest,
            },
        )
        return _public(conn, row)


def document(engine, company_id, proposal_id, root, signed_id=None):
    with engine.connect() as conn:
        row = _get(conn, company_id, proposal_id)
        if signed_id:
            signed = (
                conn.execute(
                    text(
                        "SELECT * FROM company_proposal_signed_documents "
                        "WHERE id=:id AND proposal_id=:p"
                    ),
                    {"id": signed_id, "p": proposal_id},
                )
                .mappings()
                .first()
            )
            if not signed:
                raise AtsError("Signed document not found for this proposal.", 404)
            return _read(root, signed["storage_key"], signed["sha256"], signed["size"])
        return _read(root, row["pdf_key"], row["pdf_sha256"], row["pdf_size"])


def email(engine, company_id, proposal_id):
    with engine.connect() as conn:
        s = json.loads(_get(conn, company_id, proposal_id)["snapshot_json"])
    greeting = "Dear " + s["contact_name"] + "," if s["contact_name"] else "Dear Sir/Madam,"
    body = (
        f"{greeting}\n\nGreetings from Jobmitra!\n\nAs discussed, please find attached our "
        f"Recruitment Services Proposal & Terms of Engagement for {s['company_name']}.\n\n"
        "Kindly review the proposed service fee and Terms & Conditions. "
        "If everything is acceptable, please share a signed copy for our records.\n\n"
        "We look forward to working with your team.\n\nBest regards,\nVishal Agrawal\nDirector\n"
        "e - Friend Solutions India (Jobmitra.com)\nwww.jobmitra.com"
    )
    return {
        "company_id": company_id,
        "company_contact_id": s["company_contact_id"],
        "recipient_email": s["recipient_email"],
        "subject": proposal_pdf.TITLE + " | " + s["company_name"],
        "body": body,
        "attachment_attached": False,
        "delivery_enabled": False,
        "instructions": (
            "Download this PDF and attach it manually before sending. Nothing has been sent."
        ),
    }
