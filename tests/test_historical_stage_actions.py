"""Stage-targeted email/feedback on disposable SQLite and PostgreSQL only."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_unified_v12 import store, v2  # noqa: F401

from jobmitra.modules.ats_v2 import jobs, request_receipts, unified
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.schemas import FeedbackInput, JobCreate, MoveInput, WorkflowInput

pytest_plugins = ["test_v12_creation_failures"]


@pytest.fixture(params=["sqlite", "postgresql"])
def history_store(request):
    return (
        request.getfixturevalue("store")
        if request.param == "sqlite"
        else request.getfixturevalue("pg_store")[0]
    )


def setup(fixture_store, stage="SCREENING"):
    engine, company, _, candidate, _ = fixture_store
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Historical stage test",
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
            rounds=[{"round_name": "Interview Round 1"}, {"round_name": "Interview Round 2"}],
        ),
    )
    link = jobs.associate(engine, job["id"], candidate)
    for target in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION", "ROUND"]:
        jobs.move_candidate(
            engine,
            job["id"],
            link["id"],
            MoveInput(
                stage_code=target, round_id=flow["rounds"][0]["id"] if target == "ROUND" else None
            ),
        )
        if target == stage:
            break
    return job["id"], link["id"], candidate, flow


def evidence(engine, jid, lid):
    with engine.connect() as conn:
        link = dict(
            conn.execute(text("SELECT * FROM jd_candidates WHERE id=:id"), {"id": lid})
            .mappings()
            .one()
        )
        events = {
            r["id"]: dict(r)
            for r in conn.execute(
                text("SELECT * FROM recruitment_events WHERE job_id=:id"), {"id": jid}
            ).mappings()
        }
    return link, events


def test_historical_feedback_is_append_only_correctly_targeted_and_retry_safe(history_store):
    engine = history_store[0]
    jid, lid, cid, _ = setup(history_store)
    before, events = evidence(engine, jid, lid)
    key = request_receipts.request_key.set(str(uuid4()))
    try:
        for _ in range(2):
            jobs.feedback(
                engine,
                jid,
                lid,
                FeedbackInput(
                    stage_code="CONTACT",
                    feedback="Historical Contact feedback",
                    feedback_source="CANDIDATE",
                ),
            )
    finally:
        request_receipts.request_key.reset(key)
    after, records = evidence(engine, jid, lid)
    assert before == after
    assert all(records[k] == value for k, value in events.items())
    added = [r for k, r in records.items() if k not in events and r["event_type"] == "FEEDBACK"]
    assert len(added) == 1
    row = added[0]
    assert (row["candidate_id"], row["jd_candidate_id"]) == (cid, lid)
    assert row["from_stage"] == row["to_stage"] == "CONTACT"
    assert row["to_label_snapshot"] == "Candidate Contact"
    assert json.loads(row["payload_json"])["feedback_stage"] == {
        "stage_code": "CONTACT",
        "round_id": None,
        "label": "Candidate Contact",
        "historical": True,
    }


def test_unreached_and_foreign_rounds_are_rejected_without_any_changes(history_store):
    engine = history_store[0]
    jid, lid, cid, flow = setup(history_store)
    before = evidence(engine, jid, lid)
    for data in [
        FeedbackInput(stage_code="JOINED", feedback="Invalid future outcome"),
        FeedbackInput(
            stage_code="ROUND",
            round_id=flow["rounds"][0]["id"],
            feedback="Interview not yet reached",
        ),
        FeedbackInput(stage_code="ROUND", round_id="another-jd-round", feedback="Wrong JD round"),
        FeedbackInput(
            stage_code="CONTACT",
            round_id=flow["rounds"][0]["id"],
            feedback="Wrong stage/round pair",
        ),
    ]:
        with pytest.raises(AtsError):
            jobs.feedback(engine, jid, lid, data)
    with pytest.raises(AtsError):
        unified.email_context(
            engine,
            cid,
            jid,
            "CANDIDATE",
            selected_stage="ROUND",
            selected_round_id=flow["rounds"][0]["id"],
        )
    assert evidence(engine, jid, lid) == before


def test_email_keeps_selected_contact_submission_and_round_context(history_store):
    engine = history_store[0]
    jid, lid, cid, flow = setup(history_store, "ROUND")
    jobs.move_candidate(
        engine, jid, lid, MoveInput(stage_code="ROUND", round_id=flow["rounds"][1]["id"])
    )
    before = evidence(engine, jid, lid)
    for stage, rid, audience in [
        ("CONTACT", None, "CANDIDATE"),
        ("COMPANY_SUBMISSION", None, "COMPANY"),
        ("ROUND", flow["rounds"][0]["id"], "CANDIDATE"),
    ]:
        result = unified.email_context(
            engine, cid, jid, audience, selected_stage=stage, selected_round_id=rid
        )
        assert (result["stage"], result["round_id"]) == (stage, rid)
        assert result["current_stage"] == "ROUND"
        assert result["current_round_id"] == flow["rounds"][1]["id"]
        assert result["historical_context"] and not result["delivery_enabled"]
        assert result["company_disclosed"] == (audience == "COMPANY")
    jobs.feedback(
        engine,
        jid,
        lid,
        FeedbackInput(
            stage_code="ROUND",
            round_id=flow["rounds"][0]["id"],
            feedback="Round 1 historical feedback",
        ),
    )
    after, rows = evidence(engine, jid, lid)
    assert before[0] == after
    target = next(r for r in rows.values() if r["feedback"] == "Round 1 historical feedback")
    assert (
        json.loads(target["payload_json"])["feedback_stage"]["round_id"] == flow["rounds"][0]["id"]
    )


def test_office_api_validates_stage_and_keeps_legacy_feedback_contract(office, pg_store):
    jid, lid, cid, _ = setup(pg_store[0])
    before = evidence(pg_store[0][0], jid, lid)
    facts = office.get(
        "/api/v12/email-context",
        params={"candidate_id": cid, "job_id": jid, "selected_stage": "CONTACT"},
    ).json()
    assert facts["stage"] == "CONTACT" and facts["current_stage"] == "SCREENING"
    path = f"/api/ats-v2/jobs/{jid}/candidates/{lid}/feedback"
    for body in [
        {"feedback": "Legacy current feedback"},
        {"feedback": "Historical API feedback", "stage_code": "CONTACT"},
    ]:
        assert (
            office.post(path, json=body, headers={"Idempotency-Key": str(uuid4())}).status_code
            == 200
        )
    link, events = evidence(pg_store[0][0], jid, lid)
    assert link == before[0]
    labels = {e["feedback"]: e["to_stage"] for e in events.values() if e["feedback"]}
    assert labels["Legacy current feedback"] == "SCREENING"
    assert labels["Historical API feedback"] == "CONTACT"
    assert (
        office.post(
            path,
            json={"feedback": "No future joining", "stage_code": "JOINED"},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 409
    )
