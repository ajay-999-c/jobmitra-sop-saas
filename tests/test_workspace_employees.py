"""Canonical employee CRUD and assignment on explicit disposable office PG schemas."""

import importlib.util
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from jobmitra.core.config import PROJECT_ENV_FILE, Settings
from jobmitra.modules.ats_v2 import jobs, workspace_store
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.ats_v2.postgres import build_postgres_engine, validate_postgres
from jobmitra.modules.ats_v2.schemas import JobCreate, JobPatch
from jobmitra.modules.staff.employees import EmployeeInput, StaffChangeEvent, save
from jobmitra.modules.staff.models import StaffMember


@pytest.fixture(scope="module")
def office_workspace():
    if os.environ.get("JOBMITRA_OFFICE_WORKSPACE_TESTS") != "1":
        pytest.skip("Explicit isolated-office-schema opt-in required")
    config = Settings(
        _env_file=[PROJECT_ENV_FILE, PROJECT_ENV_FILE.with_name(".env.v12.mac.postgres")]
    )
    suffix = uuid4().hex[:12]
    schema = "jobmitra_v12_dev_ws_test_" + suffix
    staff_schema = "jobmitra_v12_dev_staff_" + suffix
    spec = importlib.util.spec_from_file_location(
        "workspace_provision",
        Path(__file__).resolve().parents[1] / "scripts/prepare_postgres_v12_dev.py",
    )
    # Provisioner's sibling import resolves through its existing scripts directory.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kwargs = dict(
        host=config.db_host,
        port=config.db_port,
        dbname=config.db_name,
        user=config.db_user,
        password=config.db_password.get_secret_value(),
        sslmode=config.db_sslmode,
        connect_timeout=5,
    )
    legacy = create_engine(config.database_url, hide_parameters=True).execution_options(
        schema_translate_map={None: staff_schema}
    )
    engine = None
    try:
        with psycopg.connect(**kwargs) as conn:
            module.provision(conn, schema)
            conn.execute(f'CREATE SCHEMA "{staff_schema}"')
        StaffMember.__table__.create(legacy)
        StaffChangeEvent.__table__.create(legacy)
        # Failed cross-schema reference must roll back every workspace DDL change.
        with psycopg.connect(**kwargs) as conn:
            with pytest.raises(psycopg.Error):
                with conn.transaction():
                    workspace_store.apply_postgres(conn, schema, "jobmitra_v12_dev_missing_staff")
            assert (
                conn.execute(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_schema=%s AND column_name='assigned_recruiter_id'",
                    (schema,),
                ).fetchone()[0]
                == 0
            )
            workspace_store.apply_postgres(conn, schema, staff_schema)
            workspace_store.apply_postgres(conn, schema, staff_schema)  # repeatable
        config = config.model_copy(update={"v12_postgres_schema": schema})
        engine = build_postgres_engine(config)
        validate_postgres(engine)
        with transaction(engine) as conn:
            company = str(uuid4())
            conn.execute(
                text(
                    "INSERT INTO companies(id,company_name,company_name_key) "
                    "VALUES(:id,'Workspace Test Company','workspace test company')"
                ),
                {"id": company},
            )
        yield engine, legacy, company, config, staff_schema
    finally:
        if engine:
            engine.dispose()
        legacy.dispose()
        # Only random disposable namespaces created by this fixture may be removed.
        with psycopg.connect(**kwargs) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.execute(f'DROP SCHEMA IF EXISTS "{staff_schema}" CASCADE')


def employee(legacy, name="Workspace Test Recruiter", **changes):
    with Session(legacy) as session:
        return save(session, EmployeeInput(display_name=name, **changes), "OFFICE_LAN", uuid4())


def test_round_removal_restore_and_direct_progress_preserve_facts(office_workspace):
    from jobmitra.modules.ats_v2 import candidates, direct_movement
    from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
    from jobmitra.modules.ats_v2.schemas import WorkflowInput

    engine, _, company, *_ = office_workspace
    candidate = candidates.create_candidate(
        engine, CandidateCreate(full_name="Round safety fixture")
    )
    job = jobs.create_job(
        engine,
        JobCreate(company_id=company, title="Round safety", target_date="2099-01-01"),
        CompanyGateway(engine),
    )
    flow = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=0,
            rounds=[{"round_name": "Portfolio assessment"}, {"round_name": "Manager discussion"}],
        ),
    )
    link = jobs.attach_contact(engine, job["id"], candidate["id"])
    assert link["stage_code"] == "CONTACT"
    assert jobs.attach_contact(engine, job["id"], candidate["id"])["id"] == link["id"]
    facts = direct_movement.choices(engine, job["id"], link["id"])
    direct_movement.move(
        engine,
        job["id"],
        link["id"],
        direct_movement.DirectMove(
            idempotency_key=uuid4(),
            destination_stage="ROUND",
            destination_round_id=flow["rounds"][0]["id"],
            expected_stage="CONTACT",
            workflow_version=facts["workflow_version"],
        ),
        "OFFICE_LAN",
    )
    rounds = [{k: r[k] for k in ("id", "round_name", "mode", "is_active")} for r in flow["rounds"]]
    rounds[0]["is_active"] = False
    with pytest.raises(AtsError, match="Move candidates out"):
        jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(
                workflow_mode="CONFIGURED",
                workflow_version=1,
                rounds=rounds,
            ),
        )
    rounds[0]["is_active"], rounds[1]["is_active"] = True, False
    removed = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=1,
            rounds=rounds,
        ),
    )
    assert removed["rounds"][1]["retired_at"]
    rounds[1]["is_active"] = True
    restored = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=2,
            rounds=rounds,
        ),
    )
    assert [r["id"] for r in restored["rounds"]] == [r["id"] for r in flow["rounds"]]
    with engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM candidate_activities WHERE candidate_id=:c"),
                {"c": candidate["id"]},
            )
            == 0
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM recruitment_events WHERE jd_candidate_id=:l "
                    "AND event_type IN ('FEEDBACK','EMAIL_SEND_ATTEMPT','INTERVIEW_SCHEDULED')"
                ),
                {"l": link["id"]},
            )
            == 0
        )
    assert jobs.pipeline(engine, job["id"])["items"][0]["round_id"] == flow["rounds"][0]["id"]


def test_canonical_identity_optional_details_and_idempotency(office_workspace):
    _, legacy, *_ = office_workspace
    key = uuid4()
    data = EmployeeInput(
        display_name="Same Canonical Identity",
        email="recruiter@example.test",
        mobile="123",
        designation="Recruiter",
    )
    with Session(legacy) as session:
        first = save(session, data, "OFFICE_LAN", key)
        assert save(session, data, "OFFICE_LAN", key) == first
        member = session.get(StaffMember, UUID(first["id"]))
        assert str(member.id) == first["id"]
        assert member.email == data.email
    with pytest.raises(ValueError):
        EmployeeInput(display_name="Invalid", email="not an email")


def test_assignment_inactive_history_and_stale_edit(office_workspace):
    engine, legacy, company, *_ = office_workspace
    first = employee(legacy)
    second = employee(legacy, "Second Recruiter")
    gateway = CompanyGateway(engine)
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Assignment Test",
            target_date="2099-01-01",
            assigned_recruiter_id=first["id"],
        ),
        gateway,
    )
    assert str(job["assigned_recruiter_id"]) == first["id"]
    with Session(legacy) as session:
        inactive = save(
            session,
            EmployeeInput(
                display_name=first["display_name"],
                is_active=False,
                expected_revision=first["revision"],
            ),
            "OFFICE_LAN",
            uuid4(),
            UUID(first["id"]),
        )
        assert not inactive["is_active"]
    # Existing inactive assignment remains visible and does not block unrelated edits.
    edited = jobs.update_job(
        engine,
        job["id"],
        JobPatch(title="Changed title", expected_revision=job["revision"]),
        gateway,
    )
    assert str(edited["assigned_recruiter_id"]) == first["id"]
    with pytest.raises(AtsError, match="changed"):
        jobs.update_job(
            engine,
            job["id"],
            JobPatch(title="Stale overwrite", expected_revision=job["revision"]),
            gateway,
        )
    reassigned = jobs.update_job(
        engine,
        job["id"],
        JobPatch(assigned_recruiter_id=second["id"], expected_revision=edited["revision"]),
        gateway,
    )
    with pytest.raises(AtsError, match="active employee"):
        jobs.update_job(
            engine,
            job["id"],
            JobPatch(assigned_recruiter_id=first["id"], expected_revision=reassigned["revision"]),
            gateway,
        )
    with engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT payload_json,created_at FROM recruitment_events WHERE "
                "job_id=:j AND event_type='JD_RECRUITER_ASSIGNED' ORDER BY id"
            ),
            {"j": job["id"]},
        ).all()
        assert len(events) == 2 and all(row.created_at for row in events)
        assert first["id"] in events[1].payload_json and second["id"] in events[1].payload_json
    unassigned = jobs.create_job(
        engine,
        JobCreate(company_id=company, title="Unassigned compatible", target_date="2099-01-01"),
        gateway,
    )
    assert unassigned["assigned_recruiter_id"] is None


def test_staff_stale_update_and_duplicate_request_rejected(office_workspace):
    _, legacy, *_ = office_workspace
    row = employee(legacy, "Employee conflict")
    with Session(legacy) as session:
        changed = save(
            session,
            EmployeeInput(display_name="Employee renamed", expected_revision=row["revision"]),
            "LOCAL_DEVELOPMENT",
            uuid4(),
            UUID(row["id"]),
        )
        with pytest.raises(AtsError, match="changed"):
            save(
                session,
                EmployeeInput(display_name="Lost edit", expected_revision=row["revision"]),
                "LOCAL_DEVELOPMENT",
                uuid4(),
                UUID(row["id"]),
            )
        assert changed["revision"] != row["revision"]


def test_sqlite_adapter_extension_preserves_existing_rows(tmp_path):
    from jobmitra.modules.ats_v2.database import (
        build_ats_engine,
        initialize,
        upgrade_unified,
        validate,
    )

    engine = build_ats_engine(tmp_path / "isolated.sqlite3")
    initialize(engine)
    upgrade_unified(engine)
    with engine.connect() as conn:
        before = conn.execute(text("SELECT * FROM job_descriptions")).all()
    workspace_store.apply_sqlite(engine)
    workspace_store.apply_sqlite(engine)
    validate(engine)
    row = employee(engine, "SQLite canonical recruiter")
    with transaction(engine) as conn:
        cid = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key) "
                "VALUES(:id,'SQLite Client','sqlite client')"
            ),
            {"id": cid},
        )
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=cid,
            title="SQLite assigned",
            target_date="2099-01-01",
            assigned_recruiter_id=row["id"],
        ),
        CompanyGateway(engine),
    )
    assert str(job["assigned_recruiter_id"]) == row["id"]
    assert job["assigned_recruiter_name"] == row["display_name"]
    with Session(engine) as session:
        save(
            session,
            EmployeeInput(
                display_name=row["display_name"], expected_revision=row["revision"], is_active=False
            ),
            "LOCAL_DEVELOPMENT",
            uuid4(),
            UUID(row["id"]),
        )
    changed = jobs.update_job(
        engine,
        job["id"],
        JobPatch(title="Inactive retained", expected_revision=job["revision"]),
        CompanyGateway(engine),
    )
    assert changed["assigned_recruiter_id"] == row["id"]
    assert before == []
    validate(engine)
    engine.dispose()


def test_office_employee_api_and_protected_mutations(office_workspace, monkeypatch):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("JOBMITRA_GMAIL_ENABLED", "false")
    from jobmitra.main import create_app

    engine, legacy, _, config, staff_schema = office_workspace
    config = config.model_copy(
        update={
            "office_lan_enabled": True,
            "office_lan_cidrs": "127.0.0.0/8",
            "office_lan_hosts": "",
            "unified_v12_local_direct_editing": False,
            "gmail_enabled": False,
        }
    )
    headers = {"X-Jobmitra-UI": "1", "Idempotency-Key": str(uuid4()), "Origin": "http://127.0.0.1"}
    with (
        patch("jobmitra.main.build_engine", return_value=legacy),
        patch("jobmitra.modules.ats_v2.postgres.build_postgres_engine", return_value=engine),
    ):
        app = create_app(config)
        app.state.staff_schema = staff_schema
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000)) as client:
            created = client.post(
                "/api/v12/employees",
                json={"display_name": "API Search Recruiter", "email": "api@example.test"},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            row = created.json()
            found = client.get("/api/v12/employees?q=search%20RECRUIT").json()
            assert any(r["id"] == row["id"] for r in found["items"])
            canonical = client.get("/api/staff").json()
            assert any(r["id"] == row["id"] for r in canonical)
            headers["Idempotency-Key"] = str(uuid4())
            changed = client.patch(
                "/api/v12/employees/" + row["id"],
                json={
                    "display_name": "API Search Recruiter",
                    "is_active": False,
                    "expected_revision": row["revision"],
                },
                headers=headers,
            )
            assert changed.status_code == 200 and not changed.json()["is_active"]
            assert not any(
                r["id"] == row["id"]
                for r in client.get("/api/v12/employees?active_only=true").json()["items"]
            )
            assert (
                client.post(
                    "/api/v12/employees",
                    json={"display_name": "Cross origin"},
                    headers={**headers, "Origin": "http://untrusted.example"},
                ).status_code
                == 403
            )
        protected = create_app(config.model_copy(update={"office_lan_enabled": False}))
        protected.state.staff_schema = staff_schema
        with TestClient(protected, base_url="http://127.0.0.1") as client:
            assert (
                client.post(
                    "/api/v12/employees", json={"display_name": "Unauthorized"}, headers=headers
                ).status_code
                == 403
            )


def test_dashboard_recruiter_filter_uses_identity(office_workspace):
    from jobmitra.modules.ats_v2.jd_dashboard import Filters, browse

    engine, legacy, company, *_ = office_workspace
    row = employee(legacy, "Dashboard Assigned Recruiter")
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Filter identity",
            target_date="2099-01-01",
            assigned_recruiter_id=row["id"],
        ),
        CompanyGateway(engine),
    )
    result = browse(engine, Filters(assigned_recruiter_id=row["id"]))
    assert [r["id"] for r in result["items"]] == [job["id"]]
    assert result["items"][0]["assigned_recruiter_name"] == row["display_name"]
    assert browse(engine, Filters(q="dashboard assigned"))["total"] == 1
    assert all(
        r["assigned_recruiter_id"] is None
        for r in browse(engine, Filters(unassigned=True))["items"]
    )


def test_canonical_employee_migration_rolls_back_and_preserves_ids(office_workspace):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    _, legacy, *_ = office_workspace
    schema = "jobmitra_v12_dev_staff_mig_" + uuid4().hex[:10]
    identifier = uuid4()
    spec = importlib.util.spec_from_file_location(
        "employee_migration",
        Path(__file__).resolve().parents[1] / "migrations/versions/0008_employee_details.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        with legacy.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(
                text(
                    f'CREATE TABLE "{schema}".staff_members ('
                    "id UUID PRIMARY KEY,display_name TEXT NOT NULL,"
                    "is_active BOOLEAN NOT NULL DEFAULT true,"
                    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
                )
            )
            conn.execute(
                text(
                    f'INSERT INTO "{schema}".staff_members(id,display_name) '
                    "VALUES(:id,'Existing canonical identity')"
                ),
                {"id": identifier},
            )
        with legacy.begin() as conn:
            conn = conn.execution_options(schema_translate_map={None: schema})
            conn.execute(text(f'SET LOCAL search_path="{schema}",pg_catalog'))
            with pytest.raises(RuntimeError, match="rollback probe"):
                with conn.begin_nested():
                    with Operations.context(MigrationContext.configure(conn)):
                        migration.upgrade()
                    raise RuntimeError("rollback probe")
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema=:s AND column_name='email'"
                    ),
                    {"s": schema},
                )
                == 0
            )
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            assert conn.scalar(text(f'SELECT id FROM "{schema}".staff_members')) == identifier
            with Session(conn) as session:
                added = save(
                    session,
                    EmployeeInput(display_name="Migrated canonical master"),
                    "LOCAL_DEVELOPMENT",
                    uuid4(),
                )
                assert added["id"]
            with pytest.raises(Exception, match="immutable"):
                with conn.begin_nested():
                    conn.execute(text(f'DELETE FROM "{schema}".staff_change_events'))
    finally:
        with legacy.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_new_job_active_default_does_not_promote_existing_drafts(office_workspace):
    engine, _, company, *_ = office_workspace
    gateway = CompanyGateway(engine)
    old = jobs.create_job(
        engine,
        JobCreate(
            company_id=company, title="Intentional Draft", target_date="2099-01-01", status="DRAFT"
        ),
        gateway,
    )
    new = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="New Active Requirement",
            target_date="2099-01-01",
            salary_min_inr=0,
        ),
        gateway,
    )
    assert new["status"] == "ACTIVE"
    assert new["salary_min_inr"] == 0 and new["salary_max_inr"] is None and new["vacancies"] is None
    assert jobs.get_job(engine, old["id"])["status"] == "DRAFT"
    patched = jobs.update_job(
        engine,
        old["id"],
        JobPatch(title="Draft still editable", expected_revision=old["revision"]),
        gateway,
    )
    assert patched["status"] == "DRAFT"
