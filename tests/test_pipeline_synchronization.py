"""Canonical attachment/progression on disposable PostgreSQL; no office writes."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text

from jobmitra.modules.ats_v2 import jobs, unified

pytest_plugins = ["test_v12_creation_failures"]


def post(client, path, body, key=None):
    return client.post(path, json=body, headers={"Idempotency-Key": key or str(uuid4())})


@pytest.mark.parametrize("mode", ["UNKNOWN", "DIRECT", "CONFIGURED"])
def test_both_attachment_entrypoints_preserve_pool_history_and_canonical_next_stage(
    office, pg_store, mode
):
    engine, company, _, cid, _ = pg_store[0]
    response = post(
        office,
        "/api/ats-v2/jobs",
        {
            "company_id": company,
            "title": "Synthetic pipeline synchronization",
            "status": "ACTIVE",
            "target_date": unified.office_today().isoformat(),
        },
    )
    assert response.status_code == 201
    jid = response.json()["id"]
    if mode != "UNKNOWN":
        flow = office.put(
            f"/api/ats-v2/jobs/{jid}/workflow",
            json={
                "workflow_mode": mode,
                "workflow_version": 0,
                "rounds": [{"round_name": "Custom panel"}] if mode == "CONFIGURED" else [],
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert flow.status_code == 200
    other = post(
        office,
        "/api/ats-v2/candidates",
        {"full_name": "Synthetic Desk Applicant", "email": "desk-sync@example.test"},
    )
    assert other.status_code == 201
    # Both frontend entry points call this same route and refresh approved/state.
    for candidate_id in [cid, other.json()["id"]]:
        path = f"/api/ats-v2/jobs/{jid}/candidates"
        key = str(uuid4())
        first = post(office, path, {"candidate_id": candidate_id}, key)
        retry = post(office, path, {"candidate_id": candidate_id}, key)
        assert first.status_code == retry.status_code == 201
        assert first.json()["id"] == retry.json()["id"]
        lid = first.json()["id"]
        assert post(office, path, {"candidate_id": candidate_id}).status_code == 409
        state = office.get("/api/v12/approved/state").json()
        job = next(j for j in state["jobs"] if j["id"] == jid)
        member = next(m for m in job["pipeline"]["items"] if m["id"] == lid)
        assert member["stage_code"] == "POOL" and member["next_stage"] == "CONTACT"
        attached = [e for e in state["events"] if e["jd_candidate_id"] == lid]
        assert len(attached) == 1 and attached[0]["event_type"] == "ADDED"
        assert (attached[0]["candidate_id"], attached[0]["job_id"]) == (candidate_id, jid)
        assert attached[0]["after"]["stage_code"] == "POOL"
        prior_event = attached[0]
        for destination in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION"]:
            result = post(
                office,
                f"{path}/{lid}/move",
                {"stage_code": destination, "expected_stage": member["stage_code"]},
            )
            assert result.status_code == 200
            member = next(
                m
                for m in office.get(f"/api/ats-v2/jobs/{jid}/pipeline").json()["items"]
                if m["id"] == lid
            )
            assert member["stage_code"] == destination
        assert (
            member["next_stage"]
            == {"UNKNOWN": None, "DIRECT": "SELECTED", "CONFIGURED": "ROUND"}[mode]
        )
        history = office.get("/api/ats-v2/history", params={"jd_candidate_id": lid}).json()
        assert (
            next(e for e in history["items"] if e["id"] == prior_event["id"])["after_json"]
            == prior_event["after_json"]
        )
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM jd_candidates WHERE job_id=:j AND candidate_id=:c"),
                    {"j": jid, "c": candidate_id},
                )
                == 1
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM recruitment_events "
                        "WHERE jd_candidate_id=:l AND event_type='ADDED'"
                    ),
                    {"l": lid},
                )
                == 1
            )


def test_attachment_and_audit_events_roll_back_if_receipt_cannot_commit(pg_store):
    engine, company, _, cid, _ = pg_store[0]
    from jobmitra.modules.ats_v2.companies import CompanyGateway
    from jobmitra.modules.ats_v2.schemas import JobCreate

    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Atomic attach",
            status="ACTIVE",
            target_date=unified.office_today(),
        ),
        CompanyGateway(engine),
    )
    with patch.object(jobs.receipts, "record", side_effect=RuntimeError("Receipt failure")):
        with pytest.raises(RuntimeError, match="Receipt failure"):
            jobs.associate(engine, job["id"], cid)
    with engine.connect() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM jd_candidates WHERE job_id=:j"), {"j": job["id"]}
            )
            == 0
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM recruitment_events "
                    "WHERE job_id=:j AND jd_candidate_id IS NOT NULL"
                ),
                {"j": job["id"]},
            )
            == 0
        )
