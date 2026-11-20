"""Private immutable resume versions and explicitly reviewed professional evidence."""

import hashlib
import html
import json
import os
import stat
import uuid
import zipfile
import zlib
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from xml.etree import ElementTree

from sqlalchemy import text

from . import request_receipts as receipts
from .candidate_schemas import GenerateResumeInput, ParsedResumeInput
from .candidates import rebuild_search
from .common import AtsError, one
from .database import transaction


def _root(root):
    if root is None:
        raise AtsError("Configure the private ATS V2 resume storage root.", 503)
    root = Path(root).expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise AtsError("ATS resume storage must be an absolute private directory.", 503)
    root = root.resolve()
    if {"static", "templates"} & {part.casefold() for part in root.parts}:
        raise AtsError("ATS resumes must be stored outside public static directories.", 503)
    return root


def safe_resume_path(root, relative):
    root = _root(root)
    if not relative or "\\" in relative or ":" in relative or "\x00" in relative:
        raise AtsError("Invalid stored resume path.", 422)
    path = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        path.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {".", ".."} for part in path.parts)
    ):
        raise AtsError("Invalid stored resume path.", 422)
    resolved = (root / Path(*path.parts)).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise AtsError("Resume path is outside private storage.", 422)
    return resolved


def _filename(filename):
    if (
        not filename
        or len(filename) > 240
        or filename in {".", ".."}
        or any(c in filename for c in '/\\:\x00<>"|?*')
        or filename.endswith((".", " "))
        or any(ord(c) < 32 or ord(c) == 127 for c in filename)
    ):
        raise AtsError("Use a filename without directories or invalid characters.")
    return filename


def _validate(data, filename, max_bytes):
    if not data or len(data) > max_bytes:
        raise AtsError("Resume is empty or exceeds the configured upload limit.", 413)
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
            raise AtsError("Upload a readable PDF or DOCX resume.")
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 2000
                    or len({i.filename for i in entries}) != len(entries)
                    or sum(i.file_size for i in entries) > 50 * 1024 * 1024
                    or any(i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16) for i in entries)
                ):
                    raise ValueError
                for entry in entries:
                    path = PurePosixPath(entry.filename)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or "\\" in entry.filename
                        or ":" in entry.filename
                        or entry.filename.casefold().endswith("vbaproject.bin")
                    ):
                        raise ValueError
                for required in ("[Content_Types].xml", "word/document.xml"):
                    if archive.getinfo(required).file_size > min(max_bytes * 2, 10 * 1024 * 1024):
                        raise ValueError
                    xml = archive.read(required)
                    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                        raise ValueError
                    ElementTree.fromstring(xml)
                if (
                    b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                    not in archive.read("[Content_Types].xml")
                ):
                    raise ValueError
        except (
            zipfile.BadZipFile,
            KeyError,
            ValueError,
            ElementTree.ParseError,
            RuntimeError,
            EOFError,
            NotImplementedError,
            zlib.error,
        ):
            raise AtsError("Upload a readable PDF or DOCX resume.") from None
    else:
        raise AtsError("Upload a PDF or DOCX resume.")
    return suffix


def _version(conn, candidate_id, kind, **values):
    conn.execute(
        text(
            "UPDATE candidate_resumes SET is_current=0 WHERE candidate_id=:id AND resume_kind=:kind"
        ),
        {"id": candidate_id, "kind": kind},
    )
    values.update(candidate_id=candidate_id, resume_kind=kind)
    columns = list(values)
    result = conn.execute(
        text(
            "INSERT INTO candidate_resumes ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join(":" + key for key in columns)
            + ")"
        ),
        values,
    )
    return result.lastrowid


def _publish(root, candidate_id, kind, data, suffix):
    relative = f"{candidate_id}/{kind.lower()}/{uuid.uuid4().hex}{suffix}"
    path = safe_resume_path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)
    return relative, path


def upload_resume(
    engine,
    candidate_id,
    root,
    data,
    filename,
    max_bytes,
    kind="ORIGINAL",
    metadata=None,
    reuse_existing=False,
):
    filename = _filename(filename)
    suffix = _validate(data, filename, max_bytes)
    if kind not in {"ORIGINAL", "JOBMITRA_STANDARD"}:
        raise AtsError("Choose ORIGINAL or JOBMITRA_STANDARD resume kind.")
    root = _root(root)
    metadata = metadata or {}
    path = None
    try:
        with transaction(engine) as conn:
            one(conn, "candidates", candidate_id)
            request_data = [
                candidate_id,
                filename,
                kind,
                hashlib.sha256(data).hexdigest(),
                metadata,
            ]
            if reuse_existing:
                request_data.append("REUSE_EXISTING")
            prior = receipts.replay(conn, "resume-upload", request_data)
            if prior is not None:
                result = get_resume(engine, candidate_id, prior)
                return (
                    {**result, "reused_existing": True, "replayed": True}
                    if reuse_existing
                    else result
                )
            if metadata.get("source_original_id"):
                original = one(conn, "candidate_resumes", metadata["source_original_id"])
                if (
                    original["candidate_id"] != candidate_id
                    or original["resume_kind"] != "ORIGINAL"
                ):
                    raise AtsError("Source original must belong to this candidate.", 422)
            relative = None
            if reuse_existing and kind == "JOBMITRA_STANDARD":
                rows = conn.execute(
                    text(
                        "SELECT * FROM candidate_resumes WHERE candidate_id=:c "
                        "AND resume_kind='JOBMITRA_STANDARD' AND storage_path IS NOT NULL "
                        "ORDER BY is_current DESC,id DESC"
                    ),
                    {"c": candidate_id},
                ).mappings()
                for existing in rows:
                    old = json.loads(existing["parsed_json"] or "{}")
                    if old.get("sha256") != hashlib.sha256(data).hexdigest():
                        continue
                    stored, _, _ = download_resume(engine, candidate_id, existing["id"], root)
                    if stored.read_bytes() != data:
                        raise AtsError("Existing resume bytes differ from their checksum.", 409)
                    relative = existing["storage_path"]
                    if all(
                        (old.get(k) in (None, "") and metadata.get(k) in (None, ""))
                        or old.get(k) == metadata.get(k)
                        for k in ("preparation_source", "source_original_id", "upload_notes")
                    ):
                        receipts.record(
                            conn,
                            "resume-upload",
                            request_data,
                            existing["id"],
                            candidate_id=candidate_id,
                        )
                        return {**_resume_public(existing), "reused_existing": True}
                    break
            if relative is None:
                relative, path = _publish(root, candidate_id, kind, data, suffix)
            resume_id = _version(
                conn,
                candidate_id,
                kind,
                source_type="UPLOADED",
                original_filename=filename,
                storage_path=relative,
                parsed_json=json.dumps(
                    {**metadata, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                ),
            )
            if kind == "ORIGINAL":
                conn.execute(
                    text(
                        "UPDATE candidate_resumes SET is_current=0 WHERE candidate_id=:id "
                        "AND (resume_kind='PARSED_TEXT' OR (resume_kind='JOBMITRA_STANDARD' "
                        "AND source_type='GENERATED')) AND is_current=1"
                    ),
                    {"id": candidate_id},
                )
                rebuild_search(conn, candidate_id)
            receipts.record(
                conn, "resume-upload", request_data, resume_id, candidate_id=candidate_id
            )
        return get_resume(engine, candidate_id, resume_id)
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def _resume_public(row):
    result = dict(row)
    result["downloadable"] = bool(result.pop("storage_path", None))
    result.pop("raw_text", None)
    result.pop("source_json", None)
    result.pop("source_fingerprint", None)
    parsed = json.loads(result.pop("parsed_json") or "{}")
    imported = bool(result.get("legacy_postgres_id"))
    result["source_legacy"] = "postgresql" if imported else None
    if result["resume_kind"] == "PARSED_TEXT":
        result["review_status"] = parsed.get("status") or (
            "REVIEWED" if parsed.get("facts_reviewed") else "HISTORICAL_REVIEW_REQUIRED"
        )
        result["source_resume_id"] = parsed.get("source_resume_id")
        result["source_sha256"] = parsed.get("source_sha256")
        result["reviewed_draft_id"] = parsed.get("reviewed_draft_id")
        result["artifact_sha256"] = parsed.get("artifact_sha256")
        if imported:
            result["historical_parsed_json"] = parsed
            result["requires_review"] = True
        else:
            result["profile"] = parsed.get("profile", {})
            result["source_resume_id"] = parsed.get("source_resume_id")
            result["candidate_name_snapshot"] = parsed.get("candidate_name_snapshot")
            result["requires_review"] = not bool(parsed.get("facts_reviewed"))
    else:
        for key in (
            "sha256",
            "size",
            "uploaded_by",
            "actor_role",
            "preparation_source",
            "source_original_id",
            "upload_notes",
        ):
            result[key] = parsed.get(key)
        result["file_status"] = parsed.get("migration_file_status") or (
            "stored" if result["downloadable"] else "unavailable"
        )
    result["is_current"] = bool(result["is_current"])
    return result


def set_current(engine, candidate_id, resume_id, expected_current_id, actor_name, role):
    with transaction(engine) as conn:
        row = one(conn, "candidate_resumes", resume_id)
        if row["candidate_id"] != candidate_id or row["resume_kind"] not in {
            "ORIGINAL",
            "JOBMITRA_STANDARD",
        }:
            raise AtsError(
                "Choose an original or altered version belonging to this candidate.", 404
            )
        request_data = [candidate_id, resume_id, expected_current_id, actor_name]
        if receipts.replay(conn, "resume-current", request_data) is not None:
            return get_resume(engine, candidate_id, resume_id)
        current = conn.execute(
            text(
                "SELECT id FROM candidate_resumes WHERE candidate_id=:c AND "
                "resume_kind=:k AND is_current=1"
            ),
            {"c": candidate_id, "k": row["resume_kind"]},
        ).scalar()
        if current != expected_current_id:
            raise AtsError("Current resume changed. Reload before selecting a version.", 409)
        if not row["storage_path"]:
            raise AtsError("This historical file is unavailable; it cannot become current.", 409)
        conn.execute(
            text(
                "UPDATE candidate_resumes SET is_current=0 WHERE candidate_id=:c AND resume_kind=:k"
            ),
            {"c": candidate_id, "k": row["resume_kind"]},
        )
        conn.execute(
            text("UPDATE candidate_resumes SET is_current=1 WHERE id=:r"), {"r": resume_id}
        )
        if row["resume_kind"] == "ORIGINAL":
            conn.execute(
                text(
                    "UPDATE candidate_resumes SET is_current=0 WHERE candidate_id=:c AND "
                    "(resume_kind='PARSED_TEXT' OR (resume_kind='JOBMITRA_STANDARD' AND "
                    "source_type='GENERATED'))"
                ),
                {"c": candidate_id},
            )
        conn.execute(
            text(
                "INSERT INTO "
                "recruitment_events(candidate_id,event_type,before_json,after_json,payload_json) "
                "VALUES(:c,'RESUME_CURRENT_CHANGED',:before,:after,:payload)"
            ),
            {
                "c": candidate_id,
                "before": json.dumps({"current_resume_id": current}),
                "after": json.dumps({"current_resume_id": resume_id, "kind": row["resume_kind"]}),
                "payload": json.dumps({"actor_name": actor_name, "actor_role": role}),
            },
        )
        rebuild_search(conn, candidate_id)
        receipts.record(conn, "resume-current", request_data, resume_id, candidate_id=candidate_id)
    return get_resume(engine, candidate_id, resume_id)


def get_resume(engine, candidate_id, resume_id):
    with engine.connect() as conn:
        one(conn, "candidates", candidate_id)
        row = one(conn, "candidate_resumes", resume_id)
        if row["candidate_id"] != candidate_id:
            raise AtsError("Resume not found.", 404)
        return _resume_public(row)


def list_resumes(engine, candidate_id):
    with engine.connect() as conn:
        one(conn, "candidates", candidate_id)
        rows = conn.execute(
            text(
                "SELECT * FROM candidate_resumes WHERE candidate_id=:id "
                "ORDER BY created_at DESC,id DESC"
            ),
            {"id": candidate_id},
        ).mappings()
        return [_resume_public(row) for row in rows]


def save_parsed_resume(engine, candidate_id, data: ParsedResumeInput):
    with transaction(engine) as conn:
        request_data = [candidate_id, data.model_dump(mode="json")]
        prior = receipts.replay(conn, "parsed-version", request_data)
        if prior is not None:
            return get_resume(engine, candidate_id, prior)
        candidate = one(conn, "candidates", candidate_id)
        source = one(conn, "candidate_resumes", data.source_resume_id)
        if (
            source["candidate_id"] != candidate_id
            or source["resume_kind"] != "ORIGINAL"
            or not source["is_current"]
        ):
            raise AtsError("Review the current original resume for this candidate.", 409)
        payload = {
            "profile": data.profile.model_dump(exclude_none=True),
            "source_resume_id": source["id"],
            "facts_reviewed": True,
            "candidate_name_snapshot": candidate["full_name"],
        }
        resume_id = _version(
            conn,
            candidate_id,
            "PARSED_TEXT",
            source_type="UPLOADED",
            parsed_json=json.dumps(payload, ensure_ascii=False),
        )
        rebuild_search(conn, candidate_id)
        receipts.record(conn, "parsed-version", request_data, resume_id, candidate_id=candidate_id)
    return get_resume(engine, candidate_id, resume_id)


def _render_value(value):
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return "".join(
            f"<p><strong>{html.escape(str(key).replace('_', ' ').title())}:</strong> "
            f"{_render_value(item)}</p>"
            for key, item in value.items()
            if item
        )
    if isinstance(value, list):
        return "<ul>" + "".join("<li>" + _render_value(item) + "</li>" for item in value) + "</ul>"
    return html.escape(str(value))


def generate_resume(engine, candidate_id, root, data: GenerateResumeInput):
    root, path = _root(root), None
    try:
        with transaction(engine) as conn:
            request_data = [candidate_id, data.model_dump(mode="json")]
            prior = receipts.replay(conn, "standard-resume", request_data)
            if prior is not None:
                return get_resume(engine, candidate_id, prior)
            candidate = one(conn, "candidates", candidate_id)
            parsed = one(conn, "candidate_resumes", data.parsed_resume_id)
            if (
                parsed["candidate_id"] != candidate_id
                or parsed["resume_kind"] != "PARSED_TEXT"
                or not parsed["is_current"]
            ):
                raise AtsError("Review the current professional data before generation.", 409)
            payload = json.loads(parsed["parsed_json"] or "{}")
            original = one(conn, "candidate_resumes", payload.get("source_resume_id", -1))
            if (
                not original["is_current"]
                or original["candidate_id"] != candidate_id
                or payload.get("candidate_name_snapshot") != candidate["full_name"]
            ):
                raise AtsError(
                    "Identity or original resume changed. Review professional data again.", 409
                )
            original_path = safe_resume_path(root, original["storage_path"])
            original_meta = json.loads(original["parsed_json"] or "{}")
            if not original_path.is_file() or hashlib.sha256(
                original_path.read_bytes()
            ).hexdigest() != original_meta.get("sha256"):
                raise AtsError("Original resume integrity review required.", 409)
            profile = payload["profile"]
            body = "".join(
                f"<section><h2>{html.escape(key.replace('_', ' ').title())}</h2>"
                + _render_value(value)
                + "</section>"
                for key, value in profile.items()
                if value
            )
            name = html.escape(candidate["full_name"])
            document = (
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f"<title>{name} — Jobmitra resume</title>"
                "<style>body{font:16px/1.6 Arial,sans-serif;max-width:850px;margin:3em auto;"
                "padding:0 24px;color:#172334}h1,h2{color:#243c62}h2{font-size:1.2em;"
                "border-bottom:1px solid #ddd}li p{margin:.2em 0}"
                "@media print{body{margin:0}}</style>"
                f"<body><header><p>JOBMITRA · PROFESSIONAL RESUME</p><h1>{name}</h1></header>"
                f"{body}</body></html>"
            ).encode()
            relative, path = _publish(root, candidate_id, "JOBMITRA_STANDARD", document, ".html")
            resume_id = _version(
                conn,
                candidate_id,
                "JOBMITRA_STANDARD",
                source_type="GENERATED",
                original_filename=f"Jobmitra-{candidate['candidate_code']}.html",
                storage_path=relative,
                parsed_json=json.dumps(
                    {
                        "parsed_resume_id": parsed["id"],
                        "sha256": hashlib.sha256(document).hexdigest(),
                    }
                ),
            )
            receipts.record(
                conn, "standard-resume", request_data, resume_id, candidate_id=candidate_id
            )
        return get_resume(engine, candidate_id, resume_id)
    except Exception:
        if path is not None:
            path.unlink(missing_ok=True)
        raise


def download_resume(engine, candidate_id, resume_id, root):
    with engine.connect() as conn:
        one(conn, "candidates", candidate_id)
        row = one(conn, "candidate_resumes", resume_id)
        if row["candidate_id"] != candidate_id:
            raise AtsError("Resume not found.", 404)
        if not row["storage_path"]:
            raise AtsError("This version contains professional JSON; use the resume history API.")
        path = safe_resume_path(root, row["storage_path"])
        if not path.is_file():
            raise AtsError("Stored resume file is unavailable.", 404)
        metadata = json.loads(row["parsed_json"] or "{}")
        if metadata.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise AtsError("Stored resume integrity review required.", 409)
        media = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".html": "text/html",
        }.get(path.suffix.lower())
        if not media:
            raise AtsError("Unsupported stored resume type.")
        return path, media, row["original_filename"] or path.name
