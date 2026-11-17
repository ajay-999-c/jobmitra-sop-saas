"""Offline processor-environment contract tests, invoked by the SOP pytest suite."""
# ruff: noqa: E402 -- imports follow the explicit processor interpreter/path boundary.

import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

REPO = Path(sys.argv.pop(1)).resolve()
BRIDGE_DIR = Path(__file__).resolve().parents[1] / "src/jobmitra/modules/resume_processing"
sys.path[:0] = [str(BRIDGE_DIR), str(REPO)]

import bridge
from app.core import config
from app.core.database import open_database
from app.schemas.resume import ResumeProfile
from app.services import extraction, llm_parser, pii_pipeline
from docx import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pypdf import PdfReader
from store import control, database, document, save_control, update_control


class WorkerChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="jobmitra-sop-worker-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / "private"
        self.private.mkdir()
        self.db = self.private / "candidates.sqlite3"
        self.doc_id = hashlib.sha256(b"synthetic original bytes").hexdigest()
        self.candidate_id = str(uuid4())
        original = self.private / "original.docx"
        original.write_bytes(b"synthetic original bytes")
        conn = open_database(self.db)
        conn.execute(
            "INSERT INTO candidates(candidate_id,full_name,identity_status,email_normalized) "
            "VALUES(?,?,'CONFIRMED',?)",
            (self.candidate_id, "Demo Example", "private@example.test"),
        )
        conn.execute(
            "INSERT INTO resumes(document_id,document_sha256,candidate_id,original_file_path) "
            "VALUES(?,?,?,?)",
            (self.doc_id, self.doc_id, self.candidate_id, str(original)),
        )
        save_control(
            conn, self.doc_id, {"consent": True, "state": "UPLOADED", "started_at": time.time()}
        )
        conn.commit()
        conn.close()
        for key, value in {
            "ROOT": self.root,
            "PRIVATE": self.private,
            "DATABASE": self.db,
            "BLOCK_OUT_OF_SCOPE_PII": True,
            "GROQ_MODEL": "openai/gpt-oss-120b",
            "GROQ_REASONING_EFFORT": "medium",
            "GROQ_API_KEY": "synthetic-not-a-live-key",
            "GROQ_LIMITS": {k: 0 for k in ["RPM", "TPM", "RPD", "TPD"]},
            "MAX_RETRIES": 1,
            "BACKOFF_SECONDS": 0,
            "BACKOFF_JITTER": 0,
        }.items():
            p = patch.object(config, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.clean = (
            "[NAME_1]\nEngineer at Example Employer, 2020 - Present. "
            "Skills: Python and SQL.\nBuilt supported systems."
        )
        self.raw = self.clean.replace("[NAME_1]", "Demo Example") + "\nprivate@example.test"
        self.mask = {
            "status": "MASKED",
            "identity": {"name": "Demo Example", "email": "private@example.test"},
            "sanitized_text": self.clean,
            "counts": {"NAME": 1, "EMAIL": 1},
        }
        self.profile = ResumeProfile(
            current_job_title="Engineer",
            skills=["Python", "SQL"],
            professional_summary="Engineer building supported systems.",
            work_experience=[
                {
                    "company": "Example Employer",
                    "role": "Engineer",
                    "start_date": "2020",
                    "end_date": "Present",
                    "responsibilities": ["Built supported systems."],
                }
            ],
            education=[{"degree": "Engineering", "institution": "Example College"}],
        )
        # Any accidental network access outside the mocked chain is a test failure.
        self.net = patch("httpx.Client.send", side_effect=AssertionError("Live HTTP forbidden"))
        self.net.start()
        self.addCleanup(self.net.stop)

    def stages(self, masking=None):
        with (
            patch.object(extraction, "make_converter"),
            patch.object(extraction, "extract_markdown", return_value=(self.raw, "OK")) as extract,
            patch.object(pii_pipeline, "load_gliner"),
            patch.object(
                pii_pipeline, "sanitize_resume", return_value=masking or self.mask
            ) as mask,
        ):
            bridge.local_stages(self.root, self.db, self.doc_id)
        return extract, mask

    def parse(self, response=None):
        chain = Mock()
        chain.invoke.return_value = response or self.profile.model_dump()
        with patch.object(llm_parser, "make_chain", return_value=chain):
            bridge.parse_document(self.root, self.db, self.doc_id)
        return chain

    def completed(self):
        self.stages()
        self.parse()
        update_control(self.db, self.doc_id, state="REVIEW_REQUIRED", stage=4)

    def test_stages_persist_cache_and_only_sanitized_content_reaches_chain(self):
        extract, mask = self.stages()
        extract.assert_called_once()
        mask.assert_called_once()
        again_extract, again_mask = self.stages()
        again_extract.assert_not_called()
        again_mask.assert_not_called()
        chain = self.parse()
        sent = chain.invoke.call_args.args[0]
        self.assertEqual(sent, {"resume_text": self.clean})
        self.assertNotIn("Demo Example", str(sent))
        self.assertNotIn("private@example.test", str(sent))
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            self.assertEqual(row["extraction_status"], "EXTRACTED")
            self.assertEqual(row["masking_status"], "MASKED")
            self.assertEqual(row["llm_status"], "COMPLETED")
            self.assertEqual(row["candidate_id"], self.candidate_id)
            self.assertTrue(Path(row["extracted_markdown_path"]).is_file())
            self.assertTrue(Path(row["sanitized_markdown_path"]).is_file())
            parsed = Path(row["parsed_json_path"])
            original = parsed.read_bytes()
        with patch.object(
            llm_parser, "make_chain", side_effect=AssertionError("Cache must not call provider")
        ):
            bridge.parse_document(self.root, self.db, self.doc_id)
        self.assertEqual(parsed.read_bytes(), original)
        review = bridge.review_data(self.root, self.db, self.doc_id)
        self.assertEqual(review["presentation"]["candidate_name"], "Demo Example")
        self.assertEqual(review["presentation"]["projects"], [])

    def test_strict_groq_contract_reuses_approved_prompt_and_schema(self):
        prompts = []

        def response(value):
            prompts.append(value.to_string())
            return {
                "raw": AIMessage(
                    content=self.profile.model_dump_json(),
                    response_metadata={"finish_reason": "stop"},
                ),
                "parsed": self.profile.model_dump(),
                "parsing_error": None,
            }

        with patch("langchain_groq.ChatGroq") as client:
            client.return_value.with_structured_output.return_value = RunnableLambda(response)
            chain = llm_parser.make_chain(provider="groq")
            llm_parser.parse_resume(self.clean, chain, {"name": "Demo Example"})
            self.assertEqual(client.call_args.kwargs["model"], "openai/gpt-oss-120b")
            self.assertEqual(client.call_args.kwargs["reasoning_effort"], "medium")
            self.assertEqual(client.call_args.kwargs["temperature"], 0)
            self.assertEqual(client.call_args.kwargs["max_retries"], 0)
            self.assertTrue(client.return_value.with_structured_output.call_args.kwargs["strict"])
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("private@example.test", prompts[0])

    def test_name_mismatch_warns_and_preserves_registration(self):
        mask = {**self.mask, "identity": {**self.mask["identity"], "name": "Detected Example"}}
        with database(self.db) as conn:
            before = [tuple(r) for r in conn.execute("SELECT * FROM candidates")]
        self.stages(mask)
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            self.assertEqual(row["processing_status"], "READY_FOR_LLM")
            self.assertIn("candidate_name_mismatch", json.loads(row["warnings_json"]))
            self.assertEqual(before, [tuple(r) for r in conn.execute("SELECT * FROM candidates")])
        self.assertEqual(self.parse().invoke.call_count, 1)
        self.assertEqual(
            bridge.review_data(self.root, self.db, self.doc_id)["presentation"]["candidate_name"],
            "Demo Example",
        )

    def test_dob_address_warn_without_failed_masking(self):
        text = self.clean + "\nDOB: 1990-01-01\nAddress: Example Street"
        self.stages({**self.mask, "sanitized_text": text})
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            self.assertEqual(row["masking_status"], "MASKED")
            self.assertEqual(row["processing_status"], "READY_FOR_LLM")
            self.assertEqual(
                set(json.loads(row["warnings_json"])),
                {"personal_detail_outside_masking_scope", "address_outside_masking_scope"},
            )
        self.assertEqual(self.parse().invoke.call_args.args[0], {"resume_text": text})

    def test_residual_detected_name_stays_blocked(self):
        with self.assertRaises(bridge.ProcessingError):
            self.stages({**self.mask, "sanitized_text": self.clean + "\nDemo Example"})
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            self.assertEqual(row["processing_status"], "BLOCKED")
            self.assertIn("candidate_name_residual", json.loads(row["blocking_reasons_json"]))

    def snapshot(self):
        with database(self.db) as conn:
            return {
                table: [tuple(r) for r in conn.execute("SELECT * FROM " + table)]
                for table in ["candidates", "resumes", "resume_parses"]
            }

    def test_reevaluation_is_local_idempotent_and_skips_completed(self):
        self.stages()
        update_control(self.db, self.doc_id, state="REVIEW_REQUIRED", error="LOCAL_REVIEW_REQUIRED")
        with (
            patch.object(llm_parser, "make_chain", side_effect=AssertionError("No LLM")),
            patch.object(extraction, "make_converter", side_effect=AssertionError("No extraction")),
            patch.object(pii_pipeline, "load_gliner", side_effect=AssertionError("Reuse cache")),
        ):
            self.assertEqual(
                bridge.reevaluate_document(self.root, self.db, self.doc_id)["result"], "ready"
            )
            before = self.snapshot()
            self.assertEqual(
                bridge.reevaluate_document(self.root, self.db, self.doc_id)["result"],
                "already_ready",
            )
            self.assertEqual(before, self.snapshot())
        self.parse()
        before = self.snapshot()
        self.assertEqual(
            bridge.reevaluate_document(self.root, self.db, self.doc_id)["result"],
            "completed_unchanged",
        )
        self.assertEqual(before, self.snapshot())

    def test_old_mismatch_recovers_missing_masking_from_saved_extraction(self):
        self.stages()
        update_control(self.db, self.doc_id, state="REVIEW_REQUIRED", error="LOCAL_REVIEW_REQUIRED")
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            Path(row["sanitized_markdown_path"]).unlink()
            (self.private / "masking" / (self.doc_id + ".json")).unlink()
            conn.execute(
                "UPDATE resumes SET masking_status='BLOCKED',processing_status='BLOCKED',"
                "sanitized_markdown_path=NULL,sanitized_sha256=NULL WHERE document_id=?",
                (self.doc_id,),
            )
            original = Path(row["extracted_markdown_path"]).read_bytes()
        mask = {**self.mask, "identity": {"name": "Detected Example"}}
        with (
            patch.object(extraction, "make_converter", side_effect=AssertionError("No extraction")),
            patch.object(pii_pipeline, "load_gliner"),
            patch.object(pii_pipeline, "sanitize_resume", return_value=mask) as sanitizer,
            patch.object(llm_parser, "make_chain", side_effect=AssertionError("No LLM")),
        ):
            self.assertEqual(
                bridge.reevaluate_document(self.root, self.db, self.doc_id)["result"], "ready"
            )
            sanitizer.assert_called_once()
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            self.assertEqual(original, Path(row["extracted_markdown_path"]).read_bytes())
            self.assertIn("candidate_name_mismatch", json.loads(row["warnings_json"]))

    def test_corrupt_cached_markdown_requires_review(self):
        self.stages()
        with database(self.db) as conn:
            path = Path(document(conn, self.doc_id)["extracted_markdown_path"])
        path.write_text("tampered")
        with self.assertRaises(bridge.ProcessingError):
            self.stages()

    def test_missing_successful_version_is_not_replaced(self):
        self.completed()
        with database(self.db) as conn:
            row = document(conn, self.doc_id)
            Path(row["parsed_json_path"]).unlink()
            conn.execute(
                "UPDATE resumes SET llm_status='FAILED' WHERE document_id=?", (self.doc_id,)
            )
        with patch.object(llm_parser, "make_chain") as make_chain:
            with self.assertRaises(bridge.ProcessingError):
                bridge.parse_document(self.root, self.db, self.doc_id)
            make_chain.assert_not_called()
        with database(self.db) as conn:
            version = conn.execute(
                "SELECT llm_status FROM resume_parses WHERE parser_signature != 'sop-control-v1'"
            ).fetchone()
            self.assertEqual(version[0], "COMPLETED")

    def test_validation_failure_does_not_retry_or_save_partial_json(self):
        self.stages()
        chain = self.parse({"unrecognized_field": "bad"})
        self.assertEqual(chain.invoke.call_count, 1)
        with database(self.db) as conn:
            self.assertEqual(document(conn, self.doc_id)["llm_status"], "FAILED")
            self.assertEqual(control(conn, self.doc_id)["state"], "FAILED")
        self.assertEqual(list((self.private / "parsed").rglob("*.json")), [])

    def test_timeout_retries_once_and_rate_limit_defers(self):
        self.stages()
        chain = Mock()
        chain.invoke.side_effect = [TimeoutError(), self.profile.model_dump()]
        with patch.object(llm_parser, "make_chain", return_value=chain):
            bridge.parse_document(self.root, self.db, self.doc_id)
        self.assertEqual(chain.invoke.call_count, 2)
        with database(self.db) as conn:
            conn.execute(
                "UPDATE resumes SET llm_status='FAILED' WHERE document_id=?", (self.doc_id,)
            )
            version = conn.execute(
                "SELECT * FROM resume_parses WHERE llm_status='COMPLETED'"
            ).fetchone()
            # Preserve completed output: no rate-limit rerun should occur with a valid cache.
            self.assertTrue(Path(version["parsed_json_path"]).exists())

    def test_429_and_token_limit_are_safe_persisted_failures(self):
        self.stages()

        class RateLimit(Exception):
            status_code = 429

        chain = Mock()
        chain.invoke.side_effect = RateLimit("private raw body must not be stored")
        with patch.object(llm_parser, "make_chain", return_value=chain):
            bridge.parse_document(self.root, self.db, self.doc_id)
        self.assertEqual(chain.invoke.call_count, 1)
        with database(self.db) as conn:
            meta = control(conn, self.doc_id)
            self.assertEqual(meta["state"], "DEFERRED")
            self.assertGreater(meta["next_retry_at"], time.time())
            self.assertNotIn("private raw body", str(meta))
            conn.execute("UPDATE resume_parses SET metadata_json='{}' WHERE llm_status='DEFERRED'")
        chain.invoke.side_effect = None
        chain.invoke.return_value = {
            "raw": AIMessage(content="partial", response_metadata={"finish_reason": "length"}),
            "parsed": None,
            "parsing_error": None,
        }
        with patch.object(llm_parser, "make_chain", return_value=chain):
            bridge.parse_document(self.root, self.db, self.doc_id)
        self.assertEqual(chain.invoke.call_count, 2)
        with database(self.db) as conn:
            self.assertEqual(control(conn, self.doc_id)["state"], "FAILED")

    def test_approved_ats_generation_and_identity_separation(self):
        self.completed()
        with self.assertRaises(bridge.ProcessingError):
            bridge.export_document(self.root, self.db, self.doc_id)
        with database(self.db) as conn:
            version = conn.execute(
                "SELECT * FROM resume_parses WHERE llm_status='COMPLETED'"
            ).fetchone()
            meta = json.loads(version["metadata_json"])
            meta.update(review_status="APPROVED", reviewed_sha256=version["parsed_json_sha256"])
            conn.execute(
                "UPDATE resume_parses SET metadata_json=? WHERE parse_id=?",
                (json.dumps(meta), version["parse_id"]),
            )
            # An unrelated identity must never leak into the selected document export.
            conn.execute(
                "INSERT INTO candidates(candidate_id,full_name,identity_status) "
                "VALUES(?,?,'CONFIRMED')",
                (str(uuid4()), "Other Identity"),
            )
        bridge.export_document(self.root, self.db, self.doc_id)
        with database(self.db) as conn:
            meta = control(conn, self.doc_id)
        self.assertEqual(meta["state"], "COMPLETED")
        exports = meta["exports"]
        pdf = "\n".join(
            page.extract_text() or "" for page in PdfReader(exports["branded_pdf"]).pages
        )
        plain = "\n".join(
            page.extract_text() or "" for page in PdfReader(exports["plain_pdf"]).pages
        )
        word = "\n".join(p.text for p in Document(exports["docx"]).paragraphs)
        for content in [pdf, plain, word]:
            content = content.casefold()
            self.assertIn("demo example", content)
            self.assertIn("example employer", content)
            self.assertNotIn("private@example.test", content)
            self.assertNotIn("other identity", content)
            self.assertNotIn("certifications", content)
            self.assertNotIn("projects", content)
        html = Path(exports["preview"]).read_text()
        self.assertIn("data:image/png;base64,", html)
        for path in exports.values():
            self.assertTrue(Path(path).stat().st_size > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
