"""Email drafts on disposable PostgreSQL; no legacy or office record writes."""

from uuid import uuid4

import pytest
from test_v12_postgres_backend import snapshot

from jobmitra.modules.ats_v2 import candidates, jobs, unified
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.schemas import JobCreate, MoveInput, WorkflowInput

pytest_plugins = ["test_v12_creation_failures"]
STAGES = ["POOL", "CONTACT", "SCREENING", "COMPANY_SUBMISSION", "ROUND", "SELECTED", "JOINED"]


def fixture_job(
    engine, company, candidate, label, stage, confirmed=True, round_name="Client Discussion"
):
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company, title=label, target_date=unified.office_today(), status="ACTIVE"
        ),
        CompanyGateway(engine),
    )
    if confirmed:
        flow = jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(
                workflow_mode="CONFIGURED",
                workflow_version=0,
                rounds=[{"round_name": round_name, "mode": "VIDEO"}],
            ),
        )
    link = jobs.associate(engine, job["id"], candidate)
    for step in STAGES[1 : STAGES.index(stage) + 1]:
        if step in {"SELECTED", "JOINED"}:
            unified.outcome(
                engine,
                job["id"],
                link["id"],
                unified.Action(
                    action="SELECT" if step == "SELECTED" else "JOIN",
                    idempotency_key=uuid4(),
                    actor_name="Synthetic Office fixture",
                    effective_on=unified.office_today(),
                    confirmation_evidence="Synthetic joining confirmation",
                ),
                "OFFICE_LAN",
            )
        else:
            jobs.move_candidate(
                engine,
                job["id"],
                link["id"],
                MoveInput(
                    stage_code=step,
                    round_id=flow["rounds"][0]["id"] if step == "ROUND" else None,
                ),
            )
    return job["id"]


@pytest.mark.parametrize("stage", STAGES)
def test_existing_and_new_memberships_have_correct_read_only_email_context(office, pg_store, stage):
    engine, company, contact, existing, _ = pg_store[0]
    unified.edit_company(
        engine,
        company,
        unified.CompanyEdit(
            idempotency_key=uuid4(),
            actor_name="Synthetic Office fixture",
            contacts=[
                unified.ContactEmail(id=contact, email="hr@example.test", is_primary_email=True)
            ],
        ),
        "OFFICE_LAN",
    )
    new = candidates.create_candidate(engine, CandidateCreate(full_name="New Email Fixture"))["id"]
    fixtures = [
        (fixture_job(engine, company, existing, "Existing Email JD", stage), existing),
        (fixture_job(engine, company, new, "New Email JD", stage), new),
    ]
    before = snapshot(engine)
    assert office.get("/api/v12/access").json()["office_lan"] is True
    for jid, cid in fixtures:
        for audience in ("CANDIDATE", "COMPANY"):
            response = office.get(
                "/api/v12/email-context",
                params={
                    "candidate_id": cid,
                    "job_id": jid,
                    "audience": audience,
                },
            )
            assert response.status_code == 200, response.text
            facts = response.json()
            assert facts["stage"] == stage
            assert (facts["candidate_id"], facts["job_id"]) == (cid, jid)
            assert facts["candidate_name"] == candidates.get_candidate(engine, cid)["full_name"]
            assert facts["job_title"] == jobs.get_job(engine, jid)["title"]
            expected = (
                "hr@example.test"
                if audience == "COMPANY"
                else ("candidate@example.test" if cid == existing else None)
            )
            assert facts["recipient_email"] == expected
            assert facts["company_disclosed"] == (
                audience == "COMPANY" or stage in {"ROUND", "SELECTED", "JOINED"}
            )
            assert facts["company_name"] == (
                "Synthetic Client Company" if facts["company_disclosed"] else None
            )
            assert facts["round_name"] == ("Client Discussion" if stage == "ROUND" else None)
            assert bool(facts["round_id"]) == (stage == "ROUND")
            assert facts["sent"] is False and facts["delivery_enabled"] is False
    assert (
        office.get(
            "/api/v12/email-context",
            params={
                "candidate_id": existing,
                "job_id": fixtures[1][0],
            },
        ).status_code
        == 404
    )
    assert snapshot(engine) == before


def test_unconfirmed_workflow_and_no_candidate_email_can_open_context(office, pg_store):
    engine, company, _, _, _ = pg_store[0]
    cid = candidates.create_candidate(engine, CandidateCreate(full_name="No Email Fixture"))["id"]
    jid = fixture_job(engine, company, cid, "Unconfirmed Email JD", "SCREENING", confirmed=False)
    before = snapshot(engine)
    response = office.get("/api/v12/email-context", params={"candidate_id": cid, "job_id": jid})
    assert response.status_code == 200
    assert response.json()["stage"] == "SCREENING" and response.json()["recipient_email"] is None
    assert jobs.get_job(engine, jid)["workflow_version"] == 0
    assert snapshot(engine) == before


def test_interview_round_discloses_canonical_company_without_changing_source(office, pg_store):
    engine, company, _, cid, _ = pg_store[0]
    original = "Synthetic Client Company Discussion"
    jid = fixture_job(engine, company, cid, "Round Email JD", "ROUND", round_name=original)
    before = snapshot(engine)
    for audience, expected in [
        ("CANDIDATE", original),
        ("COMPANY", original),
    ]:
        response = office.get(
            "/api/v12/email-context",
            params={"candidate_id": cid, "job_id": jid, "audience": audience},
        )
        assert response.status_code == 200
        assert response.json()["round_name"] == expected
    assert jobs.get_workflow(engine, jid)["rounds"][0]["round_name"] == original
    assert snapshot(engine) == before
