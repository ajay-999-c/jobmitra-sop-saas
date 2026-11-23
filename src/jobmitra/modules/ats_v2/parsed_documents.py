"""Preserved parse drafts and explicit approval. Local text extraction, no AI/network calls."""

import base64
import hashlib
import io
import json
import re
from contextlib import contextmanager
from uuid import UUID, uuid5

from pydantic import ConfigDict, Field, model_validator
from pypdf import PdfReader
from sqlalchemy import text

from . import candidate_profiles as profiles
from . import candidates, resumes
from . import request_receipts as receipts
from .common import AtsError, one, utc_now
from .database import insert_result, transaction

PROFESSIONAL = {
    "job_title",
    "current_employer",
    "current_city",
    "qualification",
    "skills",
    "professional_summary",
    "experience_years",
}
EXTRAS = {
    "employment_history",
    "education_history",
    "certifications",
    "projects",
    "experience_months",
}


class JsonDraft(profiles.Strict):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    source_resume_id: int = Field(ge=1)
    raw_json: str | None = Field(default=None, max_length=262144)
    json_base64: str | None = Field(default=None, max_length=360000)
    filename: str = Field(default="pasted-resume.json", max_length=240)
    actor_name: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def one_input(self):
        if (self.raw_json is None) == (self.json_base64 is None):
            raise ValueError("Supply pasted text or uploaded JSON bytes")
        return self


class Extract(profiles.Strict):
    actor_name: str = Field(min_length=1, max_length=120)


class Approval(profiles.Strict):
    actor_name: str = Field(min_length=1, max_length=120)
    expected_revision: str = Field(min_length=64, max_length=64)
    approved_fields: list[str] = Field(min_length=1, max_length=40)
    identity_confirmed: bool = False


def _source(engine, cid, rid, root, *, pdf=False):
    with engine.connect() as conn:
        row = one(conn, "candidate_resumes", rid)
        if row["candidate_id"] != cid or row["resume_kind"] not in {
            "ORIGINAL",
            "JOBMITRA_STANDARD",
        }:
            raise AtsError("Source resume must belong to this canonical candidate.", 404)
        if pdf and row["resume_kind"] != "JOBMITRA_STANDARD":
            raise AtsError("Choose a Jobmitra Altered / Standardized PDF for extraction.")
    blob, media, _ = resumes.download_bytes(engine, cid, rid, root)
    if pdf and media != "application/pdf":
        raise AtsError("This altered version is not a PDF.")
    if len(blob) > 10 * 1024 * 1024:
        raise AtsError("Source exceeds the 10 MB limit.", 413)
    return row, blob, hashlib.sha256(blob).hexdigest()


def _normalize(payload):
    source = payload.get("profile", payload)
    if not isinstance(source, dict):
        raise AtsError("Structured JSON profile must be an object.")
    aliases = {
        "title": "job_title",
        "current_job_title": "job_title",
        "role_title": "job_title",
        "employer": "current_employer",
        "summary": "professional_summary",
        "location": "current_city",
        "education": "qualification",
        "work_experience": "extra:employment_history",
        "employment_history": "extra:employment_history",
        "education_history": "extra:education_history",
        "certifications": "extra:certifications",
        "projects": "extra:projects",
        "experience_months": "extra:experience_months",
    }
    proposed, evidence, warnings = {}, {}, []
    blocked = set()
    for key, value in source.items():
        name = aliases.get(key, key)
        if name in blocked:
            continue
        if name not in PROFESSIONAL and not (name.startswith("extra:") and name[6:] in EXTRAS):
            warnings.append("Preserved but not proposed for master update: " + key)
            continue
        try:
            if name.startswith("extra:"):
                field = name[6:]
                validated = profiles.Extra.model_validate({field: value}).model_dump(mode="json")[
                    field
                ]
            else:
                validated = profiles.CompletePatch.model_validate({name: value}).model_dump(
                    mode="json", exclude_unset=True
                )[name]
            if name in proposed and proposed[name] != validated:
                warnings.append(
                    "Conflicting aliases for " + name + "; enter a reviewed JSON value."
                )
                proposed.pop(name)
                evidence.pop(name, None)
                blocked.add(name)
                continue
            proposed[name] = validated
            evidence[name] = {"json_key": key, "value": value}
        except ValueError:
            warnings.append(
                "Preserved field needs manual correction before it can be proposed: " + key
            )
    return proposed, evidence, warnings


def extract_labelled(text):
    """Only explicit labels are structured. Generic narrative resumes remain manual/pending."""
    labels = {
        "current job title": "job_title",
        "current designation": "job_title",
        "job title": "job_title",
        "designation": "job_title",
        "current employer": "current_employer",
        "current company": "current_employer",
        "skills": "skills",
        "technical skills": "skills",
        "technologies": "skills",
        "qualification": "qualification",
        "professional summary": "professional_summary",
        "summary": "professional_summary",
        "current location": "current_city",
    }
    values, evidence, warnings = {}, {}, []
    duplicates = set()
    for number, line in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r"\s*([^:]{2,50}):\s*(.+?)\s*", line)
        if not match:
            continue
        label, value = match[1].casefold().strip(), match[2].strip()
        key = labels.get(label)
        if label == "total experience":
            exp = re.fullmatch(
                r"(?:(\d+)\s*(?:years?|yrs?)\s*)?(?:(\d+)\s*(?:months?|mos?)\s*)?", value, re.I
            )
            if exp and any(exp.groups()) and (not exp[2] or int(exp[2]) < 12):
                key = "experience_months"
                value = int(exp[1] or 0) * 12 + int(exp[2] or 0)
        if not key:
            continue
        if key in duplicates:
            continue
        value = (
            [s.strip() for s in re.split(r"[,;]", value) if s.strip()] if key == "skills" else value
        )
        if key in values and values[key] != value:
            duplicates.add(key)
            values.pop(key, None)
            evidence.pop(key, None)
            warnings.append("Conflicting labelled values for " + key + "; not proposed.")
            continue
        values[key] = value
        evidence[key] = {"line": number, "text": line}
    proposed, _, invalid = _normalize(values)
    for key in list(proposed):
        evidence[key] = evidence.get(key.removeprefix("extra:"), {})
    evidence = {key: evidence[key] for key in proposed}
    return proposed, evidence, warnings + invalid


@contextmanager
def _artifact_transaction(engine, root):
    published = []
    try:
        with transaction(engine) as conn:
            yield conn, published
    except Exception:
        for path in published:
            resumes.discard_unreferenced(engine, root, path)
        raise


def _insert_draft(
    conn, cid, source, sha, actor, role, artifact, metadata, filename, source_type, root, published
):
    blob = artifact.encode("utf-8")
    relative, path = resumes._publish(root, cid, "PARSED_TEXT", blob, ".json")
    published.append(path)
    rid = insert_result(
        conn,
        text(
            "INSERT INTO "
            "candidate_resumes(candidate_id,resume_kind,source_type,original_filename,"
            "raw_text,parsed_json,storage_path,is_current) "
            "VALUES(:c,'PARSED_TEXT',:type,:filename,:raw,:meta,:path,0)"
        ),
        {
            "c": cid,
            "type": source_type,
            "filename": filename,
            "raw": artifact,
            "path": relative,
            "meta": json.dumps(
                {
                    "workflow": "NATIVE_PARSED_V1",
                    "facts_reviewed": False,
                    "source_resume_id": source["id"],
                    "source_sha256": sha,
                    "created_by": actor,
                    "actor_role": role,
                    "artifact_sha256": hashlib.sha256(artifact.encode("utf-8")).hexdigest(),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "size": len(blob),
                    **metadata,
                }
            ),
        },
    ).lastrowid
    return rid


def json_draft(engine, cid, data, role, root):
    source, _, sha = _source(engine, cid, data.source_resume_id, root)
    filename = resumes._filename(data.filename)
    if not filename.lower().endswith(".json"):
        raise AtsError("Choose a .json file.")
    try:
        raw = (
            base64.b64decode(data.json_base64, validate=True).decode("utf-8")
            if data.json_base64 is not None
            else data.raw_json
        )
        if len(raw.encode("utf-8")) > 262144:
            raise ValueError("Too large")
        payload = json.loads(raw.lstrip("\ufeff"))
        if not isinstance(payload, dict):
            raise ValueError("Not an object")
    except (ValueError, UnicodeError):
        raise AtsError("Upload UTF-8 JSON containing an object (maximum 256 KB).") from None
    proposed, evidence, warnings = _normalize(payload)
    key = [cid, data.model_dump(), sha]
    with _artifact_transaction(engine, root) as (conn, published):
        prior = receipts.replay(conn, "parsed-json-draft", key)
        if prior:
            return get(engine, cid, prior)
        profiles.ensure(conn)
        rid = _insert_draft(
            conn,
            cid,
            source,
            sha,
            data.actor_name,
            role,
            raw,
            {
                "input_kind": "JSON",
                "status": "STRUCTURED_DRAFT" if proposed else "MANUAL_REVIEW_REQUIRED",
                "proposed_fields": proposed,
                "field_evidence": evidence,
                "warnings": warnings,
                "document_candidate_name": payload.get("full_name") or payload.get("name"),
            },
            filename,
            "UPLOADED",
            root,
            published,
        )
        receipts.record(conn, "parsed-json-draft", key, rid, candidate_id=cid)
    return get(engine, cid, rid)


def extract(engine, cid, rid, data, role, root):
    source, blob, sha = _source(engine, cid, rid, root, pdf=True)
    key = [cid, rid, sha, data.model_dump()]
    with engine.connect() as conn:
        prior = receipts.replay(conn, "parsed-pdf-draft", key)
        if prior:
            return get(engine, cid, prior)
    warnings = []
    text_value = ""
    proposed = {}
    evidence = {}
    try:
        reader = PdfReader(io.BytesIO(blob), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("Unsupported PDF")
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            if sum(len(p) for p in pages) > 250000:
                raise ValueError("Text limit exceeded")
        text_value = "\n\n".join(pages).strip()
        proposed, evidence, warnings = extract_labelled(text_value)
        status = (
            "PARTIAL_STRUCTURED_DRAFT"
            if proposed
            else "TEXT_ONLY_PARSER_PENDING"
            if text_value
            else "OCR_REQUIRED"
        )
    except Exception:
        status = "EXTRACTION_FAILED"
        warnings.append("Local PDF text extraction failed; manual review is required.")
    warnings.append(
        "Local labelled-field parser only. Unlabelled roles, dates, employment, "
        "education, certifications and projects require reviewed JSON or manual "
        "editing. No AI or OCR was used."
    )
    artifact = json.dumps(
        {
            "schema_version": 1,
            "source_resume_id": rid,
            "source_sha256": sha,
            "status": status,
            "proposed_fields": proposed,
            "field_evidence": evidence,
            "extracted_text": text_value,
            "warnings": warnings,
        },
        ensure_ascii=False,
        indent=2,
    )
    with _artifact_transaction(engine, root) as (conn, published):
        prior = receipts.replay(conn, "parsed-pdf-draft", key)
        if prior:
            return get(engine, cid, prior)
        profiles.ensure(conn)
        draft_id = _insert_draft(
            conn,
            cid,
            source,
            sha,
            data.actor_name,
            role,
            artifact,
            {
                "input_kind": "PDF",
                "status": status,
                "proposed_fields": proposed,
                "field_evidence": evidence,
                "warnings": warnings,
            },
            "pdf-extraction-" + str(rid) + ".json",
            "GENERATED",
            root,
            published,
        )
        receipts.record(conn, "parsed-pdf-draft", key, draft_id, candidate_id=cid)
    return get(engine, cid, draft_id)


def _draft(conn, cid, rid):
    row = one(conn, "candidate_resumes", rid)
    if row["candidate_id"] != cid or row["resume_kind"] != "PARSED_TEXT":
        raise AtsError("Parsed version not found for this candidate.", 404)
    meta = json.loads(row["parsed_json"] or "{}")
    if not isinstance(meta, dict):
        meta = {"historical_parsed_json": meta}
    return row, meta


def get(engine, cid, rid):
    with engine.connect() as conn:
        row, meta = _draft(conn, cid, rid)
        profile = profiles._state(conn, cid)
        raw = row["raw_text"] or meta.get("original_source_json_text")
        input_kind = meta.get("input_kind")
        if meta.get("reviewed_draft_id"):
            original_draft, draft_meta = _draft(conn, cid, meta["reviewed_draft_id"])
            raw = original_draft["raw_text"]
            input_kind = draft_meta.get("input_kind")
        text_value = ""
        if input_kind == "PDF" and raw:
            text_value = json.loads(raw).get("extracted_text", "")
        source = None
        if meta.get("source_resume_id"):
            original = (
                conn.execute(
                    text("SELECT * FROM candidate_resumes WHERE id=:id"),
                    {"id": meta["source_resume_id"]},
                )
                .mappings()
                .first()
            )
            if original is not None and original["candidate_id"] != cid:
                raise AtsError("Parsed source ownership mismatch.", 409)
            if original is not None:
                source = resumes._resume_public(original)
        name = meta.get("document_candidate_name")
        return {
            "id": row["id"],
            "candidate_id": cid,
            "created_at": row["created_at"],
            "filename": row["original_filename"],
            "status": meta.get("status")
            or ("REVIEWED" if meta.get("facts_reviewed") else "HISTORICAL_REVIEW_REQUIRED"),
            "source": source,
            "source_sha256": meta.get("source_sha256"),
            "proposed_fields": meta.get("proposed_fields", {}),
            "field_evidence": meta.get("field_evidence", {}),
            "warnings": meta.get("warnings", []),
            "extracted_text": text_value,
            "original_json_text": raw if input_kind == "JSON" else None,
            "profile_revision": profile["revision"],
            "current_profile": profile,
            "identity_confirmation_required": bool(
                name
                and str(name).strip().casefold()
                != profile["candidate"]["full_name"].strip().casefold()
            ),
            "applied_fields": meta.get("applied_fields", []),
            "reviewed_draft_id": meta.get("reviewed_draft_id"),
            "downloadable_json": bool(raw or meta.get("original_source_json")),
            "json_sha256": hashlib.sha256(_artifact(conn, cid, rid)).hexdigest(),
            "json_origin": "preserved_source_text"
            if raw is not None
            else "serialized_historical_metadata",
        }


def _artifact(conn, cid, rid):
    row, meta = _draft(conn, cid, rid)
    if meta.get("reviewed_draft_id"):
        row, meta = _draft(conn, cid, meta["reviewed_draft_id"])
    raw = row["raw_text"] or meta.get("original_source_json_text")
    if raw is None:
        value = meta.get("original_source_json") or meta.get("historical_parsed_json") or meta
        raw = json.dumps(value, ensure_ascii=False, indent=2)
    blob = raw.encode("utf-8")
    if meta.get("artifact_sha256") and hashlib.sha256(blob).hexdigest() != meta["artifact_sha256"]:
        raise AtsError("Preserved JSON checksum verification failed.", 409)
    return blob


def download(engine, cid, rid, root=None):
    with engine.connect() as conn:
        blob = _artifact(conn, cid, rid)
        row, meta = _draft(conn, cid, rid)
        if meta.get("reviewed_draft_id"):
            row, _ = _draft(conn, cid, meta["reviewed_draft_id"])
        stored_id = row["id"] if row["storage_path"] else None
    if stored_id is not None:
        stored, _, _ = resumes.download_bytes(engine, cid, stored_id, root)
        if stored != blob:
            raise AtsError("Preserved JSON file and database evidence disagree.", 409)
    return blob


def approve(engine, cid, rid, data, role):
    key = [cid, rid, data.model_dump()]
    with transaction(engine) as conn:
        prior = receipts.replay(conn, "parsed-review", key)
        if prior:
            return {"parsed_version": get(engine, cid, prior), "replayed": True}
        row, meta = _draft(conn, cid, rid)
        if meta.get("workflow") != "NATIVE_PARSED_V1" or meta.get("facts_reviewed"):
            raise AtsError("Select a preserved draft for field approval.")
        proposed = meta.get("proposed_fields", {})
        selected = set(data.approved_fields)
        if not selected <= set(proposed):
            raise AtsError("Only displayed proposed fields may be approved.")
        current = profiles._state(conn, cid)
        name = meta.get("document_candidate_name")
        if (
            name
            and str(name).strip().casefold() != current["candidate"]["full_name"].strip().casefold()
            and not data.identity_confirmed
        ):
            raise AtsError("Confirm this source document belongs to the selected candidate.")
        source = one(conn, "candidate_resumes", meta["source_resume_id"])
        if source["candidate_id"] != cid:
            raise AtsError("Source resume belongs to another candidate.", 404)
        changes = {k: proposed[k] for k in selected if not k.startswith("extra:")}
        extra = {k[6:]: proposed[k] for k in selected if k.startswith("extra:")}
        if not PROFESSIONAL >= set(changes) or not EXTRAS >= set(extra):
            raise AtsError("Unsupported professional update.")
        request_key = receipts.request_key.get()
        if not request_key:
            raise AtsError("An Idempotency-Key UUID is required.")
        review = profiles.Review(
            idempotency_key=uuid5(UUID(request_key), "parsed-profile-review"),
            actor_name=data.actor_name,
            expected_revision=data.expected_revision,
            changes=changes,
            extra=extra,
            approved_fields=sorted(selected),
            source_digest=meta["source_sha256"],
        )
        profiles.save(engine, cid, review, role, connection=conn)
        new_id = resumes._version(
            conn,
            cid,
            "PARSED_TEXT",
            source_type=row["source_type"],
            original_filename="Reviewed " + str(row["original_filename"] or "parsed JSON"),
            parsed_json=json.dumps(
                {
                    "workflow": "NATIVE_PARSED_V1",
                    "status": "APPROVED_FIELDS",
                    "facts_reviewed": True,
                    "profile": {**changes, **extra},
                    "source_resume_id": source["id"],
                    "source_sha256": meta["source_sha256"],
                    "reviewed_draft_id": rid,
                    "applied_fields": sorted(selected),
                    "reviewed_at": utc_now(),
                    "rejected_or_unapproved_fields": sorted(set(proposed) - selected),
                    "reviewed_by": data.actor_name,
                    "actor_role": role,
                }
            ),
        )
        candidates.rebuild_search(conn, cid)
        receipts.record(conn, "parsed-review", key, new_id, candidate_id=cid)
    return {"parsed_version": get(engine, cid, new_id), "replayed": False}
