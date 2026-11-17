"""Run in the processor's Python environment. Reuse its services, prompt and schema.

This single-document adapter deliberately does not invoke the Groq pilot batch CLI.
The SOP owns this adapter; the sibling repository is imported without modification.
"""

import argparse
import contextlib
import json
import logging
import math
import os
import sys
import time
import uuid
from pathlib import Path

from store import (  # Script directory is on sys.path in the isolated interpreter.
    ProcessingError,
    control,
    database,
    digest,
    document,
    private_path,
    selected_parse,
    update_control,
)


def checked(root, row, kind):
    path = private_path(root, row[kind + "_markdown_path"])
    if not path.is_file() or digest(path.read_bytes()) != row[kind + "_sha256"]:
        raise ProcessingError("Artifact integrity review required.")
    return path


def local_stages(root, db, doc_id):
    from app.core import config
    from app.core.batch import atomic_write
    from app.core.eligibility import input_eligibility, masking_identity, save_masking_identity
    from app.services import extraction, pii_pipeline

    with database(db) as conn:
        row = document(conn, doc_id)
    original = Path(row["original_file_path"])
    original = original if original.is_absolute() else root / original
    if not original.is_file() or digest(original.read_bytes()) != doc_id:
        raise ProcessingError("Original file integrity review required.")
    update_control(db, doc_id, state="EXTRACTING", stage=1)
    if row["extraction_status"] == "EXTRACTED":
        raw_path = checked(root, row, "extracted")
    else:
        raw, result = extraction.extract_markdown(original, extraction.make_converter())
        if result != "OK":
            with database(db) as conn:
                conn.execute(
                    "UPDATE resumes SET extraction_status=? WHERE document_id=?", (result, doc_id)
                )
            raise ProcessingError("Text extraction requires local review.")
        raw_path = config.PRIVATE / "extracted" / (doc_id + ".md")
        if raw_path.exists():
            raise ProcessingError("An unregistered extraction already exists; review required.")
        atomic_write(raw_path, raw)
        raw_path.chmod(0o600)
        with database(db) as conn:
            conn.execute(
                "UPDATE resumes SET extraction_status='EXTRACTED',extracted_markdown_path=?,"
                "extracted_sha256=?,updated_at=CURRENT_TIMESTAMP WHERE document_id=?",
                (str(raw_path), digest(raw_path.read_bytes()), doc_id),
            )
    update_control(db, doc_id, state="MASKING", stage=2)
    mask_version = digest(Path(pii_pipeline.__file__).read_bytes())
    if row["masking_status"] == "MASKED":
        if row["mask_version"] != mask_version:
            raise ProcessingError("Masking version requires local review.")
        clean_path = checked(root, row, "sanitized")
        detected = masking_identity(row)
    else:
        result = pii_pipeline.sanitize_resume(
            raw_path.read_text(encoding="utf-8"), pii_pipeline.load_gliner()
        )
        with database(db) as conn:
            conn.execute(
                "UPDATE resumes SET masking_status=?,mask_version=? WHERE document_id=?",
                (
                    "BLOCKED" if result["status"] == "MASKED" else result["status"],
                    mask_version,
                    doc_id,
                ),
            )
        if result["status"] != "MASKED":
            raise ProcessingError("Masking requires local review.")
        detected = result.get("identity", {})
        for detected_key, registered_key in [
            ("email", "email_normalized"),
            ("mobile", "mobile_e164"),
        ]:
            actual, expected = detected.get(detected_key), row[registered_key]
            if actual and expected and actual.strip().casefold() != expected.strip().casefold():
                raise ProcessingError("Resume contacts conflict with registration.")
        clean_path = config.PRIVATE / "sanitized" / (doc_id + ".md")
        if clean_path.exists():
            raise ProcessingError("An unregistered sanitized file already exists; review required.")
        atomic_write(clean_path, result["sanitized_text"])
        clean_path.chmod(0o600)
        with database(db) as conn:
            conn.execute(
                "UPDATE resumes SET masking_status='MASKED',sanitized_markdown_path=?,"
                "sanitized_sha256=?,"
                "masking_reason=NULL,updated_at=CURRENT_TIMESTAMP WHERE document_id=?",
                (str(clean_path), digest(clean_path.read_bytes()), doc_id),
            )
            row = document(conn, doc_id)
        save_masking_identity(root, row, detected)
    identity = {
        "name": row["full_name"],
        "email": row["email_normalized"],
        "mobile": row["mobile_e164"],
    }
    blocks, warnings = input_eligibility(clean_path.read_text(encoding="utf-8"), detected, identity)
    with database(db) as conn:
        conn.execute(
            "UPDATE resumes SET processing_status=?,blocking_reasons_json=?,warnings_json=?,"
            "updated_at=CURRENT_TIMESTAMP WHERE document_id=?",
            (
                "BLOCKED" if blocks else "READY_FOR_LLM",
                json.dumps(blocks),
                json.dumps(warnings),
                doc_id,
            ),
        )
    if blocks:
        raise ProcessingError("PII screening requires local review.")


def reevaluate_document(root, db, doc_id):
    """Local eligibility migration only: no extraction rerun or LLM dispatch."""
    from app.core.batch import command_lock
    from run_llm import preflight

    with command_lock():
        with database(db) as conn:
            row = document(conn, doc_id)
            old = control(conn, doc_id)
            previous_masking_status = row["masking_status"]
            previous_blocks = json.loads(row["blocking_reasons_json"] or "[]")
            completed = conn.execute(
                "SELECT 1 FROM resume_parses WHERE document_id=? AND llm_status='COMPLETED'",
                (doc_id,),
            ).fetchone()
            if row["llm_status"] == "COMPLETED" or completed:
                return {"document_id": doc_id, "result": "completed_unchanged"}
            if row["extraction_status"] != "EXTRACTED":
                raise ProcessingError("A saved extraction is required for re-evaluation.")
            if old.get("state") in {"QUEUED", "EXTRACTING", "MASKING", "PARSING", "GENERATING"}:
                raise ProcessingError("Wait for active processing before re-evaluation.")
            if row["processing_status"] == "READY_FOR_LLM" and old.get("state") == "READY_FOR_LLM":
                original = Path(row["original_file_path"])
                original = original if original.is_absolute() else root / original
                if not original.is_file() or digest(original.read_bytes()) != doc_id:
                    raise ProcessingError("Original file integrity review required.")
                checked(root, row, "extracted")
                checked(root, row, "sanitized")
                preflight(row)
                return {"document_id": doc_id, "result": "already_ready"}
        # Old mismatch failures never saved sanitized text. Reuse extraction and invoke only
        # the unchanged local masker in that case; otherwise reuse the saved sanitized file.
        local_stages(root, db, doc_id)
        with database(db) as conn:
            row = document(conn, doc_id)
            preflight(row)
            meta = control(conn, doc_id)
            history = list(old.get("eligibility_history", []))
            history.append(
                {
                    "previous_state": old.get("state"),
                    "previous_error": old.get("error"),
                    "previous_masking_status": previous_masking_status,
                    "previous_blocking_reasons": previous_blocks,
                    "previous_updated_at": old.get("updated_at"),
                    "policy": "limited-mask-v2",
                }
            )
            meta.update(state="READY_FOR_LLM", stage=3, error=None, eligibility_history=history)
            conn.execute(
                "UPDATE resumes SET llm_status=COALESCE(llm_status,'QUEUED') WHERE document_id=?",
                (doc_id,),
            )
            from store import save_control

            save_control(conn, doc_id, meta)
            return {
                "document_id": doc_id,
                "result": "ready",
                "warnings": json.loads(row["warnings_json"]),
            }


def parse_document(root, db, doc_id):
    from app.core import config
    from app.core.batch import file_matches
    from app.core.database import update_resume
    from app.schemas.resume import ResumeProfile
    from app.services.llm_parser import (
        check_professional_json,
        make_chain,
        parse_resume,
        parser_signature,
    )
    from run_llm import groq_quota_wait, persist_json, preflight, retry_delay, temporary_error

    update_control(db, doc_id, state="PARSING", stage=3)
    with database(db) as conn:
        row = document(conn, doc_id)
        clean, identity = preflight(row)
        # Reuse an existing registered canonical version without an API request.
        if row["llm_status"] == "COMPLETED":
            version = selected_parse(conn, row)
            output = private_path(root, version["parsed_json_path"])
            if not file_matches(output, version["parsed_json_sha256"]):
                raise ProcessingError("Completed output integrity review required.")
            check_professional_json(
                ResumeProfile.model_validate_json(output.read_text(encoding="utf-8")), identity
            )
            return
        signature = digest((row["sanitized_sha256"] + parser_signature("groq")).encode())
        output = config.PRIVATE / "parsed" / "groq" / doc_id / (signature + ".json")
        old = conn.execute(
            "SELECT * FROM resume_parses WHERE document_id=? AND parser_signature=?",
            (doc_id, signature),
        ).fetchone()
        version = dict(old) if old else None
        if version and version["llm_status"] == "COMPLETED" and not output.is_file():
            raise ProcessingError("Completed output is missing; preserve its version for review.")
        meta = (
            json.loads(version["metadata_json"])
            if version
            else {
                "provider": "groq",
                "sanitized_sha256": row["sanitized_sha256"],
                "reasoning_effort": "medium",
                "max_output_tokens": config.GROQ_MAX_OUTPUT_TOKENS,
                "requests": [],
                "failure_history": [],
            }
        )
        if meta.get("next_retry_at", 0) > time.time():
            update_control(
                db,
                doc_id,
                state="DEFERRED",
                error="RATE_LIMIT",
                next_retry_at=meta["next_retry_at"],
            )
            return
        attempts = version["attempt_count"] if version else 0
        meta.setdefault("requests", [])
        meta.setdefault("failure_history", [])

        def save(state, sha=None):
            conn.execute(
                "INSERT INTO resume_parses(parse_id,document_id,model_name,parser_signature,"
                "parsed_json_path,parsed_json_sha256,llm_status,attempt_count,metadata_json) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id,parser_signature) DO UPDATE SET "
                "parsed_json_sha256=COALESCE(excluded.parsed_json_sha256,"
                "resume_parses.parsed_json_sha256),llm_status=excluded.llm_status,"
                "attempt_count=excluded.attempt_count,metadata_json=excluded.metadata_json",
                (
                    str(uuid.uuid4()),
                    doc_id,
                    config.GROQ_MODEL,
                    signature,
                    str(output),
                    sha,
                    state,
                    attempts,
                    json.dumps(meta),
                ),
            )
            conn.commit()

        def canonical(sha):
            update_resume(
                conn,
                doc_id,
                llm_status="COMPLETED",
                parsed_json_path=str(output),
                parsed_json_sha256=sha,
                model_name=config.GROQ_MODEL,
                parser_signature=signature,
                attempt_count=attempts,
                last_error_class=None,
                next_retry_at=None,
            )

        if output.exists():
            if not version or not file_matches(output, version["parsed_json_sha256"]):
                raise ProcessingError("Existing output version conflict.")
            check_professional_json(
                ResumeProfile.model_validate_json(output.read_text(encoding="utf-8")), identity
            )
            save("COMPLETED", version["parsed_json_sha256"])
            canonical(version["parsed_json_sha256"])
            return
        # Include provider headers from previous invocations in quota pacing.
        events = []
        for item in conn.execute(
            "SELECT metadata_json FROM resume_parses WHERE model_name=?", (config.GROQ_MODEL,)
        ):
            events.extend(json.loads(item[0]).get("requests", []))
        last = max(events, key=lambda e: e["at"]) if events else {}
        state = {"headers": last.get("headers", {}), "at": last.get("headers_at", time.time())}
        reserve = math.ceil(len(clean) / 3) + 2500 + config.GROQ_MAX_OUTPUT_TOKENS
        wait, daily = groq_quota_wait(conn, state, reserve)
        if wait and (daily or wait > 60):
            meta["next_retry_at"] = time.time() + wait
            save("DEFERRED")
            update_control(
                db,
                doc_id,
                state="DEFERRED",
                error="RATE_LIMIT",
                next_retry_at=meta["next_retry_at"],
            )
            return
        if wait:
            time.sleep(wait)
        if not config.GROQ_API_KEY:
            update_control(db, doc_id, state="FAILED", error="MISSING_API_KEY")
            return
        chain = make_chain(provider="groq", request_state=state)
        for retry in range(min(config.MAX_RETRIES, 1) + 1):
            attempts += 1
            save("PROCESSING")
            update_resume(conn, doc_id, llm_status="PROCESSING", attempt_count=attempts)
            event = {"at": time.time(), "tokens_reserved": reserve}
            metrics = {}
            try:
                payload = parse_resume(clean, chain, identity, metrics)
            except Exception as exc:
                transient = temporary_error(exc)
                wait, deferred = retry_delay(exc, retry) if transient else (0, False)
                code = getattr(exc, "status_code", None)
                # Every 429 is deferred for explicit employee retry; never loop on quota.
                deferred = deferred or code == 429
                event.update(
                    headers=state.get("headers", {}),
                    headers_at=time.time(),
                    seconds=time.time() - event["at"],
                    **metrics,
                )
                meta["requests"].append(event)
                meta["failure_history"].append(
                    {"at": time.time(), "error_class": type(exc).__name__, "http_status": code}
                )
                if deferred:
                    meta["next_retry_at"] = time.time() + max(wait, 60)
                save("DEFERRED" if deferred else "FAILED")
                update_resume(
                    conn,
                    doc_id,
                    llm_status="DEFERRED" if deferred else "FAILED",
                    last_error_class=type(exc).__name__,
                )
                if transient and not deferred and retry < min(config.MAX_RETRIES, 1):
                    time.sleep(wait)
                    continue
                update_control(
                    db,
                    doc_id,
                    state="DEFERRED" if deferred else "FAILED",
                    error="RATE_LIMIT" if deferred else "PARSING_FAILED",
                    next_retry_at=meta.get("next_retry_at"),
                )
                return
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            sha = digest(serialized.encode())
            event.update(
                headers=state.get("headers", {}),
                headers_at=time.time(),
                seconds=time.time() - event["at"],
                **metrics,
            )
            meta["requests"].append(event)
            meta.pop("next_retry_at", None)
            save("PROCESSING", sha)  # Hash checkpoint enables crash recovery without another call.
            persist_json(output, serialized)
            output.chmod(0o600)
            save("COMPLETED", sha)
            canonical(sha)
            return


def review_data(root, db, doc_id):
    from app.services.alter_resume import load_resume_for_export
    from run_llm import preflight

    with database(db) as conn:
        row = document(conn, doc_id)
        version = selected_parse(conn, row)
    original = Path(row["original_file_path"])
    original = original if original.is_absolute() else root / original
    if not original.is_file() or digest(original.read_bytes()) != doc_id:
        raise ProcessingError("Original file integrity review required.")
    checked(root, row, "extracted")
    checked(root, row, "sanitized")
    preflight(row)
    private_path(root, version["parsed_json_path"])
    presentation, provenance = load_resume_for_export(
        doc_id,
        parsed_json=version["parsed_json_path"],
        database=db,
    )
    return {
        "presentation": presentation,
        "parse_id": provenance["parse_id"],
        "sha256": provenance["parsed_json_sha256"],
    }


def export_document(root, db, doc_id):
    from generate_alter_resume import generate

    review_data(root, db, doc_id)
    with database(db) as conn:
        row = document(conn, doc_id)
        version = selected_parse(conn, row)
        meta = json.loads(version["metadata_json"])
        if (
            meta.get("review_status") != "APPROVED"
            or meta.get("reviewed_sha256") != version["parsed_json_sha256"]
        ):
            raise ProcessingError("Approve the current parse version before generation.")
    update_control(db, doc_id, state="GENERATING", stage=4)
    args = {"parsed_json": version["parsed_json_path"], "database": db, "require_approved": True}
    files, _ = generate(doc_id, format="both", **args)
    plain, _ = generate(doc_id, format="pdf", no_logo=True, **args)
    exports = {
        "branded_pdf": files["pdf"],
        "plain_pdf": plain["pdf"],
        "docx": files["docx"],
        "preview": str(Path(files["pdf"]).parent / "resume.html"),
    }
    hashes = {kind: digest(Path(path).read_bytes()) for kind, path in exports.items()}
    update_control(
        db,
        doc_id,
        state="COMPLETED",
        stage=5,
        error=None,
        exports=exports,
        export_hashes=hashes,
        exported_parse_id=version["parse_id"],
        exported_sha256=version["parsed_json_sha256"],
    )


def run_job(root, db, action, doc_id):
    from app.core.batch import command_lock

    try:
        with command_lock():
            if action == "process":
                with database(db) as conn:
                    meta = control(conn, doc_id)
                    if not meta.get("consent"):
                        raise ProcessingError("Candidate authorization is required.")
                local_stages(root, db, doc_id)
                parse_document(root, db, doc_id)
                with database(db) as conn:
                    row = document(conn, doc_id)
                if row["llm_status"] == "COMPLETED":
                    review_data(root, db, doc_id)  # Includes output privacy screening.
                    update_control(db, doc_id, state="REVIEW_REQUIRED", stage=4, error=None)
            else:
                export_document(root, db, doc_id)
    except ProcessingError:
        update_control(db, doc_id, state="REVIEW_REQUIRED", error="LOCAL_REVIEW_REQUIRED")
    except ImportError:
        update_control(db, doc_id, state="FAILED", error="DEPENDENCY_MISSING")
    except Exception:
        # Raw model/renderer exceptions can include resume text or credentials.
        with database(db) as conn:
            masking = control(conn, doc_id).get("state") == "MASKING"
            if masking:
                conn.execute(
                    "UPDATE resumes SET masking_status='FAILED' WHERE document_id=?", (doc_id,)
                )
        update_control(
            db,
            doc_id,
            state="REVIEW_REQUIRED" if masking else "FAILED",
            error="MASKING_FAILED" if masking else "PROCESSING_FAILED",
        )


def validate_upload(path, kind):
    if kind == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted or not reader.pages:
            raise ValueError("UnreadablePDF")
    else:
        from docx import Document

        Document(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("action", choices=["process", "export", "review", "validate", "reevaluate"])
    parser.add_argument("target")
    parser.add_argument("--kind", choices=["pdf", "docx"])
    args = parser.parse_args()
    root = args.repo.resolve()
    sys.path.insert(0, str(root))
    os.environ["JOBMITRA_DATABASE"] = str(args.db.resolve())
    os.environ["JOBMITRA_GROQ_MODEL"] = "openai/gpt-oss-120b"
    os.environ["JOBMITRA_GROQ_REASONING_EFFORT"] = "medium"
    os.environ["JOBMITRA_PROMPT_FILE"] = str(root / "prompts/resume_extraction_v3.md")
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
            if args.action == "reevaluate":
                result = reevaluate_document(root, args.db, args.target)
            elif args.action == "review":
                result = review_data(root, args.db, args.target)
            elif args.action == "validate":
                validate_upload(private_path(root, args.target), args.kind)
                result = {"valid": True}
            else:
                run_job(root, args.db, args.action, args.target)
                result = {"done": True}
        print(json.dumps(result))
    except Exception:
        print(json.dumps({"error": "PROCESSOR_REQUEST_FAILED"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
