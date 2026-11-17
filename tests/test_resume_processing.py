"""Local SQLite endpoints with synthetic data; no PostgreSQL/model/API calls."""

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.resume_processing import service
from jobmitra.modules.resume_processing.router import CandidateInput
from jobmitra.modules.resume_processing.store import (
    ProcessingError,
    control,
    database,
    private_path,
    save_control,
    status,
)

REPO = Path(os.getenv("JOBMITRA_TEST_PROCESSOR_REPO", "../jobmitra-resume-processing")).resolve()
PYTHON = Path(
    os.getenv("JOBMITRA_TEST_PROCESSOR_PYTHON", "/Users/mac/miniconda3/envs/gen_ai/bin/python")
)
HEADERS = {"X-Jobmitra-UI": "1", "Origin": "http://localhost"}
API = "/api/resume-processing"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if not PYTHON.is_file() or not REPO.is_dir():
        pytest.skip("Set JOBMITRA_TEST_PROCESSOR_REPO and JOBMITRA_TEST_PROCESSOR_PYTHON")
    root = tmp_path / "processor"
    (root / "private").mkdir(parents=True)
    (root / "app/services").mkdir(parents=True)
    (root / "app/services/llm_parser.py").touch()
    db = root / "private/candidates.sqlite3"
    setup = """
import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.core.database import open_database
from docx import Document
open_database(Path(sys.argv[2])).close()
doc=Document();doc.add_paragraph('Synthetic Candidate')
doc.add_paragraph('Python engineer at Example Employer');doc.save(sys.argv[3])
from pypdf import PdfWriter
pdf=PdfWriter();pdf.add_blank_page(width=612,height=792);pdf.write(sys.argv[4])
"""
    subprocess.run(
        [
            str(PYTHON),
            "-c",
            setup,
            str(REPO),
            str(db),
            str(root / "fixture.docx"),
            str(root / "fixture.pdf"),
        ],
        check=True,
    )
    engine = Mock()
    engine.connect.side_effect = AssertionError("PostgreSQL must not be used")
    monkeypatch.setattr("jobmitra.main.build_engine", lambda _: engine)
    monkeypatch.setattr(
        "jobmitra.core.pages.list_staff", Mock(side_effect=AssertionError("No staff query"))
    )
    settings = Settings(
        _env_file=None,
        db_host="invalid.example",
        db_name="unused",
        db_user="unused",
        db_password="unused",
        resume_processing_enabled=True,
        resume_processing_repo=root,
        resume_processing_python=PYTHON,
        resume_processing_database=db,
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        yield client, root, db, settings
    engine.connect.assert_not_called()


def register(client, **values):
    return client.post(
        API + "/candidates",
        headers=HEADERS,
        json={"full_name": "Synthetic Candidate", "consent": True, **values},
    )


def upload(client, root, candidate_id, kind="docx", **headers):
    return client.post(
        API + f"/candidates/{candidate_id}/documents",
        content=(root / ("fixture." + kind)).read_bytes(),
        headers={
            **HEADERS,
            "Content-Type": "application/octet-stream",
            "X-Resume-Format": kind,
            "X-Candidate-Consent": "confirmed",
            **headers,
        },
    )


def test_no_login_on_localhost_and_postgres_independent_page(workspace):
    client, _, _, settings = workspace
    page = client.get("/resume-processing")
    assert page.status_code == 200
    assert "www-authenticate" not in page.headers
    assert "Signed in:" not in page.text
    assert 'href="/resume-processing" aria-current="page"' in page.text
    assert "unsafe-inline" not in page.headers["content-security-policy"]
    assert client.get(API + "/health").json()["storage"] == "sqlite"
    for path in [
        "/resume-processing",
        API + "/health",
        API + "/candidates",
        API + "/documents/" + "a" * 64 + "/downloads/original",
    ]:
        response = client.get("http://remote.example" + path)
        assert response.status_code == 403
        assert "www-authenticate" not in response.headers
    with TestClient(
        client.app, base_url="http://localhost", client=("192.0.2.10", 50000)
    ) as remote:
        assert remote.get("/resume-processing").status_code == 403
        assert remote.get(API + "/health").status_code == 403
    settings.resume_processing_enabled = False
    assert client.get("/resume-processing").status_code == 404


def test_safe_candidate_validation_and_origin(workspace):
    client, _, _, _ = workspace
    for values in [
        {"full_name": ""},
        {"email": "private-invalid-contact"},
        {"mobile": "123"},
        {"consent": False},
        {"full_name": "<script>"},
    ]:
        result = register(client, **values)
        assert result.status_code == 422
        assert "private-invalid-contact" not in result.text
        assert "input" not in result.json()
    body = {"full_name": "Example Candidate", "consent": True}
    assert (
        client.post(
            API + "/candidates", json=body, headers={**HEADERS, "Origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert client.post(API + "/candidates", json=body).status_code == 403
    assert (
        client.post(
            API + "/candidates",
            content=b"x" * 17000,
            headers={**HEADERS, "Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_matching_requires_explicit_identity_and_never_name_only(workspace):
    client, _, db, _ = workspace
    a = register(client, email="synthetic@example.test", mobile="9876543210").json()
    assert register(client, email="synthetic@example.test").status_code == 409
    assert (
        register(client, full_name="Other Candidate", email="synthetic@example.test").status_code
        == 409
    )
    selected = register(client, email="synthetic@example.test", candidate_id=a["candidate_id"])
    assert selected.json()["candidate_id"] == a["candidate_id"]
    b = register(client).json()
    assert b["candidate_id"] != a["candidate_id"]
    with database(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT mobile_e164 FROM candidates WHERE candidate_id=?", (a["candidate_id"],)
            ).fetchone()[0]
            == "+919876543210"
        )


@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_format_upload_idempotence_and_identity_link(workspace, kind):
    client, root, db, _ = workspace
    candidate = register(client).json()["candidate_id"]
    first = upload(client, root, candidate, kind)
    assert first.status_code == 200, first.text
    doc_id = first.json()["document_id"]
    assert upload(client, root, candidate, kind).json()["document_id"] == doc_id
    other = register(client, full_name="Different Candidate").json()["candidate_id"]
    assert upload(client, root, other, kind).status_code == 409
    with database(db) as conn:
        row = conn.execute("SELECT * FROM resumes WHERE document_id=?", (doc_id,)).fetchone()
        assert row["candidate_id"] == candidate
        assert (
            Path(row["original_file_path"]).read_bytes()
            == (root / ("fixture." + kind)).read_bytes()
        )
        assert conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] == 1
    assert client.get(API + "/documents").json()[0]["state"] == "UPLOADED"
    assert client.get(API + f"/documents/{doc_id}/downloads/original").status_code == 200
    assert client.get(API + f"/documents/{doc_id}/downloads/docx").status_code == 409
    assert client.get(API + f"/documents/{'b' * 64}").status_code == 404


def test_bad_uploads_and_consent_do_not_register_resume(workspace):
    client, root, db, settings = workspace
    candidate = register(client).json()["candidate_id"]
    assert upload(client, root, candidate, **{"X-Candidate-Consent": ""}).status_code == 422
    assert upload(client, root, candidate, **{"X-Resume-Format": "exe"}).status_code == 422
    result = client.post(
        API + f"/candidates/{candidate}/documents",
        content=b"%PDF-fake%%EOF",
        headers={**HEADERS, "X-Resume-Format": "pdf", "X-Candidate-Consent": "confirmed"},
    )
    assert result.status_code == 422
    assert (
        client.post(
            API + f"/candidates/{candidate}/documents",
            content=b"x" * (settings.resume_max_bytes + 1),
            headers=HEADERS,
        ).status_code
        == 413
    )
    with database(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] == 0


def test_single_job_claim_status_refresh_and_restart_timeout(workspace, monkeypatch):
    client, root, db, _ = workspace
    candidate = register(client).json()["candidate_id"]
    doc_id = upload(client, root, candidate).json()["document_id"]
    monkeypatch.setattr(service.Processor, "_run", lambda *args: None)
    assert client.post(API + f"/documents/{doc_id}/process", headers=HEADERS).status_code == 202
    assert client.post(API + f"/documents/{doc_id}/process", headers=HEADERS).status_code == 409
    with database(db) as conn:
        assert status(conn, doc_id)["state"] == "QUEUED"
        meta = control(conn, doc_id)
        meta["started_at"] = time.time() - 1000
        save_control(conn, doc_id, meta)
    state = client.get(API + f"/documents/{doc_id}").json()
    assert state["state"] == "FAILED" and state["error"] == "INTERRUPTED"


def test_stale_review_unapproved_export_and_path_escape(workspace, monkeypatch):
    client, root, _, _ = workspace
    candidate = register(client).json()["candidate_id"]
    doc_id = upload(client, root, candidate).json()["document_id"]
    assert client.post(API + f"/documents/{doc_id}/exports", headers=HEADERS).status_code == 409
    parse_id = str(uuid4())
    monkeypatch.setattr(
        service.Processor, "review", lambda *args: {"parse_id": parse_id, "sha256": "a" * 64}
    )
    assert (
        client.post(
            API + f"/documents/{doc_id}/review",
            headers=HEADERS,
            json={
                "parse_id": parse_id,
                "sha256": "b" * 64,
                "approved": True,
                "facts_reviewed": True,
            },
        ).status_code
        == 409
    )
    with pytest.raises(ProcessingError):
        private_path(root, "../../outside.pdf")


def test_no_implicit_database_creation(workspace):
    _, root, _, _ = workspace
    missing = root / "another.sqlite3"
    with pytest.raises(ProcessingError), database(missing):
        pass
    assert not missing.exists()


def test_existing_email_stages_stay_unchanged(workspace):
    client, _, _, _ = workspace
    assert client.get("/email").status_code == 200
    from jobmitra.modules.email_studio.router import SUBMISSION_FILE, UPDATES_FILE

    assert client.get("/email/updates").content == UPDATES_FILE.read_bytes()
    assert client.get("/email/submission").content == SUBMISSION_FILE.read_bytes()


def test_processor_offline_composition():
    if not PYTHON.is_file() or not REPO.is_dir():
        pytest.skip("Configure processor test paths")
    script = Path(__file__).with_name("resume_processing_worker_checks.py")
    result = subprocess.run(
        [str(PYTHON), str(script), str(REPO)], capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_candidate_input_rejects_unrelated_recruitment_fields():
    with pytest.raises(ValueError):
        CandidateInput(full_name="Synthetic Candidate", consent=True, expected_salary=100)


def test_http_worker_review_and_download_flow(workspace, monkeypatch):
    """HTTP -> separate Python -> mocked model boundaries -> real ATS renderers -> download."""
    client, root, db, _ = workspace
    bridge_dir = Path(service.__file__).parent
    worker = root / "offline_worker.py"
    worker.write_text("""
import sys,json
from pathlib import Path
from unittest.mock import Mock,patch
root,db,repo,bridge_dir,action,target=sys.argv[1:]
sys.path[:0]=[bridge_dir,repo]
from app.core import config
from app.schemas.resume import ResumeProfile
from app.services import extraction,pii_pipeline,llm_parser
import bridge
config.ROOT=Path(root);config.PRIVATE=Path(root)/'private';config.DATABASE=Path(db)
config.BLOCK_OUT_OF_SCOPE_PII=True
config.GROQ_API_KEY='synthetic-offline-key'
profile=ResumeProfile(current_job_title='Engineer',skills=['Python'],
 work_experience=[{'company':'Example Employer','role':'Engineer','end_date':'Present'}])
clean='[NAME_1] engineer at Example Employer. Python.'
masked={'status':'MASKED','identity':{'name':'Synthetic Candidate'},'sanitized_text':clean}
chain=Mock();chain.invoke.return_value=profile.model_dump()
with (
 patch.object(extraction,'make_converter'),
 patch.object(extraction,'extract_markdown',return_value=(
  'Synthetic Candidate engineer at Example Employer. Python.','OK')),
 patch.object(pii_pipeline,'load_gliner'),
 patch.object(pii_pipeline,'sanitize_resume',return_value=masked),
 patch.object(llm_parser,'make_chain',return_value=chain),
 patch('httpx.Client.send',side_effect=AssertionError('No live requests'))
):
 if action=='process':bridge.run_job(Path(root),Path(db),action,target);result={'done':True}
 elif action=='export':bridge.run_job(Path(root),Path(db),action,target);result={'done':True}
 elif action=='review':result=bridge.review_data(Path(root),Path(db),target)
print(json.dumps(result))
""")
    original_bridge = service.Processor.bridge

    def offline_bridge(self, action, target, *, kind=None, timeout=30):
        if action == "validate":
            return original_bridge(self, action, target, kind=kind, timeout=timeout)
        result = subprocess.run(
            [
                str(PYTHON),
                str(worker),
                str(root),
                str(db),
                str(REPO),
                str(bridge_dir),
                action,
                target,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=True,
        )
        import json

        return json.loads(result.stdout)

    monkeypatch.setattr(service.Processor, "bridge", offline_bridge)
    candidate = register(client).json()["candidate_id"]
    doc_id = upload(client, root, candidate).json()["document_id"]
    path = API + f"/documents/{doc_id}"

    def wait_for(expected):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            data = client.get(path).json()
            if data["state"] == expected:
                return data
            if data["state"] in {"FAILED", "DEFERRED"}:
                pytest.fail(str(data))
            time.sleep(0.1)
        pytest.fail("Worker did not finish: " + str(data))

    assert client.post(path + "/process", headers=HEADERS).status_code == 202
    wait_for("REVIEW_REQUIRED")
    reviewed = client.get(path + "/review").json()
    assert reviewed["presentation"]["candidate_name"] == "Synthetic Candidate"
    assert reviewed["presentation"]["projects"] == []
    assert client.post(path + "/exports", headers=HEADERS).status_code == 409
    values = {
        "parse_id": reviewed["parse_id"],
        "sha256": reviewed["sha256"],
        "approved": True,
        "facts_reviewed": True,
    }
    assert client.post(path + "/review", json=values, headers=HEADERS).status_code == 200
    assert client.post(path + "/exports", headers=HEADERS).status_code == 202
    finished = wait_for("COMPLETED")
    assert set(finished["exports"]) == {"preview", "branded_pdf", "plain_pdf", "docx"}
    for kind in finished["exports"]:
        result = client.get(path + "/downloads/" + kind)
        assert result.status_code == 200, result.text[:120]
        assert result.headers["cache-control"] == "no-store"
        assert len(result.content) > 100
    # Revocation immediately disables every generated download.
    values["approved"] = False
    assert client.post(path + "/review", json=values, headers=HEADERS).status_code == 200
    assert client.get(path + "/downloads/docx").status_code == 409


def test_ready_state_privacy_warnings_visible_in_status_and_page(workspace):
    import json

    client, root, db, _ = workspace
    candidate = register(client).json()["candidate_id"]
    doc_id = upload(client, root, candidate).json()["document_id"]
    warnings = [
        "candidate_name_mismatch",
        "personal_detail_outside_masking_scope",
        "address_outside_masking_scope",
    ]
    with database(db) as conn:
        conn.execute(
            "UPDATE resumes SET processing_status='READY_FOR_LLM',warnings_json=? "
            "WHERE document_id=?",
            (json.dumps(warnings), doc_id),
        )
        meta = control(conn, doc_id)
        meta.update(state="READY_FOR_LLM", stage=3, error=None)
        save_control(conn, doc_id, meta)
    result = client.get(API + f"/documents/{doc_id}").json()
    assert result["state"] == "READY_FOR_LLM"
    assert result["warnings"] == warnings
    assert result["blocking_reasons"] == []
    assert "not fully anonymized" in client.get("/resume-processing").text
    js = client.get("/static/stage2/resume-processing.mjs").text
    assert "Warnings — processing is allowed" in js
    assert "candidate_name_mismatch" in js
