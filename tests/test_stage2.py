"""Stage 2 only. DB tests refuse every target except the private disposable cluster."""

import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobmitra.core.database import Base, get_session
from jobmitra.core.workflow import WorkflowError, office_today
from jobmitra.main import create_app
from jobmitra.modules.candidates.models import CANDIDATE_RESUME_TABLES, STAGE3_TABLES
from jobmitra.modules.companies.models import Company, CompanyContact
from jobmitra.modules.jobs.models import JobRecruiter
from jobmitra.modules.jobs.service import target_state
from jobmitra.modules.stage2 import STAGE2_TABLES
from jobmitra.modules.worklog.service import ActivityService

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_STAGE2_DISPOSABLE") != "1",
    reason="Use scripts/test_stage2_isolated.py; never use a real DB",
)


def company_snapshot(connection):
    return {
        model.__tablename__: list(connection.execute(select(model.__table__).order_by(model.id)))
        for model in (Company, CompanyContact)
    }


@pytest.fixture(scope="module")
def database(workflow_database):
    return workflow_database


@pytest.fixture
def ui(database):
    engine, settings, companies, contacts, _, _ = database
    with engine.connect() as connection:
        outer = connection.begin()
        app = create_app(settings)

        def sessions():
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        app.dependency_overrides[get_session] = sessions
        try:
            with TestClient(app) as client:
                client.headers["X-Jobmitra-UI"] = "1"
                yield client, connection, companies, contacts
        finally:
            app.dependency_overrides.clear()
            outer.rollback()


def staff(client, name="Test Recruiter"):
    response = client.post("/api/staff", json={"display_name": name})
    assert response.status_code == 201, response.text
    return response.json()


def job(client, company_id, actor, **values):
    response = client.post(
        "/api/jobs",
        json={
            "company_id": str(company_id),
            "actor_staff_id": actor["id"],
            "job_title": "Analyst",
            **values,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def action(client, jd, actor, suffix="", method="PATCH", **values):
    current = client.get(f"/api/jobs/{jd['id']}").json()
    return client.request(
        method,
        f"/api/jobs/{jd['id']}{suffix}",
        json={"actor_staff_id": actor["id"], "version": current["version"], **values},
    )


ATS = {
    "schema_version": 1,
    "keywords": ["analysis"],
    "suggested_required_skills": ["Power BI"],
    "suggested_preferred_skills": [],
    "semantic_summary": "Test enrichment",
    "professional_jd": "Test JD",
}


def test_additive_migration_roundtrip_preserves_stage1_and_models(database):
    engine, _, _, _, before, columns = database
    with engine.begin() as connection:
        assert set(inspect(connection).get_table_names()) == set(
            STAGE2_TABLES | STAGE3_TABLES | CANDIDATE_RESUME_TABLES
        ) | {
            "companies",
            "company_contacts",
            "alembic_version",
        }
        assert json.dumps(
            {name: inspect(connection).get_columns(name) for name in columns},
            default=str,
            sort_keys=True,
        ) == json.dumps(columns, default=str, sort_keys=True)
        assert company_snapshot(connection) == before
        assert (
            compare_metadata(
                MigrationContext.configure(
                    connection, opts={"compare_type": True, "compare_server_default": True}
                ),
                Base.metadata,
            )
            == []
        )
        connection.execute(text("CREATE TABLE unrelated_sentinel (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO unrelated_sentinel VALUES (42)"))
        cfg = Config("alembic.ini")
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0001_company_management")
        assert not (STAGE2_TABLES & set(inspect(connection).get_table_names()))
        assert company_snapshot(connection) == before
        assert connection.scalar(text("SELECT id FROM unrelated_sentinel")) == 42
        command.upgrade(cfg, "head")
        assert company_snapshot(connection) == before
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0007_candidate_resumes"
        )
        assert connection.scalar(text("SELECT count(*) FROM staff_members")) == 0
        connection.execute(text("DROP TABLE unrelated_sentinel"))


def test_sql_is_additive_and_contains_only_five_approved_tables():
    sql = Path("outputs/stage-2/0002_jd_tracking.sql").read_text()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == STAGE2_TABLES
    assert not re.search(
        r"^\s*(DROP\b|TRUNCATE\b|DELETE FROM\b|CREATE EXTENSION\b|CREATE ROLE\b)", sql, re.I | re.M
    )
    assert not re.search(r"ALTER TABLE (?:public\.)?(companies|company_contacts)\b", sql, re.I)
    assert not re.search(r"INSERT INTO (staff_members|companies|company_contacts)", sql, re.I)
    assert "0001_company_management" in sql and "0002_jd_tracking" in sql


def test_staff_dynamic_duplicates_rename_deactivate_and_history(ui):
    client, _, companies, _ = ui
    first = staff(client, "Test Person")
    duplicate = staff(client, "test person")
    assert duplicate["duplicate_name_warning"] and first["id"] != duplicate["id"]
    jd = job(client, companies[0], first)
    assert (
        client.patch(
            f"/api/staff/{first['id']}", json={"display_name": "Renamed Person"}
        ).status_code
        == 200
    )
    assert client.patch(f"/api/staff/{first['id']}", json={"is_active": False}).status_code == 200
    assert first["id"] not in {
        row["id"] for row in client.get("/api/staff?active_only=true").json()
    }
    history = client.get(f"/api/jobs/{jd['id']}/activities").json()
    assert history[0]["actor_display_name"] == "Test Person"
    assert history[0]["changes"]["actor"]["attribution"] == "self-selected/unverified"
    assert client.get(f"/api/jobs/{jd['id']}").json()["created_by_staff_id"] == first["id"]
    assert action(client, jd, first, job_title="Blocked actor").status_code == 422
    assert client.delete(f"/api/staff/{first['id']}").status_code == 405


def test_quick_jd_unknown_optional_fields_and_active_without_ai(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor, status="Active", raw_requirement="Rough company brief")
    assert jd["status"] == "Active" and jd["version"] == 1
    assert jd["salary_period"] == jd["salary_basis"] == "Unknown"
    assert all(
        jd[key] is None
        for key in (
            "salary_min",
            "salary_max",
            "vacancies",
            "experience_min_months",
            "experience_max_months",
            "received_at",
            "domain_key",
            "location_text",
            "ats_json",
        )
    )
    assert jd["required_skills"] == jd["preferred_skills"] == jd["recruiters"] == []
    assert jd["salary_currency"] == "INR"
    assert jd["general_skills"] == []
    assert jd["ats_status"] == "Not Added"


@pytest.mark.parametrize(
    "values",
    [
        {"experience_min_months": -1},
        {"experience_min_months": 24, "experience_max_months": 12},
        {"salary_min": "-1"},
        {"salary_min": "300", "salary_max": "200"},
        {"salary_min": "NaN"},
        {"salary_period": "Weekly"},
        {"salary_basis": None},
        {"vacancies": 0},
        {"vacancies": True},
        {"specific_skill_min_months": -1},
        {"target_date": "2026-12-01"},
        {"target_milestone": "SELECTION"},
        {"received_at": "2026-10-19T10:00:00"},
        {"job_title": "   "},
    ],
)
def test_invalid_criteria_rejected_without_insert(ui, values):
    client, connection, companies, _ = ui
    actor = staff(client)
    response = client.post(
        "/api/jobs",
        json={
            "company_id": str(companies[0]),
            "actor_staff_id": actor["id"],
            "job_title": "Test",
            **values,
        },
    )
    assert response.status_code == 422, response.text
    assert connection.scalar(text("SELECT count(*) FROM job_requirements")) == 0
    assert connection.scalar(text("SELECT count(*) FROM activities")) == 0


def test_contact_ownership_and_partial_patch_null_and_range_validation(ui):
    client, _, companies, contacts = ui
    actor = staff(client)
    response = client.post(
        "/api/jobs",
        json={
            "company_id": str(companies[0]),
            "company_contact_id": str(contacts[1]),
            "actor_staff_id": actor["id"],
            "job_title": "Mismatch",
        },
    )
    assert response.status_code == 422
    jd = job(
        client,
        companies[0],
        actor,
        company_contact_id=str(contacts[0]),
        location_text="Original",
        salary_min="100",
        salary_max="200",
    )
    changed = action(client, jd, actor, location_text=None).json()
    assert changed["location_text"] is None and changed["company_contact_id"] == str(contacts[0])
    assert action(client, jd, actor, salary_max="50").status_code == 422
    assert action(client, jd, actor, company_id=str(companies[1])).status_code == 422
    current = client.get(f"/api/jobs/{jd['id']}").json()
    assert current["salary_max"] == "200.00" and current["version"] == changed["version"]


def test_multiple_recruiters_reactivate_same_row_and_one_history_event(ui):
    client, connection, companies, _ = ui
    first, second = staff(client, "Test A"), staff(client, "Test B")
    jd = job(client, companies[0], first)
    both = action(client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"], second["id"]])
    assert both.status_code == 200, both.text
    assert len(both.json()["recruiters"]) == 2
    assert len(client.get(f"/api/jobs/{jd['id']}/activities").json()) == 2
    action(client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"]])
    action(client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"], second["id"]])
    assert len(connection.execute(select(JobRecruiter)).all()) == 2
    client.patch(f"/api/staff/{second['id']}", json={"is_active": False})
    assert (
        action(
            client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"], second["id"]]
        ).status_code
        == 200
    )
    action(client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"]])
    assert (
        action(
            client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"], second["id"]]
        ).status_code
        == 422
    )


def test_skills_dedupe_ats_separation_stale_and_simple_edit_history(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor, required_skills=["Excel", "excel", "SQL", " SQL "])
    assert jd["required_skills"] == ["Excel", "SQL"]
    enriched = action(client, jd, actor, "/ats-json", "PUT", ats=ATS, reviewed=True)
    assert enriched.status_code == 200, enriched.text
    assert enriched.json()["required_skills"] == ["Excel", "SQL"]
    changed = action(client, jd, actor, required_skills=["Excel", "SQL", "Power BI", "power bi"])
    assert changed.status_code == 200, changed.text
    assert changed.json()["required_skills"] == ["Excel", "SQL", "Power BI"]
    assert changed.json()["ats_json"] == ATS and changed.json()["ats_status"] == "Stale"
    history = client.get(f"/api/jobs/{jd['id']}/activities").json()
    change = next(row for row in history if row["event_type"] == "JD_CRITERIA_CHANGED")
    assert change["changes"]["fields"]["required_skills"] == {
        "before": ["Excel", "SQL"],
        "after": ["Excel", "SQL", "Power BI"],
    }
    assert "change_reason" not in change
    assert (
        action(client, jd, actor, "/ats-json", "PUT", ats={**ATS, "schema_version": 2}).status_code
        == 422
    )


def test_stale_version_http_409_and_noop_preserves_version(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor)
    same = action(client, jd, actor, job_title=jd["job_title"]).json()
    assert same["version"] == jd["version"]
    changed = action(client, jd, actor, job_title="Changed").json()
    response = client.patch(
        f"/api/jobs/{jd['id']}",
        json={"actor_staff_id": actor["id"], "version": jd["version"], "job_title": "Lost edit"},
    )
    assert response.status_code == 409 and "Reload" in response.json()["detail"]
    assert client.get(f"/api/jobs/{jd['id']}").json() == changed


@pytest.mark.parametrize("vacancies", [None, 2])
def test_target_labels_shortlist_and_no_fabricated_selection_or_joining(ui, vacancies):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor, status="Active", vacancies=vacancies)
    yesterday = (office_today("Asia/Kolkata") - timedelta(days=1)).isoformat()
    targeted = action(
        client, jd, actor, "/target", target_date=yesterday, target_milestone="SELECTION"
    ).json()
    assert targeted["target_state"] == "Overdue" and targeted["status"] == "Active"
    note = action(
        client,
        jd,
        actor,
        "/notes",
        "POST",
        note="A staff note about one selection is not verified evidence.",
    )
    assert note.status_code == 201
    assert action(client, jd, actor, "/shortlist-completion", "POST").status_code == 422
    action(client, jd, actor, vacancies=1)
    assert action(client, jd, actor, "/shortlist-completion", "POST").status_code == 422
    action(client, jd, actor, "/target", target_date=yesterday, target_milestone="JOINING")
    assert action(client, jd, actor, "/shortlist-completion", "POST").status_code == 422
    action(client, jd, actor, "/target", target_date=yesterday, target_milestone="SHORTLIST")
    complete = action(client, jd, actor, "/shortlist-completion", "POST").json()
    assert (
        complete["target_state"] == "Completed"
        and complete["target_completed_by_staff_id"] == actor["id"]
    )
    changed = action(
        client, jd, actor, "/target", target_date="2030-01-01", target_milestone="SHORTLIST"
    ).json()
    assert changed["target_completed_at"] is None and changed["target_state"] == "Upcoming"
    assert (
        action(
            client, jd, actor, "/target", target_date=None, target_milestone="SHORTLIST"
        ).status_code
        == 422
    )
    assert not any("count" in key or "pipeline_stage" in key for key in changed)


@pytest.mark.parametrize(
    "offset,label",
    [
        (None, "No Target"),
        (-1, "Overdue"),
        (0, "Due Today"),
        (1, "Due Soon"),
        (3, "Due Soon"),
        (4, "Upcoming"),
    ],
)
def test_office_calendar_target_labels(offset, label):
    today = date(2026, 10, 19)
    jd = SimpleNamespace(
        target_date=today + timedelta(days=offset) if offset is not None else None,
        target_milestone="SELECTION",
        target_completed_at=None,
    )
    assert target_state(jd, today) == label
    assert office_today("Asia/Kolkata", datetime(2026, 10, 18, 20, tzinfo=UTC)) == today


def test_closure_reason_and_reopen_history(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor)
    assert action(client, jd, actor, "/status", status="Closed").status_code == 422
    closed = action(
        client, jd, actor, "/status", status="Closed", closure_reason="Company cancelled the role"
    ).json()
    assert closed["closed_at"] and closed["closed_by_staff_id"] == actor["id"]
    reopened = action(client, jd, actor, "/status", status="Active").json()
    assert all(
        reopened[key] is None for key in ("closed_at", "closed_by_staff_id", "closure_reason")
    )
    assert any(
        row["changes"]["fields"].get("closure_reason", {}).get("before")
        == "Company cancelled the role"
        for row in client.get(f"/api/jobs/{jd['id']}/activities").json()
    )


def test_tasks_filter_reassign_done_cancel_overdue_and_inactive_history(ui):
    client, _, companies, _ = ui
    actor, second = staff(client, "Test A"), staff(client, "Test B")
    jd = job(client, companies[0], actor)
    due = (office_today("Asia/Kolkata") - timedelta(days=1)).isoformat()
    created = action(
        client,
        jd,
        actor,
        "/tasks",
        "POST",
        title="Company follow-up",
        assigned_staff_id=second["id"],
        due_date=due,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "Pending" and task["is_overdue"]
    assert len(client.get(f"/api/tasks?staff_id={second['id']}").json()) == 1
    assert client.get(f"/api/tasks?staff_id={actor['id']}").json() == []
    before = client.get("/api/tasks").json()
    client.get(f"/tasks?staff_id={actor['id']}")
    assert client.get("/api/tasks").json() == before
    patch = {
        "actor_staff_id": actor["id"],
        "version": task["job_version"],
        "assigned_staff_id": actor["id"],
    }
    changed = client.patch(f"/api/tasks/{task['id']}", json=patch).json()
    done = client.patch(
        f"/api/tasks/{task['id']}",
        json={"actor_staff_id": actor["id"], "version": changed["job_version"], "status": "Done"},
    ).json()
    assert (
        done["completed_at"]
        and done["completed_by_staff_id"] == actor["id"]
        and not done["is_overdue"]
    )
    other = action(
        client, jd, actor, "/tasks", "POST", title="Other follow-up", assigned_staff_id=second["id"]
    ).json()
    client.patch(f"/api/staff/{second['id']}", json={"is_active": False})
    assert len(client.get(f"/api/tasks?staff_id={second['id']}").json()) == 1
    cancelled = client.patch(
        f"/api/tasks/{other['id']}",
        json={
            "actor_staff_id": actor["id"],
            "version": other["job_version"],
            "status": "Cancelled",
        },
    ).json()
    assert cancelled["status"] == "Cancelled" and cancelled["completed_at"] is None
    assert (
        action(
            client,
            jd,
            actor,
            "/tasks",
            "POST",
            title="Invalid new owner",
            assigned_staff_id=second["id"],
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "operation",
    ["criteria", "recruiters", "target", "status", "ats", "note", "task_create", "task_update"],
)
def test_action_and_history_roll_back_together(ui, monkeypatch, operation):
    client, connection, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor)
    existing = action(
        client, jd, actor, "/tasks", "POST", title="Original task", assigned_staff_id=actor["id"]
    ).json()
    before = client.get(f"/api/jobs/{jd['id']}").json()
    tasks_before = client.get("/api/tasks").json()
    history_before = client.get(f"/api/jobs/{jd['id']}/activities").json()
    companies_before = company_snapshot(connection)

    def fail(*args, **kwargs):
        raise WorkflowError("Simulated audit failure", 503)

    monkeypatch.setattr(ActivityService, "append_change_event", staticmethod(fail))
    calls = {
        "criteria": lambda: action(client, jd, actor, job_title="Must roll back"),
        "recruiters": lambda: action(
            client, jd, actor, "/recruiters", "PUT", staff_ids=[actor["id"]]
        ),
        "target": lambda: action(
            client, jd, actor, "/target", target_date="2030-01-01", target_milestone="SHORTLIST"
        ),
        "status": lambda: action(client, jd, actor, "/status", status="Active"),
        "ats": lambda: action(client, jd, actor, "/ats-json", "PUT", ats=ATS),
        "note": lambda: action(client, jd, actor, "/notes", "POST", note="Must roll back"),
        "task_create": lambda: action(
            client,
            jd,
            actor,
            "/tasks",
            "POST",
            title="Must roll back",
            assigned_staff_id=actor["id"],
        ),
        "task_update": lambda: client.patch(
            f"/api/tasks/{existing['id']}",
            json={"actor_staff_id": actor["id"], "version": before["version"], "status": "Done"},
        ),
    }
    assert calls[operation]().status_code == 503
    assert client.get(f"/api/jobs/{jd['id']}").json() == before
    assert client.get("/api/tasks").json() == tasks_before
    assert client.get(f"/api/jobs/{jd['id']}/activities").json() == history_before
    assert company_snapshot(connection) == companies_before


def test_create_job_rolls_back_when_history_fails(ui, monkeypatch):
    client, connection, companies, _ = ui
    actor = staff(client)

    def fail(*args, **kwargs):
        raise WorkflowError("Simulated audit failure", 503)

    monkeypatch.setattr(ActivityService, "append_change_event", staticmethod(fail))
    response = client.post(
        "/api/jobs",
        json={
            "company_id": str(companies[0]),
            "actor_staff_id": actor["id"],
            "job_title": "Must roll back",
        },
    )
    assert response.status_code == 503
    assert connection.scalar(text("SELECT count(*) FROM job_requirements")) == 0


def test_job_listing_has_constant_query_count_and_real_filters(ui):
    client, connection, companies, _ = ui
    first, second = staff(client, "Test A"), staff(client, "Test B")
    for number in range(18):
        jd = job(
            client,
            companies[number % 2],
            first,
            job_title=f"Role {number}",
            status="Active" if number % 2 else "Draft",
            domain_key="Finance" if number % 2 else None,
            required_skills=["Excel"],
        )
        action(client, jd, first, "/recruiters", "PUT", staff_ids=[first["id"], second["id"]])
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        response = client.get("/api/jobs")
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert response.status_code == 200 and len(response.json()) == 18
    assert len(statements) == 2
    assert all(len(row["recruiters"]) == 2 and "ats_json" not in row for row in response.json())
    assert (
        len(
            client.get(
                f"/api/jobs?status=Active&recruiter_id={second['id']}&domain=finance&skill=excel"
            ).json()
        )
        == 9
    )
    assert len(client.get("/api/jobs?q=Isolated%20Company%200").json()) == 9


def test_pages_fragments_local_assets_and_no_fake_candidate_metrics(ui):
    client, _, companies, _ = ui
    actor = staff(client, "<script>unsafe</script>")
    jd = job(client, companies[0], actor, job_title="<img src=x onerror=alert(1)>")
    for path in [
        "/overview",
        "/requirements",
        "/requirements/new",
        "/staff",
        "/tasks",
        f"/requirements/{jd['id']}",
    ]:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert "<script>unsafe</script>" not in response.text
        assert "<img src=x onerror=alert(1)>" not in response.text
        assert "Self-selected, unverified attribution" in response.text
    fragment = client.get("/requirements?status=&recruiter_id=&q=", headers={"HX-Request": "true"})
    assert (
        fragment.status_code == 200
        and "<html" not in fragment.text
        and "jobs-results" in fragment.text
    )
    assert client.get("/tasks?staff_id=&status=", headers={"HX-Request": "true"}).status_code == 200
    page = client.get(f"/requirements/{jd['id']}").text
    assert "not connected" in page and "Stage 2" in page
    assert "current_pipeline_stage" not in page and "selected_count" not in page
    for asset in ["workflow.css", "workflow.mjs", "vendor/htmx.min.js"]:
        response = client.get("/static/stage2/" + asset)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert (
        client.post(
            "/api/staff",
            json={"display_name": "Untrusted"},
            headers={"Origin": "https://outside.invalid"},
        ).status_code
        == 403
    )


def test_database_checks_reject_invalid_target_and_preserve_company_fk(ui):
    client, connection, companies, contacts = ui
    actor = staff(client)
    jd = job(client, companies[0], actor, company_contact_id=str(contacts[0]))
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE job_requirements SET "
                    "target_milestone='SELECTION',target_date=NULL WHERE id=:id"
                ),
                {"id": jd["id"]},
            )
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text("DELETE FROM company_contacts WHERE id=:id"), {"id": contacts[0]}
            )
    assert client.get(f"/api/jobs/{jd['id']}").status_code == 200


def test_remote_migration_is_blocked_without_opt_in(monkeypatch):
    import jobmitra.core.config as config
    import jobmitra.core.database as database

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(db_name="jobmitra_dev", db_host="remote.invalid"),
    )
    monkeypatch.setattr(
        database, "build_engine", lambda *_: pytest.fail("Remote connection forbidden")
    )
    with pytest.raises(RuntimeError, match="explicitly approved"):
        command.upgrade(Config("alembic.ini"), "head")


FOCUS_EXPECTED = [
    ("CANDIDATE_POOL", "Candidate Pool"),
    ("CANDIDATE_CONTACT", "Candidate Contact"),
    ("JOBMITRA_SCREENING", "Jobmitra Screening"),
    ("COMPANY_SUBMISSION", "Company Submission"),
    ("INTERVIEWS", "Interviews"),
    ("SELECTION", "Selection"),
    ("JOINING", "Joining"),
]


def test_work_focus_persistence_history_order_noop_clear_and_independence(ui):
    from jobmitra.modules.jobs.focus import FOCUS_STAGES

    assert list(FOCUS_STAGES) == FOCUS_EXPECTED
    client, connection, companies, _ = ui
    actor = staff(client)
    jd = job(
        client,
        companies[0],
        actor,
        status="On Hold",
        vacancies=3,
        target_date="2030-01-01",
        target_milestone="SELECTION",
    )
    before_companies = company_snapshot(connection)
    url = f"/api/jobs/{jd['id']}"
    initial_page = client.get(f"/requirements/{jd['id']}").text
    assert "Focus not set" in initial_page and 'class="process-step is-current"' not in initial_page
    assert jd["current_work_focus"] is None
    for code, label in FOCUS_EXPECTED:
        old = client.get(url).json()
        history_before = client.get(url + "/activities").json()
        result = action(client, jd, actor, "/work-focus", current_work_focus=code)
        assert result.status_code == 200, result.text
        saved = client.get(url).json()
        assert saved == result.json() and saved["current_work_focus"] == code
        for key in old.keys() - {"current_work_focus", "version", "updated_at"}:
            assert saved[key] == old[key], key
        assert saved["version"] == old["version"] + 1
        history = client.get(url + "/activities").json()
        assert len(history) == len(history_before) + 1
        prior_ids = {item["id"] for item in history_before}
        event = next(item for item in history if item["id"] not in prior_ids)
        assert event["event_type"] == "WORK_FOCUS_CHANGED"
        assert event["actor_staff_id"] == actor["id"] and event["occurred_at"]
        assert event["changes"]["fields"] == {
            "current_work_focus": {"before": old["current_work_focus"], "after": code}
        }
        assert event["changes"]["actor"]["attribution"] == "self-selected/unverified"
        page = client.get(f"/requirements/{jd['id']}").text
        assert page.count('class="process-step is-current"') == 1
        assert "Recruiter Screening" not in page and "is-complete" not in page
        assert "selected_count" not in page and "not connected" in page
        assert page.index('class="process-tracker"') < page.index('class="controls"')
        assert page.index('class="controls"') < page.index('class="tabs"')
        assert label in page
        stages = re.findall(r'<span class="step-marker"[^>]*>\d</span><span>(.*?)</span>', page)
        assert stages == [label for _, label in FOCUS_EXPECTED]
        noop = action(client, jd, actor, "/work-focus", current_work_focus=code)
        assert noop.json() == saved
        assert client.get(url + "/activities").json() == history
    assert client.get(url).json()["target_completed_at"] is None
    assert action(client, jd, actor, "/shortlist-completion", "POST").status_code == 422
    for empty in (None, ""):
        assert action(client, jd, actor, "/work-focus", current_work_focus=empty).status_code == 200
        assert client.get(url).json()["current_work_focus"] is None
    assert 'class="process-step is-current"' not in client.get(f"/requirements/{jd['id']}").text
    assert company_snapshot(connection) == before_companies
    assert client.get("/companies").status_code == 200


@pytest.mark.parametrize("value", ["RECRUITER_SCREENING", "Closed", "UNKNOWN", 1, []])
def test_work_focus_rejects_unknown_codes_without_writes(ui, value):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor)
    url = f"/api/jobs/{jd['id']}"
    history = client.get(url + "/activities").json()
    assert action(client, jd, actor, "/work-focus", current_work_focus=value).status_code == 422
    assert client.get(url).json() == jd
    assert client.get(url + "/activities").json() == history


def test_work_focus_stale_write_and_audit_failure_are_atomic(ui, monkeypatch):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(client, companies[0], actor)
    url = f"/api/jobs/{jd['id']}"
    saved = action(client, jd, actor, "/work-focus", current_work_focus="CANDIDATE_CONTACT").json()
    history = client.get(url + "/activities").json()
    stale = client.patch(
        url + "/work-focus",
        json={
            "actor_staff_id": actor["id"],
            "version": jd["version"],
            "current_work_focus": "INTERVIEWS",
        },
    )
    assert stale.status_code == 409

    def fail(*args, **kwargs):
        raise WorkflowError("Simulated audit failure", 503)

    monkeypatch.setattr(ActivityService, "append_change_event", staticmethod(fail))
    assert action(client, jd, actor, "/work-focus", current_work_focus="JOINING").status_code == 503
    assert client.get(url).json() == saved
    assert client.get(url + "/activities").json() == history


def test_work_focus_migration_preserves_populated_stage2(database):
    engine, _, companies, _, _, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, "0002_jd_tracking")
            actor, jd = uuid4(), uuid4()
            connection.execute(
                text("INSERT INTO staff_members (id,display_name) VALUES (:id,'Migration test')"),
                {"id": actor},
            )
            connection.execute(
                text(
                    "INSERT INTO job_requirements (id,company_id,created_by_staff_id,job_title) "
                    "VALUES (:id,:company,:actor,'Existing JD')"
                ),
                {"id": jd, "company": companies[0], "actor": actor},
            )
            names = sorted(STAGE2_TABLES | {"companies", "company_contacts"})

            def snapshots():
                return {
                    name: connection.execute(
                        text(
                            f"SELECT to_jsonb(t) - 'current_work_focus' FROM {name} t "
                            "ORDER BY to_jsonb(t)::text"
                        )
                    )
                    .scalars()
                    .all()
                    for name in names
                }

            before = snapshots()
            command.upgrade(cfg, "0003_jd_work_focus")
            assert snapshots() == before
            assert (
                connection.scalar(
                    text("SELECT current_work_focus FROM job_requirements WHERE id=:id"), {"id": jd}
                )
                is None
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE job_requirements SET current_work_focus='RECRUITER_SCREENING' "
                        "WHERE id=:id"
                    ),
                    {"id": jd},
                )
            command.downgrade(cfg, "0002_jd_tracking")
            assert snapshots() == before
            assert "current_work_focus" not in {
                c["name"] for c in inspect(connection).get_columns("job_requirements")
            }
            command.upgrade(cfg, "head")
        finally:
            transaction.rollback()


def test_general_skills_preserve_confirmed_criteria_and_ats(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(
        client,
        companies[0],
        actor,
        required_skills=["SQL"],
        preferred_skills=["Excel"],
        specific_skill="Payroll",
        specific_skill_min_months=18,
        salary_currency="USD",
        salary_min="1000",
        salary_max="2000",
        salary_period="Monthly",
        qualification="BCom",
        raw_requirement="Company confirmed brief",
    )
    assert action(client, jd, actor, "/ats-json", "PUT", ats=ATS, reviewed=False).status_code == 200
    before = client.get(f"/api/jobs/{jd['id']}").json()
    result = action(
        client, jd, actor, general_skills=" Power   BI, Excel\nPOWER BI, ,\n Excel\r\nPython "
    )
    assert result.status_code == 200, result.text
    after = result.json()
    assert after["general_skills"] == ["Power BI", "Excel", "Python"]
    for key in before.keys() - {"general_skills", "version", "updated_at", "ats_status"}:
        assert after[key] == before[key], key
    assert after["ats_status"] == "Stale"
    assert action(client, jd, actor, general_skills=" , \n ").json()["general_skills"] == []
    html = client.get(f"/requirements/{jd['id']}").text
    assert 'name="salary_currency"' not in html
    assert 'name="required_skills"' not in html
    assert 'name="specific_skill"' not in html
    assert "Previously confirmed requirements" in html
    assert "salary editing is unavailable" in html
    assert "Payroll" in html and "18 months" in html


def test_general_skills_creation_and_salary_edit(ui):
    client, _, companies, _ = ui
    actor = staff(client)
    jd = job(
        client,
        companies[0],
        actor,
        general_skills=[" Excel, SQL ", "excel", " \n"],
        salary_min="25000",
        salary_max="50000",
        salary_period="Monthly",
    )
    assert jd["general_skills"] == ["Excel", "SQL"]
    assert jd["required_skills"] == jd["preferred_skills"] == []
    assert jd["specific_skill"] is None and jd["salary_currency"] == "INR"
    updated = action(
        client, jd, actor, salary_period="Annual", salary_min="300000", salary_max="600000"
    ).json()
    assert updated["salary_period"] == "Annual"
    assert float(updated["salary_min"]) == 300000
    assert updated["general_skills"] == jd["general_skills"]
    assert action(client, jd, actor, general_skills=[None]).status_code == 422
    html = client.get("/requirements/new").text
    assert "Skills (Optional)" in html and "₹" in html
    assert 'name="salary_currency"' not in html


def test_general_skills_migration_preserves_existing_rows(database):
    engine, _, companies, _, _, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            cfg = Config("alembic.ini")
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, "0004_candidate_desk")
            actor, jd = uuid4(), uuid4()
            connection.execute(
                text("INSERT INTO staff_members (id,display_name) VALUES (:id,'Migration test')"),
                {"id": actor},
            )
            connection.execute(
                text("""INSERT INTO job_requirements
                (id,company_id,created_by_staff_id,job_title,required_skills,preferred_skills,
                 specific_skill,specific_skill_min_months,salary_currency,salary_min)
                VALUES (:id,:company,:actor,'Legacy',ARRAY['SQL'],ARRAY['Excel'],
                        'Payroll',18,'USD',1000)"""),
                {"id": jd, "company": companies[0], "actor": actor},
            )
            before = dict(
                connection.execute(text("SELECT * FROM job_requirements WHERE id=:id"), {"id": jd})
                .mappings()
                .one()
            )
            command.upgrade(cfg, "0005_jd_general_skills")
            after = dict(
                connection.execute(text("SELECT * FROM job_requirements WHERE id=:id"), {"id": jd})
                .mappings()
                .one()
            )
            assert after.pop("general_skills") == []
            assert after == before
        finally:
            transaction.rollback()
