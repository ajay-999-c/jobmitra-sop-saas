"""Live focused tests confined to a rolled-back disposable schema, never source data."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobmitra.core.config import Settings
from jobmitra.core.database import build_engine
from jobmitra.modules.companies.models import Company, CompanyContact

pytestmark = pytest.mark.skipif(
    os.getenv("JOBMITRA_RUN_SCHEMA_TESTS") != "1", reason="Opt in to isolated local schema tests"
)


@pytest.fixture
def database():
    settings = Settings()
    assert settings.db_name == "jobmitra_dev"
    assert settings.db_host in {"localhost", "127.0.0.1", "::1"} or (
        os.getenv("JOBMITRA_STAGE2_DISPOSABLE") == "1"
        and settings.db_host.startswith("/private/tmp/jobmitra-stage2-")
    )
    engine = build_engine(settings)
    with engine.connect() as connection:
        transaction = connection.begin()
        schema = "test_company_" + uuid4().hex
        original_schema = connection.dialect.default_schema_name
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            # Match SQLAlchemy reflection's default to the transaction-local schema.
            connection.dialect.default_schema_name = schema
            cfg = Config("alembic.ini")
            cfg.attributes.update(connection=connection, version_table_schema=schema)
            command.upgrade(cfg, "0001_company_management")
            yield connection, cfg
        finally:
            transaction.rollback()
            connection.dialect.default_schema_name = original_schema
    engine.dispose()


def test_migration_matches_models_and_roundtrips(database):
    connection, cfg = database
    assert set(inspect(connection).get_table_names()) == {
        "companies",
        "company_contacts",
        "alembic_version",
    }
    context = MigrationContext.configure(
        connection, opts={"compare_type": True, "compare_server_default": True}
    )
    company_metadata = MetaData()
    for model in (Company, CompanyContact):
        model.__table__.to_metadata(company_metadata)
    assert compare_metadata(context, company_metadata) == []
    command.downgrade(cfg, "base")
    assert inspect(connection).get_table_names() == ["alembic_version"]
    command.upgrade(cfg, "0001_company_management")
    assert connection.scalar(text("SELECT count(*) FROM companies")) == 0


def test_create_without_contacts_or_phones(database):
    connection, _ = database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        company = Company(company_name="Schema Test Only")
        session.add(company)
        session.commit()
        assert company.id is not None
        assert company.contacts == []
        assert company.general_phone_numbers == company.source_register_ids == []
        assert (company.address_line, company.city, company.state, company.postal_code) == (
            None,
            None,
            None,
            None,
        )
        assert company.created_at.tzinfo is not None


def test_edit_preserves_ids_and_tracks_arrays(database):
    connection, _ = database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        company = Company(
            company_name="Original",
            general_phone_numbers=["01234567890"],
            source_register_ids=["TEST-1", "TEST-2"],
        )
        first = CompanyContact(company=company, contact_name=None, phone_numbers=[])
        second = CompanyContact(
            company=company,
            contact_name="Test Contact",
            phone_numbers=["1234567890", "09876543210"],
        )
        session.add_all([company, first, second])
        session.commit()
        ids = (company.id, first.id, second.id)
        company.company_name = " Renamed  Company "
        company.address_line, company.city = "Test Address", "Test City"
        company.state, company.postal_code = "Test State", "001234"
        company.general_phone_numbers.append("09876543210")
        first.contact_name, first.designation = "Updated Contact", "HR"
        first.phone_numbers.append("01111111111")
        session.commit()
        session.expire_all()
        assert (company.id, first.id, second.id) == ids
        assert company.company_name_key == "renamed company"
        assert company.general_phone_numbers == ["01234567890", "09876543210"]
        assert first.phone_numbers == ["01111111111"]
        assert company.source_register_ids == ["TEST-1", "TEST-2"]
        assert company.postal_code == "001234"
        company.city = None
        session.commit()
        assert company.city is None and company.state == "Test State"


def test_duplicate_normalized_names_are_rejected(database):
    connection, _ = database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        session.add(Company(company_name=" Acme  Test "))
        session.commit()
        session.add(Company(company_name="ACME TEST", company_name_key="incorrect override"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_foreign_key_and_delete_restriction(database):
    connection, _ = database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        session.add(CompanyContact(company_id=uuid4(), contact_name=None))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        company = Company(company_name="Referenced Test")
        session.add(CompanyContact(company=company))
        session.commit()
        session.delete(company)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_unmanaged_objects_and_pgvector_are_untouched(database):
    connection, cfg = database
    version = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
    connection.execute(text("CREATE TABLE unrelated_sentinel (id integer PRIMARY KEY)"))
    connection.execute(text("INSERT INTO unrelated_sentinel VALUES (7)"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "0001_company_management")
    assert connection.scalar(text("SELECT id FROM unrelated_sentinel")) == 7
    assert (
        connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        == version
    )


def test_database_array_defaults_and_null_element_constraint(database):
    connection, _ = database
    row = connection.execute(
        text(
            "INSERT INTO companies (id, company_name, company_name_key) "
            "VALUES (:id, 'Defaults Test', 'defaults test') "
            "RETURNING general_phone_numbers, source_register_ids"
        ),
        {"id": uuid4()},
    ).one()
    assert row.general_phone_numbers == row.source_register_ids == []
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, company_name, company_name_key, general_phone_numbers) "
                    "VALUES (:id, 'Null Test', 'null test', ARRAY[NULL]::text[])"
                ),
                {"id": uuid4()},
            )
