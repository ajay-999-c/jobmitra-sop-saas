"""Focused reconciliation and insert-only importer checks. Source Excel files stay read-only."""

import copy
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from jobmitra.core.config import Settings
from jobmitra.core.database import build_engine
from jobmitra.modules.companies.importer import (
    CompanyCandidate,
    ContactCandidate,
    ImportPlan,
    InvalidWorkbook,
    execute_import,
    read_inputs,
    validate_tables,
)
from jobmitra.modules.companies.models import Company, CompanyContact
from jobmitra.modules.companies.normalization import company_name_key

SOURCE = Path("outputs/phase-1a/company-dataset-cleaned.xlsx")
ORIGINAL = Path("company-dataset.xlsx")


@pytest.fixture(scope="module")
def inputs():
    return read_inputs(SOURCE, ORIGINAL)


def test_actual_workbook_reconciliation_and_quarantine(inputs):
    tables, originals, _ = inputs
    plan = validate_tables(tables, originals)
    summary = plan.summary()
    assert summary == {
        "company_candidates": 166,
        "original_entries": 180,
        "original_register_ids": 180,
        "eligible_companies": 131,
        "withheld_companies": 35,
        "eligible_source_register_ids": 134,
        "eligible_general_phone_values": 81,
        "eligible_contacts": 108,
        "contacts_skipped_ambiguous": 9,
        "contacts_skipped_parent_withheld": 42,
        "contact_candidates": 159,
        "review_items": 37,
    }
    assert all(all(v is None for v in c.address.values()) for c in plan.companies)
    assert all(p.designation is None for c in plan.companies for p in c.contacts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Company name key", "forged"),
        ("Company name", None),
        ("Source Register IDs", '["UNKNOWN"]'),
        ("General phone numbers", '["9999999999"]'),
        ("Source Excel rows", "999"),
    ],
)
def test_corrupt_company_mapping_is_rejected(inputs, field, value):
    tables, originals, _ = inputs
    changed = copy.deepcopy(tables)
    changed["Companies"][0][field] = value
    with pytest.raises(InvalidWorkbook):
        validate_tables(changed, originals)


def test_source_rows_cannot_be_altered_or_omitted(inputs):
    tables, originals, _ = inputs
    changed = copy.deepcopy(tables)
    changed["Source Rows"][0]["Company / client (as read)"] = "Forged original"
    with pytest.raises(InvalidWorkbook):
        validate_tables(changed, originals)
    changed = copy.deepcopy(tables)
    changed["Companies"].pop()
    with pytest.raises(InvalidWorkbook):
        validate_tables(changed, originals)


def test_contact_ownership_cannot_be_invented_and_contact_loss_is_rejected(inputs):
    tables, originals, _ = inputs
    changed = copy.deepcopy(tables)
    changed["Contacts"][0]["Phone numbers"] = '["01234567890"]'
    with pytest.raises(InvalidWorkbook):
        validate_tables(changed, originals)
    changed = copy.deepcopy(tables)
    changed["Contacts"].pop()
    with pytest.raises(InvalidWorkbook):
        validate_tables(changed, originals)


def test_deleting_review_flags_does_not_approve_identity_merges(inputs):
    tables, originals, _ = inputs
    changed = copy.deepcopy(tables)
    changed["Review"] = []
    for company in changed["Companies"]:
        company["Review status"] = "Single entry"
    plan = validate_tables(changed, originals)
    assert plan.summary()["withheld_companies"] == 35
    assert plan.summary()["eligible_contacts"] == 108


def test_review_approval_requires_category_specific_decision_and_note(inputs):
    tables, originals, _ = inputs
    changed = copy.deepcopy(tables)
    for row in changed["Review"]:
        row["Decision"] = "Merge confirmed"
    assert validate_tables(changed, originals).summary()["withheld_companies"] == 35
    # Wrong categories cannot be approved by a generic merge decision, even with a note.
    for row in changed["Review"]:
        if row["Review type"] in {"Similar names", "Shared phone"}:
            row["Reviewer note"] = "Test note"
    assert validate_tables(changed, originals).summary()["withheld_companies"] == 35


@pytest.fixture
def connection():
    if os.getenv("JOBMITRA_RUN_IMPORT_TESTS") != "1":
        pytest.skip("Set JOBMITRA_RUN_IMPORT_TESTS=1 for rollback-isolated PostgreSQL tests")
    settings = Settings()
    assert settings.db_name == "jobmitra_dev"
    assert settings.db_host in {"localhost", "127.0.0.1", "::1"}
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def candidate(name=None, ids=None, contacts=True):
    name = name or f"Import Test {uuid4()}"
    return CompanyCandidate(
        name,
        company_name_key(name),
        ids or [f"TEST-{uuid4()}"],
        ["01234567890"],
        dict(address_line=None, city=None, state=None, postal_code=None),
        7,
        [ContactCandidate("Test Contact", None, 7)] if contacts else [],
    )


def run(connection, plan, apply=True):
    with Session(connection, join_transaction_mode="create_savepoint") as session, session.begin():
        return execute_import(session, plan, apply=apply)


def test_database_dry_run_never_inserts_or_flushes(connection):
    c = candidate()
    plan = ImportPlan([c], 1, 0)
    before = connection.scalar(select(func.count()).select_from(Company))
    result = run(connection, plan, apply=False)
    assert result["companies_to_insert"] == result["contacts_to_insert"] == 1
    assert result["inserted_companies"] == result["inserted_contacts"] == 0
    assert connection.scalar(select(func.count()).select_from(Company)) == before


def test_apply_is_idempotent_and_keeps_general_phones_unassigned(connection):
    c = candidate()
    c.contacts.append(ContactCandidate("Unclear / split", None, 8, ["ambiguous_contact_split"]))
    plan = ImportPlan([c], 1, 0)
    first = run(connection, plan)
    second = run(connection, plan)
    assert first["inserted_companies"] == first["inserted_contacts"] == 1
    assert second["inserted_companies"] == second["inserted_contacts"] == 0
    assert second["database_plan"] == {"already_present": 1}
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        company = session.scalar(select(Company).where(Company.company_name_key == c.key))
        assert company.general_phone_numbers == ["01234567890"]
        assert company.source_register_ids == c.source_ids
        assert company.city is None
        assert len(company.contacts) == 1
        assert company.contacts[0].phone_numbers == [] and company.contacts[0].designation is None


def test_manually_renamed_or_edited_company_and_contacts_are_never_overwritten(connection):
    c = candidate()
    plan = ImportPlan([c], 1, 0)
    first = run(connection, plan)
    company_id = first["company_actions"][0]["company_id"]
    with Session(connection, join_transaction_mode="create_savepoint") as session, session.begin():
        company = session.scalar(select(Company).where(Company.id == company_id))
        company.company_name = f"Manually Renamed {uuid4()}"
        company.city = "Manually entered city"
        company.general_phone_numbers = ["09999999999"]
        company.contacts[0].contact_name = "Manually edited contact"
    before = snapshot(connection, company_id)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(connection, "before_cursor_execute", capture)
    try:
        assert run(connection, plan)["database_plan"] == {"already_present": 1}
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert snapshot(connection, company_id) == before
    assert not {"UPDATE", "DELETE", "TRUNCATE", "INSERT"} & set(statements)


def snapshot(connection, company_id):
    company = connection.execute(select(Company.__table__).where(Company.id == company_id)).one()
    contacts = list(
        connection.execute(
            select(CompanyContact.__table__).where(CompanyContact.company_id == company_id)
        )
    )
    return company, contacts


def test_existing_name_conflict_never_attaches_source_ids_or_contacts(connection):
    c = candidate()
    with Session(connection, join_transaction_mode="create_savepoint") as session, session.begin():
        session.add(Company(company_name=c.name, city="Manual city"))
    result = run(connection, ImportPlan([c], 1, 0))
    assert result["database_plan"] == {"existing_name_conflict": 1}
    assert result["inserted_companies"] == result["inserted_contacts"] == 0
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        company = session.scalar(select(Company).where(Company.company_name_key == c.key))
        assert company.city == "Manual city" and company.source_register_ids == []
        assert company.contacts == []


def test_partial_source_ownership_is_not_silently_extended(connection):
    c = candidate(ids=[f"TEST-{uuid4()}", f"TEST-{uuid4()}"])
    with Session(connection, join_transaction_mode="create_savepoint") as session, session.begin():
        session.add(
            Company(company_name=f"Different {uuid4()}", source_register_ids=c.source_ids[:1])
        )
    result = run(connection, ImportPlan([c], 2, 0))
    assert result["database_plan"] == {"existing_source_conflict": 1}
    assert result["inserted_companies"] == 0


def test_any_insert_failure_rolls_back_the_whole_batch(connection):
    before = connection.scalar(select(func.count()).select_from(Company))

    def interrupt(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO COMPANIES"):
            raise RuntimeError("Simulated interruption after the database INSERT")

    event.listen(connection, "after_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError):
            run(connection, ImportPlan([candidate(), candidate()], 2, 0))
    finally:
        event.remove(connection, "after_cursor_execute", interrupt)
    assert connection.scalar(select(func.count()).select_from(Company)) == before
