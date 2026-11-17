"""Use the processor's existing version-3 SQLite schema without creating/migrating it."""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

CONTROL = "sop-control-v1"
ACTIVE = {"QUEUED", "EXTRACTING", "MASKING", "PARSING", "GENERATING"}
STAGES = ["Resume Uploaded", "Text Extraction", "PII Masking", "Groq Parsing", "Resume Generation"]


class ProcessingError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status


def digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def database(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ProcessingError("Existing processor SQLite database is unavailable.", 503)
    conn = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        required = {
            "candidates": {
                "candidate_id",
                "full_name",
                "identity_status",
                "email_normalized",
                "mobile_e164",
                "created_at",
                "updated_at",
            },
            "resumes": {
                "document_id",
                "candidate_id",
                "document_sha256",
                "mask_version",
                "original_file_path",
                "extracted_sha256",
                "sanitized_sha256",
                "parsed_json_path",
                "processing_status",
                "failure_history_json",
            },
            "resume_parses": {
                "parse_id",
                "document_id",
                "parser_signature",
                "metadata_json",
                "parsed_json_path",
                "parsed_json_sha256",
                "llm_status",
            },
        }
        for table, columns in required.items():
            found = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not columns <= found:
                raise ProcessingError(
                    "Processor SQLite schema is unsupported; no migration ran.", 503
                )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def document(conn, doc_id):
    if not re.fullmatch(r"[a-f0-9]{64}", doc_id):
        raise ProcessingError("Document not found.", 404)
    row = conn.execute(
        "SELECT r.*,c.full_name,c.email_normalized,c.mobile_e164,c.identity_status "
        "FROM resumes r JOIN candidates c USING(candidate_id) WHERE document_id=?",
        (doc_id,),
    ).fetchone()
    if row is None:
        raise ProcessingError("Document not found.", 404)
    return dict(row)


def control(conn, doc_id):
    row = conn.execute(
        "SELECT metadata_json FROM resume_parses WHERE document_id=? AND parser_signature=?",
        (doc_id, CONTROL),
    ).fetchone()
    return json.loads(row[0]) if row else {}


def save_control(conn, doc_id, meta):
    meta["updated_at"] = time.time()
    conn.execute(
        "INSERT INTO resume_parses(parse_id,document_id,parser_signature,parsed_json_path,"
        "llm_status,metadata_json) VALUES(?,?,?,'','CONTROL',?) "
        "ON CONFLICT(document_id,parser_signature) DO UPDATE SET "
        "metadata_json=excluded.metadata_json",
        ("sop-" + doc_id, doc_id, CONTROL, json.dumps(meta)),
    )


def update_control(db, doc_id, **values):
    with database(db) as conn:
        conn.execute("BEGIN IMMEDIATE")
        meta = control(conn, doc_id)
        meta.update(values)
        save_control(conn, doc_id, meta)


def private_path(root, value):
    if not value:
        raise ProcessingError("Artifact path is missing; local review required.")
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to((root / "private").resolve()):
        raise ProcessingError("Artifact path is outside private processor storage.")
    return path


def selected_parse(conn, row):
    version = conn.execute(
        "SELECT * FROM resume_parses WHERE document_id=? AND llm_status='COMPLETED' "
        "AND parsed_json_path=? AND parsed_json_sha256=? ORDER BY created_at DESC LIMIT 1",
        (row["document_id"], row["parsed_json_path"], row["parsed_json_sha256"]),
    ).fetchone()
    if not version:
        raise ProcessingError("A registered completed parse is required.")
    return dict(version)


def status(conn, doc_id):
    row = document(conn, doc_id)
    meta = control(conn, doc_id)
    state = meta.get("state", "UPLOADED")
    # Child timeout is 15 minutes; an expired slot is never silently retried.
    if state in ACTIVE and time.time() - meta.get("started_at", 0) > 960:
        meta.update(state="FAILED", error="INTERRUPTED")
        save_control(conn, doc_id, meta)
        state = "FAILED"
    return {
        "document_id": doc_id,
        "candidate_id": row["candidate_id"],
        "candidate_name": row["full_name"],
        "state": state,
        "stage": meta.get("stage", 0),
        "error": meta.get("error"),
        "next_retry_at": meta.get("next_retry_at"),
        "extraction_status": row["extraction_status"],
        "masking_status": row["masking_status"],
        "llm_status": row["llm_status"],
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "blocking_reasons": json.loads(row["blocking_reasons_json"] or "[]"),
        "steps": STAGES,
        "exports": list(meta.get("exports", {})) if state == "COMPLETED" else [],
        "location": meta.get("location", ""),
    }
