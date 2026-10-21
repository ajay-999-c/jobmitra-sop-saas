"""Safety checks for the DEMO journal. No database or network connections."""

import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "demo_acceptance", Path(__file__).resolve().parents[1] / "scripts/demo_acceptance.py"
)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_successful_write_is_not_repeated(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "STATE", tmp_path / "manifest.json")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"id": "demo-id"})

    state = {"actions": {}}
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        runner = demo.Acceptance(None, state, {}, client)
        first = runner.write("company", "POST", "/api/companies", json={"company_name": "DEMO"})
        assert runner.write("company", "POST", "/api/companies") == first
    assert len(calls) == 1
    assert state["pending"] is None


def test_uncertain_write_remains_pending_and_cannot_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "STATE", tmp_path / "manifest.json")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("Server might already have committed")

    state = {"actions": {}}
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        runner = demo.Acceptance(None, state, {}, client)
        with pytest.raises(httpx.ReadTimeout):
            runner.write("company", "POST", "/api/companies")
        with pytest.raises(RuntimeError, match="Uncertain earlier write"):
            runner.write("company", "POST", "/api/companies")
    assert len(calls) == 1
    assert state["pending"]["key"] == "company"


def test_historical_edit_or_deletion_blocks_verification():
    original = {"id": "historical", "company_name": "Original"}
    backup = {"baseline": {"companies": {"rows": {"historical": demo.fingerprint(original)}}}}
    demo.preserve_baseline({"companies": [original]}, backup)
    for changed in ([], [{**original, "company_name": "Changed"}]):
        with pytest.raises(RuntimeError, match="Historical row changed or missing"):
            demo.preserve_baseline({"companies": changed}, backup)


def test_cleanup_preview_blocks_external_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "STATE", tmp_path / "manifest.json")
    rows = {table: [] for table in demo.TABLES}
    rows["job_requirements"] = [{"id": "non-demo-job", "company_id": "demo-company"}]
    owned = {table: [] for table in demo.TABLES}
    owned["companies"] = ["demo-company"]
    runner = demo.Acceptance(None, {}, {}, None)
    preview = runner.cleanup_preview(rows, {"owned": owned, "files": []})
    assert preview["blockers"] == [{"table": "job_requirements", "id": "non-demo-job"}]
    assert preview["mode"] == "preview_only_no_deletion_implemented"


def test_recruiter_composite_identity_and_generated_documents_are_stable():
    assert demo.row_id({"job_id": "job", "staff_id": "staff"}) == "job|staff"
    assert demo.sample_docx() == demo.sample_docx()
    assert demo.sample_pdf("DEMO").startswith(b"%PDF-1.4")
