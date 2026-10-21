"""Focused metadata and migration-SQL checks; no live database needed."""

from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects.postgresql import ARRAY

from jobmitra.modules.companies.models import COMPANY_TABLES, Company, CompanyContact
from jobmitra.modules.companies.normalization import company_name_key, distinct_text_values


def test_exactly_two_business_tables_and_requested_columns():
    assert COMPANY_TABLES == {"companies", "company_contacts"}
    assert set(Company.__table__.columns.keys()) == {
        "id",
        "company_name",
        "company_name_key",
        "general_phone_numbers",
        "address_line",
        "city",
        "state",
        "postal_code",
        "source_register_ids",
        "created_at",
        "updated_at",
    }
    assert set(CompanyContact.__table__.columns.keys()) == {
        "id",
        "company_id",
        "contact_name",
        "designation",
        "phone_numbers",
        "created_at",
        "updated_at",
    }
    for name in ("address_line", "city", "state", "postal_code"):
        assert Company.__table__.c[name].nullable
        assert Company.__table__.c[name].server_default is None
    for column in (
        Company.__table__.c.general_phone_numbers,
        Company.__table__.c.source_register_ids,
        CompanyContact.__table__.c.phone_numbers,
    ):
        assert isinstance(column.type, ARRAY)
        assert not column.nullable


@pytest.mark.parametrize("value", [" ACME  Limited ", "acme limited", "ＡＣＭＥ limited"])
def test_normalized_name_key(value):
    assert company_name_key(value) == "acme limited"


def test_normalization_does_not_merge_legal_names_by_punctuation():
    assert company_name_key("A.B. Ltd") != company_name_key("AB Ltd")
    assert distinct_text_values(["01234567890", "01234567890", " 1234567890 "]) == [
        "01234567890",
        "1234567890",
    ]


@pytest.mark.parametrize("value", ["", "   ", None])
def test_invalid_company_names(value):
    with pytest.raises(ValueError):
        Company(company_name=value)


def test_offline_migration_sql_is_limited_to_company_schema():
    output = StringIO()
    cfg = Config("alembic.ini", output_buffer=output)
    command.upgrade(cfg, "0001_company_management", sql=True)
    sql = output.getvalue()
    assert sql.count("CREATE TABLE ") == 3  # Two business tables plus Alembic bookkeeping.
    assert "CREATE TABLE companies" in sql and "CREATE TABLE company_contacts" in sql
    assert "TEXT[]" in sql and "UNIQUE (company_name_key)" in sql
    for forbidden in (
        "DROP ",
        "ALTER ",
        "EXTENSION",
        "VECTOR",
        "INSERT INTO companies",
        "INSERT INTO company_contacts",
    ):
        assert forbidden not in sql.upper() if forbidden.isupper() else forbidden not in sql
