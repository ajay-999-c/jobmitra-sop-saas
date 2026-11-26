"""Atomic V12 sourcing on isolated PostgreSQL; legacy primitive stays Pool-first."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text

from jobmitra.modules.ats_v2 import jobs, unified
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.schemas import MoveInput

pytest_plugins = ["test_v12_creation_failures"]


def create_job(office, company):
    response = office.post(
        "/api/ats-v2/jobs",
        json={
            "company_id": company,
            "title": "Synthetic sourcing",
            "status": "ACTIVE",
            "target_date": unified.office_today().isoformat(),
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return response.json()["id"]


def events(engine, link):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT event_type,from_stage,to_stage FROM recruitment_events "
                "WHERE jd_candidate_id=:id ORDER BY id"
            ),
            {"id": link},
        ).all()


def test_attach_contact_is_atomic_retry_safe_and_never_resets(office, pg_store):
    engine, company, _, cid, _ = pg_store[0]
    jid = create_job(office, company)
    path = f"/api/v12/approved/jobs/{jid}/attach"
    key = str(uuid4())

    def attach(key):
        return office.post(path, json={"candidate_id": cid}, headers={"Idempotency-Key": key})

    first = attach(key)
    assert first.status_code == 201, first.text
    member = first.json()
    assert member["stage_code"] == "CONTACT"
    assert events(engine, member["id"]) == [("ADDED", None, "POOL"), ("MOVED", "POOL", "CONTACT")]
    assert attach(key).json()["id"] == member["id"]
    jobs.move_candidate(engine, jid, member["id"], MoveInput(stage_code="SCREENING"))
    history = events(engine, member["id"])
    assert attach(str(uuid4())).json()["stage_code"] == "SCREENING"
    assert attach(key).json()["stage_code"] == "SCREENING"
    assert events(engine, member["id"]) == history
    pipeline = jobs.pipeline(engine, jid)
    assert len(pipeline["items"]) == 1 and pipeline["counts"]["SCREENING"] == 1
    assert pipeline["counts"]["POOL"] == pipeline["counts"]["CONTACT"] == 0


def test_failed_initial_movement_rolls_back_membership_and_pool_event(office, pg_store):
    engine, company, _, cid, _ = pg_store[0]
    jid = create_job(office, company)
    with engine.connect() as conn:
        before = conn.scalar(text("SELECT count(*) FROM recruitment_events"))
    with patch.object(jobs, "move_candidate", side_effect=AtsError("Synthetic transition failure")):
        response = office.post(
            f"/api/v12/approved/jobs/{jid}/attach",
            json={"candidate_id": cid},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
    assert not jobs.pipeline(engine, jid)["items"]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM recruitment_events")) == before


def test_concurrent_attachment_creates_one_contact_membership(office, pg_store):
    engine, company, _, cid, _ = pg_store[0]
    jid = create_job(office, company)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: jobs.attach_contact(engine, jid, cid), range(4)))
    assert len({r["id"] for r in results}) == 1
    assert {r["stage_code"] for r in results} == {"CONTACT"}
    assert len(events(engine, results[0]["id"])) == 2
