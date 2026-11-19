"""ATS companies are imported local records; PostgreSQL is never a runtime dependency."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import companies
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.database import build_ats_engine, initialize, transaction
from jobmitra.modules.ats_v2.jobs import create_job
from jobmitra.modules.ats_v2.schemas import JobCreate


def add_company(engine, name="Imported Company", *, active=True):
    identifier = str(uuid4())
    with transaction(engine) as connection:
        connection.execute(
            text(
                "INSERT INTO companies(id,legacy_postgres_id,company_name,company_name_key,"
                "is_active) VALUES(:id,:id,:name,:key,:active)"
            ),
            {"id": identifier, "name": name, "key": name.casefold(), "active": int(active)},
        )
    return {"id": identifier, "company_name": name}


@pytest.fixture
def store(tmp_path):
    engine = build_ats_engine(tmp_path / "companies.sqlite3")
    initialize(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_options_are_sorted_active_local_companies_only(store):
    beta = add_company(store, "Beta Company")
    alpha = add_company(store, "Alpha Company")
    add_company(store, "Inactive Company", active=False)
    assert companies.CompanyGateway(store).options() == [alpha, beta]


@pytest.mark.parametrize("as_text", [False, True])
def test_require_preserves_exact_imported_uuid(store, as_text):
    record = add_company(store)
    identifier = record["id"] if as_text else UUID(record["id"])
    assert companies.CompanyGateway(store).require(identifier) == record


def test_invalid_missing_and_inactive_company_ids_are_rejected(store):
    inactive = add_company(store, active=False)
    gateway = companies.CompanyGateway(store)
    for identifier in ["unverified-company-id", uuid4(), inactive["id"]]:
        with pytest.raises(AtsError) as error:
            gateway.require(identifier)
        assert error.value.status == 422
    with store.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 1


def test_postgres_engine_is_rejected_before_any_connection():
    postgres = Mock(dialect=SimpleNamespace(name="postgresql"))
    with pytest.raises(AtsError) as error:
        companies.CompanyGateway(postgres)
    assert error.value.status == 503
    postgres.connect.assert_not_called()


@pytest.mark.parametrize("operation", ["options", "require", "names", "detail"])
def test_sqlite_failure_is_safe_503_without_private_details(operation):
    engine = Mock(dialect=SimpleNamespace(name="sqlite"))
    engine.connect.side_effect = SQLAlchemyError("private-path:secret-value")
    gateway = companies.CompanyGateway(engine)
    with pytest.raises(AtsError) as error:
        if operation == "options":
            gateway.options()
        elif operation == "require":
            gateway.require(uuid4())
        elif operation == "detail":
            gateway.detail(uuid4())
        else:
            gateway.names([uuid4()])
    assert error.value.status == 503
    assert "secret-value" not in str(error.value)
    assert "private-path" not in str(error.value)


def test_historical_names_resolve_inactive_companies_without_allowing_new_jds(store):
    active = add_company(store, "Active Company")
    inactive = add_company(store, "Retired Company", active=False)
    missing = str(uuid4())
    gateway = companies.CompanyGateway(store)
    jobs = [{"company_id": row["id"]} for row in [active, inactive]] + [{"company_id": missing}]
    assert companies.resolve_companies(jobs, gateway) is None
    assert [row["company_name"] for row in jobs] == ["Active Company", "Retired Company", None]
    assert [row["company_missing"] for row in jobs] == [False, False, True]
    assert jobs[-1]["company_id"] == missing
    assert gateway.options() == [active]


def test_create_jd_references_existing_local_company(store):
    record = add_company(store)
    gateway = companies.CompanyGateway(store)
    saved = create_job(
        store,
        JobCreate(
            company_id=record["id"],
            title="Local Company Engineer",
            target_date=(datetime.now(UTC) + timedelta(days=7)).date(),
            status="ACTIVE",
        ),
        gateway,
    )
    assert saved["company_id"] == record["id"]
    with store.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 1
        assert connection.scalar(text("SELECT company_id FROM job_descriptions")) == record["id"]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_real_ats_company_routes_work_when_postgres_is_forbidden(store, monkeypatch, tmp_path):
    record = add_company(store)
    postgres = Mock()
    postgres.connect.side_effect = AssertionError("PostgreSQL runtime access is forbidden")
    postgres.raw_connection.side_effect = AssertionError("PostgreSQL runtime access is forbidden")
    monkeypatch.setattr("jobmitra.main.build_engine", lambda _: postgres)
    settings = Settings(
        _env_file=None,
        db_host="unavailable.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=store.url.database,
        ats_v2_resume_storage_root=tmp_path / "resumes",
    )
    with TestClient(create_app(settings)) as client:
        options = client.get("/api/ats-v2/companies")
        assert options.status_code == 200
        assert options.json() == [record]
        detail = client.get("/api/ats-v2/companies/" + record["id"])
        assert detail.status_code == 200
        assert detail.json()["company_name"] == record["company_name"]
        assert detail.json()["contacts"] == []
        assert "source_json" not in detail.json()
        assert client.get("/api/ats-v2/companies/" + str(uuid4())).status_code == 404
        job = client.post(
            "/api/ats-v2/jobs",
            headers={"X-Jobmitra-UI": "1"},
            json={
                "company_id": record["id"],
                "title": "Local-only Engineer",
                "target_date": "2030-01-01",
                "status": "ACTIVE",
            },
        )
        assert job.status_code == 201, job.text
        listing = client.get("/api/ats-v2/jobs")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["company_name"] == record["company_name"]
        assert listing.json()["company_error"] is None
        assert client.get("/api/ats-v2/candidates").status_code == 200
        assert client.get("/jd-workspace-v2").status_code == 200
    postgres.connect.assert_not_called()
    postgres.raw_connection.assert_not_called()
