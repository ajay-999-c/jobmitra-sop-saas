"""Shared guarded workflow database: initialized once per isolated pytest process."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from jobmitra.core.config import Settings
from jobmitra.core.database import build_engine
from jobmitra.modules.companies.models import Company, CompanyContact


def company_snapshot(connection):
    return {
        model.__tablename__: list(connection.execute(select(model.__table__).order_by(model.id)))
        for model in (Company, CompanyContact)
    }


@pytest.fixture(scope="session")
def workflow_database():
    assert os.getenv("JOBMITRA_STAGE2_DISPOSABLE") == "1", "Isolated runner required"
    settings = Settings(_env_file=None)
    socket = Path(settings.db_host)
    assert str(socket).startswith("/private/tmp/jobmitra-stage2-") and socket.name == "socket"
    assert settings.db_user == "stage2_test" and settings.db_name == "jobmitra_dev"
    engine = build_engine(settings)
    with engine.begin() as connection:
        assert connection.scalar(text("SHOW listen_addresses")) == ""
        assert Path(connection.scalar(text("SHOW data_directory"))).parent == socket.parent
        cfg = Config("alembic.ini")
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0001_company_management")
        companies = [uuid4(), uuid4()]
        contacts = [uuid4(), uuid4()]
        for number, company_id in enumerate(companies):
            connection.execute(
                Company.__table__.insert().values(
                    id=company_id,
                    company_name=f"Isolated Company {number}",
                    company_name_key=f"isolated company {number}",
                    general_phone_numbers=["000123"],
                    source_register_ids=[f"TEST-{number}"],
                    city=None,
                )
            )
            connection.execute(
                CompanyContact.__table__.insert().values(
                    id=contacts[number],
                    company_id=company_id,
                    contact_name=f"Isolated Contact {number}",
                    phone_numbers=[],
                )
            )
        before = company_snapshot(connection)
        old_columns = {
            name: inspect(connection).get_columns(name)
            for name in ("companies", "company_contacts")
        }
        command.upgrade(cfg, "head")
        assert company_snapshot(connection) == before
    try:
        yield engine, settings, companies, contacts, before, old_columns
    finally:
        engine.dispose()
