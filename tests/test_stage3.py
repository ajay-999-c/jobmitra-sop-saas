"""Candidate Desk only: synthetic records, isolated PostgreSQL and temporary files."""

import hashlib
import io
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_stage2 import database as database  # reusable guarded database fixture

from jobmitra.core.database import Base, get_session
from jobmitra.core.workflow import WorkflowError
from jobmitra.main import create_app
from jobmitra.modules.candidates.constants import STATES, UNION_TERRITORIES
from jobmitra.modules.candidates.models import STAGE3_TABLES, CandidateVisit
from jobmitra.modules.candidates.storage import LocalDocumentStorage

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE3_DISPOSABLE") != "1",
    reason="Use scripts/test_stage3_isolated.py; never a real database",
)
PDF = b"%PDF-1.4\n1 0 obj <</Type /Catalog>> endobj\n%%EOF\n"


def docx():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-type'
                's"><Override PartName="/word/document.xml" ContentType="application/vnd.o'
                'penxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types'
                ">"
            ),
        )
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2'
                '006/main"><w:body/></w:document>'
            ),
        )
    return stream.getvalue()


@pytest.fixture
def desk(database, tmp_path):
    engine, settings, *_ = database
    assert settings.db_host.startswith("/private/tmp/jobmitra-stage2-")
    root = tmp_path / "private-documents"
    root.mkdir(mode=0o700)
    config = settings.model_copy(update={"document_storage_root": root, "document_max_bytes": 4096})
    with engine.connect() as connection:
        outer = connection.begin()
        app = create_app(config)

        def sessions():
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = sessions
        try:
            with TestClient(app) as client:
                client.headers["X-Jobmitra-UI"] = "1"
                yield client, connection, root
        finally:
            outer.rollback()


def create(client, **values):
    response = client.post(
        "/api/candidates",
        json={
            "full_name": "Synthetic Candidate",
            "mobile": "001234567890",
            "source": "Foundit",
            **values,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def employee(client):
    response = client.post("/api/staff", json={"display_name": "Synthetic Employee"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client, candidate, filename="resume.pdf", content=PDF, **params):
    return client.post(
        f"/api/candidates/{candidate['id']}/documents",
        params={"kind": "ORIGINAL_RESUME", **params},
        headers={"X-Document-Filename": filename, "Content-Type": "application/octet-stream"},
        content=content,
    )


def snapshot(connection, tables):
    return {
        name: connection.execute(
            text(f"SELECT to_jsonb(t) FROM {name} t ORDER BY to_jsonb(t)::text")
        )
        .scalars()
        .all()
        for name in tables
    }


def test_registration_edit_email_salary_nulls_and_retained_identity(desk):
    client, _, _ = desk
    candidate = create(
        client,
        email="test@example.test",
        hometown="Synthetic Town",
        home_state="Madhya Pradesh",
        ready_to_relocate=False,
        experience_months=25,
        skills=["SQL", "sql"],
        current_salary_amount="20000.25",
        current_salary_period="Monthly",
        expected_salary_amount="360000.50",
        expected_salary_period="Annual",
    )
    assert candidate["mobile"] == "001234567890"
    assert (
        candidate["current_salary_amount"] == "20000.25"
        and candidate["expected_salary_amount"] == "360000.50"
    )
    assert candidate["current_salary_basis"] == "Unknown" and candidate["skills"] == ["SQL"]
    url = "/api/candidates/" + candidate["id"]
    response = client.patch(
        url, json={"version": candidate["version"], "email": None, "ready_to_relocate": None}
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert (
        changed["id"] == candidate["id"]
        and changed["email"] is None
        and changed["ready_to_relocate"] is None
    )
    assert changed["current_salary_amount"] == candidate["current_salary_amount"]
    assert changed["hometown"] == "Synthetic Town" and changed["home_state"] == "Madhya Pradesh"
    assert changed["updated_at"] and changed["version"] == 2
    assert client.patch(url, json={"version": 1, "full_name": "Stale"}).status_code == 409
    assert client.patch(url, json={"version": 2, "full_name": None}).status_code == 422
    assert client.get("/api/candidates?q=001234").json()[0]["id"] == candidate["id"]
    assert (
        len(STATES) == 28
        and len(UNION_TERRITORIES) == 8
        and len(set(STATES + UNION_TERRITORIES)) == 36
    )
    assert client.get("/api/office-visits").json() == []
    assert client.get("/api/job-search-requests").json() == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("full_name", " "),
        ("mobile", ""),
        ("mobile", "123"),
        ("email", "bad@"),
        ("source", "Unknown"),
        ("ready_to_relocate", "Yes"),
        ("home_state", "Invented"),
        ("experience_months", -1),
        ("current_salary_amount", "NaN"),
        ("expected_salary_amount", -1),
        ("skills", None),
    ],
)
def test_registration_rejects_invalid_values(desk, field, value):
    client, _, _ = desk
    r = client.post(
        "/api/candidates",
        json={
            "full_name": "Synthetic",
            "mobile": "001234567890",
            "source": "Foundit",
            field: value,
        },
    )
    assert r.status_code == 422
    assert client.get("/api/candidates").json() == []


def test_duplicate_warning_explicit_second_person_and_repeat_visits(desk):
    client, _, _ = desk
    actor = employee(client)
    candidate = create(client, source="Walk-in", recorded_by_staff_id=actor)
    visits = client.get("/api/office-visits").json()
    assert len(visits) == 1 and visits[0]["candidate_id"] == candidate["id"]
    duplicate = client.post(
        "/api/candidates",
        json={"full_name": "Other person", "mobile": "00 1234 567890", "source": "Foundit"},
    )
    assert duplicate.status_code == 409
    assert (
        len(client.get("/api/candidates/duplicates", params={"mobile": "00 1234 567890"}).json())
        == 1
    )
    second = create(client, full_name="Separate Person", confirm_duplicate=True)
    assert second["id"] != candidate["id"]
    for _ in range(2):
        response = client.post(
            f"/api/candidates/{candidate['id']}/visits",
            json={
                "visited_at": datetime.now(UTC).isoformat(),
                "purpose": "Follow up",
                "recorded_by_staff_id": actor,
                "authority_status": "Signed (reported)",
            },
        )
        assert response.status_code == 201, response.text
    visits = client.get("/api/office-visits").json()
    assert len({v["id"] for v in visits}) == 3
    assert len(client.get("/api/candidates").json()) == 2
    assert client.patch("/api/staff/" + actor, json={"is_active": False}).status_code == 200
    assert all(v["recorded_by_staff_id"] == actor for v in client.get("/api/office-visits").json())
    assert (
        client.post(
            f"/api/candidates/{candidate['id']}/visits",
            json={
                "visited_at": datetime.now(UTC).isoformat(),
                "purpose": "Follow up",
                "recorded_by_staff_id": actor,
            },
        ).status_code
        == 422
    )


def test_walkin_atomic_failure(desk):
    client, _, _ = desk

    def fail(session, *args):
        if any(isinstance(row, CandidateVisit) for row in session.new):
            raise WorkflowError("Simulated visit failure", 503)

    event.listen(Session, "before_flush", fail)
    try:
        r = client.post(
            "/api/candidates",
            json={"full_name": "Synthetic", "mobile": "001234567890", "source": "Walk-in"},
        )
        assert r.status_code == 503
    finally:
        event.remove(Session, "before_flush", fail)
    assert (
        client.get("/api/candidates").json() == [] and client.get("/api/office-visits").json() == []
    )


def test_catalog_pairing_uniqueness_keys_deactivation_and_free_role(desk):
    client, connection, _ = desk
    d = client.post("/api/domains", json={"name": "Office Work"}).json()
    assert client.post("/api/domains", json={"name": " office   WORK "}).status_code == 409
    s = client.post("/api/subdomains", json={"domain_id": d["id"], "name": "Scheduling"}).json()
    other = client.post("/api/domains", json={"name": "Other work"}).json()
    assert (
        client.post(
            "/api/candidates",
            json={
                "full_name": "Synthetic",
                "mobile": "001234567890",
                "source": "Foundit",
                "domain_id": other["id"],
                "subdomain_id": s["id"],
            },
        ).status_code
        == 422
    )
    c = create(client, domain_id=d["id"], subdomain_id=s["id"], role_title="Novel free text role")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            text("UPDATE candidates SET domain_id=:other WHERE id=:id"),
            {"other": other["id"], "id": c["id"]},
        )
    renamed = client.patch(
        "/api/domains/" + d["id"], json={"name": "Office Operations", "is_active": False}
    ).json()
    assert renamed["key"] == d["key"]
    assert client.get("/api/candidates/" + c["id"]).json()["domain_id"] == d["id"]
    assert (
        client.patch(
            "/api/candidates/" + c["id"], json={"version": 1, "role_title": "Updated role"}
        ).status_code
        == 200
    )
    assert client.get("/api/domains").json()["subdomains"] == []


def test_job_search_independent_followups_and_atomic_optional_create(desk):
    client, connection, _ = desk
    actor = employee(client)
    before = snapshot(connection, ["job_requirements", "tasks", "activities"])
    c = create(
        client,
        initial_job_search={
            "desired_role": "Office role",
            "assigned_staff_id": actor,
            "follow_up_date": "2000-01-01",
        },
    )
    requests = client.get("/api/job-search-requests?due_only=true").json()
    assert len(requests) == 1 and requests[0]["is_overdue"]
    r = requests[0]
    assert r["candidate_id"] == c["id"] and r["status"] == "Searching"
    done = client.patch(
        "/api/job-search-requests/" + r["id"],
        json={"version": r["version"], "status": "Placed", "follow_up_date": None},
    )
    assert done.status_code == 200, done.text
    assert done.json()["closed_at"] and not done.json()["is_overdue"]
    assert snapshot(connection, ["job_requirements", "tasks", "activities"]) == before
    fail = client.post(
        "/api/candidates",
        json={
            "full_name": "Invalid search owner",
            "mobile": "009876543210",
            "source": "Walk-in",
            "initial_job_search": {"desired_role": "Role", "assigned_staff_id": str(uuid4())},
        },
    )
    assert fail.status_code == 422
    assert (
        len(client.get("/api/candidates").json()) == 1
        and client.get("/api/office-visits").json() == []
    )


@pytest.mark.parametrize("filename,content", [("resume.pdf", PDF), ("resume.docx", docx())])
def test_upload_versions_download_integrity_and_latest_rule(desk, filename, content):
    client, connection, root = desk
    c = create(client)
    documents = []
    for version in (1, 2):
        response = upload(client, c, filename, content)
        assert response.status_code == 201, response.text
        doc = response.json()
        documents.append(doc)
        assert doc["version"] == version and doc["sha256"] == hashlib.sha256(content).hexdigest()
        assert doc["size_bytes"] == len(content) and "storage_key" not in doc
        downloaded = client.get(f"/candidates/{c['id']}/documents/{doc['id']}/download")
        assert downloaded.content == content and downloaded.headers[
            "content-disposition"
        ].startswith("attachment;")
        assert downloaded.headers["cache-control"] == "no-store"
    assert documents[0]["id"] != documents[1]["id"] and len(list(root.iterdir())) == 2
    assert client.get(f"/api/candidates/{c['id']}/documents").json()[0]["version"] == 2
    stored = connection.execute(
        text("SELECT storage_key FROM candidate_documents WHERE id=:id"), {"id": documents[0]["id"]}
    ).scalar()
    assert re.fullmatch(r"[0-9a-f]{32}\.(pdf|docx)", stored)
    assert (root / stored).stat().st_mode & 0o777 == 0o600
    (root / stored).unlink()
    assert (
        client.get(f"/candidates/{c['id']}/documents/{documents[0]['id']}/download").status_code
        == 404
    )
    assert len(client.get(f"/api/candidates/{c['id']}/documents").json()) == 2


@pytest.mark.parametrize(
    "filename,content,status",
    [
        ("../escape.pdf", PDF, 422),
        ("C:\\file.pdf", PDF, 422),
        ("resume.exe", PDF, 422),
        ("resume.pdf", b"not pdf", 422),
        ("resume.docx", PDF, 422),
        ("resume.pdf", b"", 422),
        ("resume.pdf", b"x" * 4097, 413),
    ],
)
def test_unsafe_invalid_and_oversize_uploads_leave_no_metadata(desk, filename, content, status):
    client, _, root = desk
    c = create(client)
    assert upload(client, c, filename, content).status_code == status
    assert client.get(f"/api/candidates/{c['id']}/documents").json() == []
    assert not root.exists() or list(root.iterdir()) == []


def test_upload_transaction_failure_cleans_file(desk):
    client, connection, root = desk
    c = create(client)

    def fail(session):
        raise WorkflowError("Simulated commit failure", 503)

    event.listen(Session, "before_commit", fail)
    try:
        assert upload(client, c).status_code == 503
    finally:
        event.remove(Session, "before_commit", fail)
    assert list(root.iterdir()) == []
    assert connection.scalar(text("SELECT count(*) FROM candidate_documents")) == 0


def test_modified_lineage_authority_and_cross_candidate_download(desk):
    client, _, _ = desk
    c = create(client)
    other = create(client, mobile="009876543210")
    original = upload(client, c).json()
    assert upload(client, c, kind="MODIFIED_RESUME").status_code == 422
    assert (
        upload(
            client, other, kind="MODIFIED_RESUME", source_document_id=original["id"], reviewed=True
        ).status_code
        == 422
    )
    modified = upload(
        client, c, kind="MODIFIED_RESUME", source_document_id=original["id"], reviewed=True
    )
    assert modified.status_code == 201, modified.text
    assert (
        modified.json()["source_document_id"] == original["id"]
        and modified.json()["approval_status"] == "Reviewed"
    )
    authority = upload(client, c, kind="AUTHORITY")
    assert authority.status_code == 201 and authority.json()["kind"] == "AUTHORITY"
    assert authority.json()["approval_status"] == "Unverified"
    assert (
        client.get(f"/candidates/{other['id']}/documents/{original['id']}/download").status_code
        == 404
    )
    assert (
        client.get(f"/candidates/{c['id']}/documents/{modified.json()['id']}/download").content
        == PDF
    )


def test_json_history_exact_version_review_and_no_profile_promotion(desk):
    client, connection, _ = desk
    c = create(client, skills=["Confirmed skill"])
    actor = employee(client)
    original = upload(client, c).json()
    parse_url = f"/api/candidates/{c['id']}/resume-parses"
    payload = {"name": "AI suggestion", "skills": ["Unconfirmed"]}
    results = []
    for provider in ("ChatGPT", "Claude"):
        r = client.post(
            parse_url,
            json={
                "document_id": original["id"],
                "provider": provider,
                "parsed_json": payload,
                "pasted_by_staff_id": actor,
            },
        )
        assert r.status_code == 201, r.text
        results.append(r.json())
        assert (
            r.json()["validation_status"] == "Structurally checked"
            and r.json()["review_status"] == "Unreviewed"
        )
    upload(client, c)
    assert all(p["document_id"] == original["id"] for p in client.get(parse_url).json())
    reviewed = client.patch(
        parse_url + "/" + results[0]["id"],
        json={"reviewed_by_staff_id": actor, "review_status": "Reviewed"},
    )
    assert (
        reviewed.status_code == 200
        and reviewed.json()["validation_status"] == "Structurally checked"
    )
    assert (
        client.patch(
            parse_url + "/" + results[0]["id"],
            json={"reviewed_by_staff_id": actor, "review_status": "Rejected"},
        ).status_code
        == 409
    )
    assert client.get("/api/candidates/" + c["id"]).json() == c
    for bad in ([], "text", 5):
        assert (
            client.post(
                parse_url,
                json={"document_id": original["id"], "provider": "Claude", "parsed_json": bad},
            ).status_code
            == 422
        )
    assert (
        client.post(
            parse_url, content="{bad", headers={"Content-Type": "application/json"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            parse_url,
            json={
                "document_id": original["id"],
                "provider": "Claude",
                "parsed_json": {"x": "x" * 270000},
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            parse_url, content="x" * 310000, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    modified = upload(
        client, c, kind="MODIFIED_RESUME", source_document_id=original["id"], reviewed=True
    ).json()
    assert (
        client.post(
            parse_url, json={"document_id": modified["id"], "provider": "Claude", "parsed_json": {}}
        ).status_code
        == 422
    )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            text("UPDATE resume_parse_results SET document_id=:doc WHERE id=:id"),
            {"doc": modified["id"], "id": results[0]["id"]},
        )


def test_storage_requires_explicit_private_root_and_safe_key(tmp_path):
    with pytest.raises(WorkflowError):
        LocalDocumentStorage(None, 4096)
    with pytest.raises(WorkflowError):
        LocalDocumentStorage("relative", 4096)
    with pytest.raises(WorkflowError):
        LocalDocumentStorage(tmp_path / "static", 4096)
    with pytest.raises(WorkflowError):
        LocalDocumentStorage(tmp_path / "unmounted-or-missing", 4096)
    (tmp_path / "private").mkdir(mode=0o700)
    store = LocalDocumentStorage(tmp_path / "private", 4096)
    with pytest.raises(WorkflowError):
        store.path("../secret")


def test_ui_pages_forms_email_states_and_local_assets(desk):
    client, _, _ = desk
    c = create(client)
    for url in (
        "/candidate-desk",
        "/candidates",
        "/candidates/new",
        "/office-visits",
        "/job-search-requests",
        "/domains",
        "/candidates/" + c["id"],
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
        assert response.headers["cache-control"] == "no-store"
    page = client.get("/candidates/new").text
    for marker in (
        'name="email"',
        'name="qualification"',
        'name="skills"',
        'name="preferred_locations"',
        "States (28)",
        "Union Territories (8)",
        "data-close-dialog",
        "Save Candidate",
        "dialog-body",
    ):
        assert marker in page
    fragment = client.get("/candidates?q=Synthetic", headers={"HX-Request": "true"})
    assert fragment.status_code == 200 and "<html" not in fragment.text
    assert client.get("/job-search-requests?staff_id=").status_code == 200
    assert client.get("/office-visits?day=").status_code == 200
    for name in ("desk.css", "desk.mjs"):
        assert client.get("/static/candidates/" + name).status_code == 200
    assert client.get("/companies").status_code == 200
    assert client.get("/requirements").status_code == 200
    assert (
        client.post(
            "/api/candidates",
            json={"full_name": "External", "mobile": "009876543210", "source": "Foundit"},
            headers={"Origin": "https://outside.invalid"},
        ).status_code
        == 403
    )


def test_stage3_migration_additive_preserves_existing_data(database):
    engine, *_ = database
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, "0003_jd_work_focus")
            names = set(inspect(connection).get_table_names()) - {"alembic_version"}
            actor, jd = uuid4(), uuid4()
            company = connection.scalar(text("SELECT id FROM companies LIMIT 1"))
            connection.execute(
                text(
                    "INSERT INTO staff_members (id,display_name) VALUES (:id,'Syntheti"
                    "c migration staff')"
                ),
                {"id": actor},
            )
            connection.execute(
                text(
                    "INSERT INTO job_requirements (id,company_id,created_by_staff_id,j"
                    "ob_title,current_work_focus) VALUES (:id,:company,:actor,'Synthet"
                    "ic existing JD','CANDIDATE_CONTACT')"
                ),
                {"id": jd, "company": company, "actor": actor},
            )
            before = snapshot(connection, names)
            columns = {
                name: [
                    (col["name"], str(col["type"]), col["nullable"])
                    for col in inspect(connection).get_columns(name)
                ]
                for name in names
            }
            command.upgrade(cfg, "0004_candidate_desk")
            assert set(inspect(connection).get_table_names()) == names | STAGE3_TABLES | {
                "alembic_version"
            }
            assert snapshot(connection, names) == before
            assert {
                name: [
                    (col["name"], str(col["type"]), col["nullable"])
                    for col in inspect(connection).get_columns(name)
                ]
                for name in names
            } == columns
            assert (
                compare_metadata(
                    MigrationContext.configure(
                        connection, opts={"compare_type": True, "compare_server_default": True}
                    ),
                    Base.metadata,
                )
                == []
            )
            command.downgrade(cfg, "0003_jd_work_focus")
            assert snapshot(connection, names) == before
            command.upgrade(cfg, "head")
        finally:
            outer.rollback()
    sql = Path("outputs/stage-3/0004_candidate_desk.sql").read_text()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == STAGE3_TABLES
    assert not re.search(
        r"^\s*(DROP|TRUNCATE|DELETE FROM|ALTER TABLE|INSERT INTO|CREATE EXTENSION|CREATE ROLE)\b",
        sql,
        re.I | re.M,
    )
    assert set(re.findall(r"UPDATE (\w+)", sql)) == {"alembic_version"}
