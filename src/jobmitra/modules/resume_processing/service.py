"""Small private-file/SQLite adapter and one-slot subprocess supervisor."""

import json
import os
import secrets
import subprocess
import threading
import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from .store import (
    ACTIVE,
    CONTROL,
    ProcessingError,
    control,
    database,
    digest,
    document,
    private_path,
    save_control,
    selected_parse,
    status,
    update_control,
)


class Processor:
    def __init__(self, settings):
        if not settings.resume_processing_repo or not settings.resume_processing_python:
            raise ProcessingError("Configure the processor repository and Python executable.", 503)
        self.root = settings.resume_processing_repo.expanduser().resolve()
        self.python = settings.resume_processing_python.expanduser().resolve()
        self.db = (
            (
                settings.resume_processing_database
                or self.root / "private/jobmitra_candidates.sqlite3"
            )
            .expanduser()
            .resolve()
        )
        if (
            not self.python.is_file()
            or not (self.root / "app/services/llm_parser.py").is_file()
            or not self.db.is_file()
        ):
            raise ProcessingError("Configured processor components are unavailable.", 503)
        self.max_bytes = settings.resume_max_bytes
        self._lock = threading.Lock()

    def bridge(self, action, target, *, kind=None, timeout=30):
        command = [
            str(self.python),
            str(Path(__file__).with_name("bridge.py")),
            "--repo",
            str(self.root),
            "--db",
            str(self.db),
            action,
            str(target),
        ]
        if kind:
            command.extend(["--kind", kind])
        env = os.environ.copy()
        # Child credentials come from its existing .env or inherited environment, never argv.
        env.update(PYTHONUNBUFFERED="1", TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2")
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                env=env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=True,
            )
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, ValueError, OSError):
            raise ProcessingError("Processor could not complete this operation.", 422) from None

    def candidates(self):
        with database(self.db) as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT candidate_id,full_name FROM candidates WHERE full_name IS NOT NULL "
                    "ORDER BY updated_at DESC,candidate_id LIMIT 100"
                )
            ]

    def register(self, values):
        name, email, mobile = values.full_name, values.email, values.mobile
        with database(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            matches = conn.execute(
                "SELECT * FROM candidates WHERE (? IS NOT NULL AND email_normalized=?) "
                "OR (? IS NOT NULL AND mobile_e164=?)",
                (email, email, mobile, mobile),
            ).fetchall()
            if values.candidate_id:
                candidate = conn.execute(
                    "SELECT * FROM candidates WHERE candidate_id=?", (str(values.candidate_id),)
                ).fetchone()
                if (
                    not candidate
                    or " ".join((candidate["full_name"] or "").split()).casefold()
                    != name.casefold()
                    or any(r["candidate_id"] != str(values.candidate_id) for r in matches)
                    or any(
                        candidate[k] and v and candidate[k] != v
                        for k, v in [("email_normalized", email), ("mobile_e164", mobile)]
                    )
                ):
                    raise ProcessingError(
                        "Candidate identity conflicts; review local records first."
                    )
                candidate_id = candidate["candidate_id"]
            else:
                if matches:
                    raise ProcessingError(
                        "A contact already belongs to a local candidate. Review and explicitly "
                        "select the existing candidate; records were not merged."
                    )
                candidate_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO candidates(candidate_id,full_name,email_normalized,mobile_e164,"
                    "identity_status) VALUES(?,?,?,?,'CONFIRMED')",
                    (candidate_id, name, email, mobile),
                )
        return {"candidate_id": candidate_id, "full_name": name}

    def upload(self, candidate_id, data, kind, *, consent, location, actor):
        if not consent:
            raise ProcessingError("Candidate authorization is required.", 422)
        if kind not in {"pdf", "docx"} or not data or len(data) > self.max_bytes:
            raise ProcessingError("Upload a PDF or DOCX within the configured size limit.", 422)
        if kind == "pdf":
            if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
                raise ProcessingError("The file is not a readable PDF.", 422)
        else:
            try:
                with zipfile.ZipFile(BytesIO(data)) as archive:
                    if (
                        not {"[Content_Types].xml", "word/document.xml"} <= set(archive.namelist())
                        or len(archive.infolist()) > 2000
                        or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024
                    ):
                        raise ValueError
            except (zipfile.BadZipFile, ValueError):
                raise ProcessingError("The file is not a supported DOCX.", 422) from None
        doc_id = digest(data)
        with database(self.db) as conn:
            if not conn.execute(
                "SELECT 1 FROM candidates WHERE candidate_id=?", (candidate_id,)
            ).fetchone():
                raise ProcessingError("Candidate not found.", 404)
            existing = conn.execute(
                "SELECT * FROM resumes WHERE document_id=?", (doc_id,)
            ).fetchone()
            if existing and existing["candidate_id"] != candidate_id:
                raise ProcessingError(
                    "These resume bytes are linked to another candidate; review required."
                )
        folder = private_path(self.root, "private/sop_uploads")
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = folder / (secrets.token_hex(16) + "." + kind)
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
            temporary.chmod(0o600)
            self.bridge("validate", str(temporary), kind=kind)
            with database(self.db) as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT * FROM resumes WHERE document_id=?", (doc_id,)
                ).fetchone()
                if existing:
                    if existing["candidate_id"] != candidate_id:
                        raise ProcessingError("Resume identity conflict; review required.")
                else:
                    destination = folder / (doc_id + "." + kind)
                    if destination.exists():
                        if digest(destination.read_bytes()) != doc_id:
                            raise ProcessingError("Stored original integrity conflict.")
                    else:
                        # Same-volume no-clobber publication; retain any prior original.
                        os.link(temporary, destination)
                    conn.execute(
                        "INSERT INTO resumes(document_id,document_sha256,candidate_id,"
                        "original_file_path,extraction_status,masking_status,processing_status) "
                        "VALUES(?,?,?,?,'PENDING','PENDING','BLOCKED')",
                        (doc_id, doc_id, candidate_id, str(destination)),
                    )
                meta = control(conn, doc_id)
                meta.update(
                    consent=True, authorized_by=actor, authorized_at=time.time(), location=location
                )
                meta.setdefault("state", "UPLOADED")
                meta.setdefault("stage", 1)
                save_control(conn, doc_id, meta)
                return status(conn, doc_id)
        finally:
            temporary.unlink(missing_ok=True)

    def documents(self):
        with database(self.db) as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    "SELECT document_id FROM resume_parses WHERE parser_signature=? "
                    "ORDER BY created_at DESC LIMIT 30",
                    (CONTROL,),
                )
            ]
            return [status(conn, doc_id) for doc_id in ids]

    def start(self, doc_id, action):
        with self._lock, database(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            document(conn, doc_id)
            for row in conn.execute(
                "SELECT document_id FROM resume_parses WHERE parser_signature=?", (CONTROL,)
            ).fetchall():
                if status(conn, row[0])["state"] in ACTIVE:
                    raise ProcessingError(
                        "One resume is already processing. Wait for it to finish."
                    )
            meta = control(conn, doc_id)
            if not meta.get("consent"):
                raise ProcessingError("Upload with candidate authorization before processing.", 422)
            if meta.get("next_retry_at", 0) and meta["next_retry_at"] > time.time():
                raise ProcessingError("Provider retry time has not arrived yet.")
            if action == "export":
                version = selected_parse(conn, document(conn, doc_id))
                reviewed = json.loads(version["metadata_json"])
                if (
                    reviewed.get("review_status") != "APPROVED"
                    or reviewed.get("reviewed_sha256") != version["parsed_json_sha256"]
                ):
                    raise ProcessingError("Approve the current parse before generating resumes.")
            elif meta.get("state") in {"REVIEW_REQUIRED", "COMPLETED"} and not meta.get("error"):
                return status(conn, doc_id)  # Duplicate click cannot produce another model request.
            meta.update(
                state="QUEUED",
                error=None,
                started_at=time.time(),
                exports={},
                stage=4 if action == "export" else 1,
            )
            save_control(conn, doc_id, meta)
        thread = threading.Thread(target=self._run, args=(doc_id, action), daemon=True)
        thread.start()
        with database(self.db) as conn:
            return status(conn, doc_id)

    def _run(self, doc_id, action):
        try:
            self.bridge(action, doc_id, timeout=900)
        except ProcessingError:
            update_control(self.db, doc_id, state="FAILED", error="WORKER_STOPPED")

    def review(self, doc_id):
        return self.bridge("review", doc_id)

    def approve(self, doc_id, values, actor):
        # Validate schema, presentation and privacy in the processor environment first.
        current = self.review(doc_id)
        if current["parse_id"] != str(values.parse_id) or current["sha256"] != values.sha256:
            raise ProcessingError("The parsed version changed. Reload and review it again.")
        with database(self.db) as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = status(conn, doc_id)
            if state["state"] in ACTIVE:
                raise ProcessingError("Wait for processing to finish before review.")
            version = selected_parse(conn, document(conn, doc_id))
            if (
                version["parse_id"] != str(values.parse_id)
                or version["parsed_json_sha256"] != values.sha256
            ):
                raise ProcessingError("The parsed version changed. Review it again.")
            meta = json.loads(version["metadata_json"])
            meta.update(
                review_status="APPROVED" if values.approved else "REJECTED",
                reviewed_by=actor,
                reviewed_at=time.time(),
                reviewed_sha256=values.sha256,
            )
            conn.execute(
                "UPDATE resume_parses SET metadata_json=? WHERE parse_id=?",
                (json.dumps(meta), version["parse_id"]),
            )
            job = control(conn, doc_id)
            job.update(
                state="APPROVED" if values.approved else "REVIEW_REQUIRED",
                error=None if values.approved else "REJECTED",
                exports={},
            )
            save_control(conn, doc_id, job)
            return status(conn, doc_id)

    def download(self, doc_id, kind):
        if kind not in {"preview", "branded_pdf", "plain_pdf", "docx", "original"}:
            raise ProcessingError("Download not found.", 404)
        with database(self.db) as conn:
            row = document(conn, doc_id)
            meta = control(conn, doc_id)
            if kind == "original":
                # Only web-managed originals are served; legacy source directories stay private.
                path = private_path(self.root, row["original_file_path"])
                expected = doc_id
            else:
                version = selected_parse(conn, row)
                review = json.loads(version["metadata_json"])
                if (
                    meta.get("state") != "COMPLETED"
                    or kind not in meta.get("exports", {})
                    or meta.get("exported_parse_id") != version["parse_id"]
                    or meta.get("exported_sha256") != version["parsed_json_sha256"]
                    or review.get("review_status") != "APPROVED"
                    or review.get("reviewed_sha256") != version["parsed_json_sha256"]
                ):
                    raise ProcessingError("Generate resumes from the current approved parse first.")
                parsed = private_path(self.root, version["parsed_json_path"])
                if (
                    not parsed.is_file()
                    or digest(parsed.read_bytes()) != version["parsed_json_sha256"]
                ):
                    raise ProcessingError("Parsed output integrity review required.")
                path = private_path(self.root, meta["exports"][kind])
                expected = meta["export_hashes"][kind]
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise ProcessingError("Download integrity review required.")
            return path
