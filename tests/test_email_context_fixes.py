"""Canonical interview context from disposable PostgreSQL, never live email."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_v12_postgres_backend import snapshot

from jobmitra.modules.ats_v2 import jobs, unified
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.ats_v2.schemas import JobCreate, MoveInput, WorkflowInput
from jobmitra.modules.email_studio import gmail_service

pytest_plugins = ["test_v12_creation_failures"]


@pytest.mark.parametrize("missing", ["[Company]", "[Candidate Name]", "[Interview Round]"])
def test_gmail_rejects_unresolved_context_before_mime_or_transport(missing):
    with pytest.raises(gmail_service.GmailError, match="missing contextual fields"):
        gmail_service.message(
            None, SimpleNamespace(subject=missing, plain="Draft", html="<p>Draft</p>"), "unused"
        )


def test_multiple_jds_custom_completion_and_company_recipient(office, pg_store):
    engine, first_company, contact, candidate, _ = pg_store[0]
    unified.edit_company(
        engine,
        first_company,
        unified.CompanyEdit(
            idempotency_key=uuid4(),
            actor_name="Synthetic fixture",
            contacts=[
                unified.ContactEmail(id=contact, email="hr@example.test", is_primary_email=True)
            ],
        ),
        "OFFICE_LAN",
    )
    second_company = str(uuid4())
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key,contacts_json) "
                "VALUES(:id,'Other Synthetic Company','other synthetic company','[]')"
            ),
            {"id": second_company},
        )
    jds = []
    for company in [first_company, second_company]:
        job = jobs.create_job(
            engine,
            JobCreate(
                company_id=company,
                title="Synthetic Role",
                target_date=unified.office_today(),
                status="ACTIVE",
            ),
            CompanyGateway(engine),
        )
        flow = jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(
                workflow_mode="CONFIGURED",
                workflow_version=0,
                rounds=[
                    {"round_name": "Portfolio Discussion", "mode": "VIDEO"},
                    {"round_name": "Owner Discussion", "mode": "FACE_TO_FACE"},
                ],
            ),
        )
        link = jobs.associate(engine, job["id"], candidate)
        for step in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION"]:
            jobs.move_candidate(engine, job["id"], link["id"], MoveInput(stage_code=step))
        for round in flow["rounds"]:
            jobs.move_candidate(
                engine, job["id"], link["id"], MoveInput(stage_code="ROUND", round_id=round["id"])
            )
        jds.append((job, flow))
    before = snapshot(engine)
    for (job, flow), company in zip(jds, [first_company, second_company], strict=True):
        facts = office.get(
            "/api/v12/email-context",
            params={
                "candidate_id": candidate,
                "job_id": job["id"],
                "selected_stage": "ROUND",
                "selected_round_id": flow["rounds"][0]["id"],
            },
        ).json()
        assert facts["company_id"] == company
        assert facts["company_name"] == (
            "Synthetic Client Company" if company == first_company else "Other Synthetic Company"
        )
        assert facts["candidate_name"] == "Synthetic Candidate"
        assert facts["round_name"] == "Portfolio Discussion" and facts["round_completed"]
        assert facts["next_round_name"] == "Owner Discussion"
    company_facts = unified.email_context(engine, candidate, jds[0][0]["id"], "COMPANY")
    assert company_facts["recipient_name"] == "Synthetic HR"
    assert company_facts["recipient_email"] == "hr@example.test"
    assert company_facts["candidate_name"] != company_facts["company_name"]
    assert snapshot(engine) == before
