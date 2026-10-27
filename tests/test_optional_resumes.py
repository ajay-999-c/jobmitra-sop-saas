"""Optional resume endpoints on a disposable Unix-socket PostgreSQL and temporary files."""

import hashlib
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from test_candidate_quick_entry import client as client
from test_candidate_quick_entry import save
from test_stage3 import PDF, docx

from jobmitra.modules.candidates.models import CandidateResume
from jobmitra.modules.candidates.storage import LocalDocumentStorage

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1",
    reason="Disposable runner required",
)


@pytest.fixture
def desk(client):
    return client


def upload(api, candidate_id, content=PDF, filename="synthetic.pdf"):
    return api.post(
        f"/api/candidates/{candidate_id}/resumes",
        content=content,
        headers={"X-Document-Filename": filename},
    )


@pytest.mark.parametrize("filename,content", [("original.pdf", PDF), ("original.docx", docx())])
def test_optional_creation_versions_and_ownership(desk, filename, content):
    api, engine = desk
    candidate = save(api, skills=["Historical"], qualification="Retained")
    before = api.get(f"/api/candidates/{candidate['id']}").json()
    assert api.get(f"/candidates/{candidate['id']}").status_code == 200
    history_url = f"/api/candidates/{candidate['id']}/resumes"
    assert api.get(history_url).json() == []
    result = upload(api, candidate["id"], content, filename)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["parsed_json"] is None and row["parsing_error"] is None
    assert row["parsing_status"] == "not_parsed" and row["is_active"]
    assert row["file_hash"] == hashlib.sha256(content).hexdigest()
    assert "storage_key" not in row and "storage_path" not in row
    path = history_url + "/" + row["id"]
    for suffix in ("download", "preview"):
        response = api.get(path + "/" + suffix)
        assert response.content == content
        assert response.headers["cache-control"] == "no-store"
        expected = "inline" if suffix == "preview" and filename.endswith(".pdf") else "attachment"
        assert response.headers["content-disposition"].startswith(expected)
        assert response.status_code == 200
        assert "www-authenticate" not in response.headers
    other = save(api, mobile="000123456788")
    assert api.get(f"/api/candidates/{other['id']}/resumes/{row['id']}/download").status_code == 404
    assert upload(api, candidate["id"]).status_code == 201
    rows = api.get(history_url).json()
    assert len(rows) == 2 and sum(r["is_active"] for r in rows) == 1
    assert api.get(path + "/download").content == content
    assert api.get(f"/api/candidates/{candidate['id']}").json() == before
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT extracted_text FROM candidate_resumes LIMIT 1")) is None
        assert conn.scalar(text("SELECT count(*) FROM candidate_documents")) == 0


@pytest.mark.parametrize(
    "filename,content,status",
    [
        ("bad.exe", PDF, 422),
        ("bad.pdf", b"not pdf", 422),
        ("bad.docx", PDF, 422),
        ("../bad.pdf", PDF, 422),
        ("empty.pdf", b"", 422),
        ("large.pdf", PDF + b"x" * 2000, 413),
    ],
)
def test_rejection_no_orphans(desk, filename, content, status):
    api, engine = desk
    candidate = save(api)
    api.app.state.settings.resume_max_bytes = 1024
    assert upload(api, candidate["id"], content, filename).status_code == status
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidate_resumes")) == 0
    assert list(api.app.state.settings.document_storage_root.iterdir()) == []


def test_no_authentication_or_login_and_default_limit(desk):
    api, engine = desk
    assert "authorization" not in api.headers
    assert api.app.state.settings.resume_max_bytes == 10 * 1024 * 1024
    assert "resume_access_username" not in type(api.app.state.settings).model_fields
    assert "resume_access_password" not in type(api.app.state.settings).model_fields
    candidate = save(api)
    assert upload(api, candidate["id"]).status_code == 201
    assert api.get("/api/resume-access").status_code == 404
    for url in ("/candidates/new", f"/candidates/{candidate['id']}"):
        response = api.get(url)
        assert response.status_code == 200
        assert "resume-access-dialog" not in response.text
        assert "Unlock resumes" not in response.text
    # The request-origin guard remains independent of authentication.
    response = api.post(
        f"/api/candidates/{candidate['id']}/resumes",
        content=PDF,
        headers={"X-Document-Filename": "test.pdf", "Origin": "https://other.invalid"},
    )
    assert response.status_code == 403
    assert save(api, mobile="000123456788")["id"]


def test_storage_and_database_failure_preserve_active(desk, monkeypatch):
    api, engine = desk
    candidate = save(api)
    original = upload(api, candidate["id"]).json()
    files = sorted(api.app.state.settings.document_storage_root.iterdir())

    def unavailable(*args):
        raise OSError("synthetic storage failure")

    with monkeypatch.context() as patch:
        patch.setattr(LocalDocumentStorage, "save", unavailable)
        assert upload(api, candidate["id"]).status_code == 503

    def reject(*args):
        raise SQLAlchemyError("synthetic database failure")

    event.listen(CandidateResume, "before_insert", reject)
    try:
        assert upload(api, candidate["id"]).status_code == 503
    finally:
        event.remove(CandidateResume, "before_insert", reject)
    assert sorted(api.app.state.settings.document_storage_root.iterdir()) == files
    rows = api.get(f"/api/candidates/{candidate['id']}/resumes").json()
    assert len(rows) == 1 and rows[0]["id"] == original["id"] and rows[0]["is_active"]


def test_parallel_versions_have_one_active(desk):
    api, engine = desk
    candidate = save(api)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: upload(api, candidate["id"]), range(2)))
    assert [r.status_code for r in results] == [201, 201]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidate_resumes")) == 2
        assert conn.scalar(text("SELECT count(*) FROM candidate_resumes WHERE is_active")) == 1


def test_additive_migration_and_sql(desk):
    api, engine = desk
    candidate = save(api, skills=["Preserve"])
    before = api.get(f"/api/candidates/{candidate['id']}").json()
    spec = importlib.util.spec_from_file_location(
        "resume_migration", "migrations/versions/0007_candidate_resumes.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        # Only on the fixture's disposable cluster, with no resume rows.
        CandidateResume.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert "candidate_resumes" in inspect(connection).get_table_names()
    assert api.get(f"/api/candidates/{candidate['id']}").json() == before
    assert upload(api, candidate["id"]).status_code == 201
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "0006_jd_catalog_links:0007_candidate_resumes", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE candidate_resumes" in sql
    assert "CREATE UNIQUE INDEX uq_candidate_resume_active" in sql
    for forbidden in (
        "DROP ",
        "DELETE FROM ",
        "TRUNCATE ",
        "ALTER TABLE candidates",
        "ALTER TABLE job_requirements",
    ):
        assert forbidden not in sql


def test_future_parsed_data_is_separate_and_errors_are_private(desk):
    api, engine = desk
    candidate = save(api)
    before = api.get(f"/api/candidates/{candidate['id']}").json()
    row = upload(api, candidate["id"]).json()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE candidate_resumes SET parsing_status='parsed', "
                "parsed_json=CAST(:data AS jsonb) WHERE id=:id"
            ),
            {"id": row["id"], "data": '{"skills": ["Synthetic"]}'},
        )
    history = api.get(f"/api/candidates/{candidate['id']}/resumes").json()
    assert history[0]["parsed_json"] == {"skills": ["Synthetic"]}
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE candidate_resumes SET parsing_status='failed', "
                "parsing_error='/private/synthetic/path' WHERE id=:id"
            ),
            {"id": row["id"]},
        )
    response = api.get(f"/api/candidates/{candidate['id']}/resumes")
    assert "/private/" not in response.text
    assert response.json()[0]["parsing_status"] == "failed"
    assert api.get(f"/api/candidates/{candidate['id']}").json() == before
