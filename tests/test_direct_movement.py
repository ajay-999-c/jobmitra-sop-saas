"""Direct progress uses real canonical events on disposable SQLite/PostgreSQL."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
import test_unified_v12 as fixtures
from pydantic import ValidationError
from sqlalchemy import text

from jobmitra.modules.ats_v2 import direct_movement as direct
from jobmitra.modules.ats_v2 import jobs, unified
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.schemas import JobCreate, MoveInput, WorkflowInput

pytest_plugins = ["test_v12_creation_failures"]
v2, store = fixtures.v2, fixtures.store


@pytest.fixture(params=["sqlite", "postgresql"])
def progress(request):
    source = (
        request.getfixturevalue("store")
        if request.param == "sqlite"
        else request.getfixturevalue("pg_store")[0]
    )
    engine, company, _, candidate, _ = source
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Direct movement fixture",
            status="ACTIVE",
            target_date=unified.office_today(),
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
                {"round_name": n} for n in ["Portfolio Check", "Custom Panel", "Owner Discussion"]
            ],
        ),
    )
    link = jobs.attach_contact(engine, job["id"], candidate)
    return engine, job["id"], link["id"], flow


def data_for(progress, code="ROUND", round_index=0, **extra):
    engine, job, link, flow = progress
    facts = direct.choices(engine, job, link)
    return direct.DirectMove(
        idempotency_key=uuid4(),
        destination_stage=code,
        destination_round_id=flow["rounds"][round_index]["id"] if code == "ROUND" else None,
        expected_stage=facts["current_stage"],
        expected_round_id=facts["current_round_id"],
        workflow_version=facts["workflow_version"],
        **extra,
    )


def snapshot(progress):
    engine = progress[0]
    with engine.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT * FROM {t} ORDER BY id")).all()
            for t in ["candidates", "jd_candidates", "recruitment_events", "candidate_activities"]
        }


def test_contact_to_first_round_records_all_normal_completions_and_replays(progress):
    engine, job, link, flow = progress
    data = data_for(progress)
    result = direct.move(engine, job, link, data, "OFFICE_LAN")
    assert (result["stage_code"], result["round_id"]) == ("ROUND", flow["rounds"][0]["id"])
    before = snapshot(progress)
    direct.move(engine, job, link, data, "OFFICE_LAN")
    assert snapshot(progress) == before
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT event_type,from_stage,to_stage,payload_json FROM "
                "recruitment_events WHERE jd_candidate_id=:id ORDER BY id"
            ),
            {"id": link},
        ).all()
        assert [(r[1], r[2]) for r in rows if r[0] == "MOVED"] == [
            ("POOL", "CONTACT"),
            ("CONTACT", "SCREENING"),
            ("SCREENING", "COMPANY_SUBMISSION"),
            ("COMPANY_SUBMISSION", "ROUND"),
        ]
        receipt = json.loads(
            conn.scalar(
                text(
                    "SELECT payload_json FROM recruitment_events WHERE "
                    "json_extract(payload_json,'$.idempotency_key')=:key"
                ),
                {"key": str(data.idempotency_key)},
            )
        )
        audit = receipt["details"]
        assert [x["stage_code"] for x in audit["completed_stages"]] == [
            "CONTACT",
            "SCREENING",
            "COMPANY_SUBMISSION",
        ]
        assert audit["employee_id"] is None and not audit["individual_authenticated"]
        assert audit["recorded_at"] and audit["manual_stage_confirmation"]
        assert conn.scalar(text("SELECT count(*) FROM candidate_activities")) == 0
        assert not any(
            r[0] in {"FEEDBACK", "EMAIL_SEND_ATTEMPT", "INTERVIEW_SCHEDULED"} for r in rows
        )
    counts = jobs.pipeline(engine, job)["counts"]
    assert counts["ROUND:" + flow["rounds"][0]["id"]] == 1 and counts["CONTACT"] == 0
    assert unified.email_context(
        engine, result["candidate_id"], job, "CANDIDATE", selected_stage="SCREENING"
    )["historical_context"]


def test_multiple_custom_rounds_completed_without_duplicates(progress):
    engine, job, link, flow = progress
    direct.move(engine, job, link, data_for(progress, round_index=2), "LOCAL_DEVELOPMENT")
    history = jobs.history(engine, jd_candidate_id=link)["items"]
    rounds = [
        e["after_json"]["round_id"]
        for e in history
        if e["event_type"] == "MOVED" and e["to_stage"] == "ROUND"
    ]
    assert len(rounds) == len(set(rounds)) == 3
    for round in flow["rounds"]:
        assert (
            unified.email_context(
                engine,
                history[0]["candidate_id"],
                job,
                "CANDIDATE",
                selected_stage="ROUND",
                selected_round_id=round["id"],
            )["round_id"]
            == round["id"]
        )


@pytest.mark.parametrize(
    "kind", ["backward", "wrong_round", "workflow", "stage", "joining", "future", "reversed_dates"]
)
def test_invalid_or_incomplete_action_leaves_all_records_unchanged(progress, kind):
    engine, job, link, _ = progress
    if kind == "backward":
        data = data_for(progress, "CONTACT")
    elif kind == "wrong_round":
        data = data_for(progress).model_copy(update={"destination_round_id": str(uuid4())})
    elif kind == "workflow":
        data = data_for(progress).model_copy(update={"workflow_version": 999})
    elif kind == "stage":
        data = data_for(progress).model_copy(update={"expected_stage": "POOL"})
    elif kind == "joining":
        data = data_for(progress, "JOINED")
    elif kind == "future":
        data = data_for(
            progress, "SELECTED", selected_on=unified.office_today() + timedelta(days=1)
        )
    else:
        data = data_for(
            progress,
            "JOINED",
            selected_on=unified.office_today(),
            joined_on=unified.office_today() - timedelta(days=1),
            confirmation_evidence="Synthetic evidence",
        )
    before = snapshot(progress)
    with pytest.raises((AtsError, ValidationError)):
        direct.move(engine, job, link, data, "OFFICE_LAN")
    assert snapshot(progress) == before


def test_actual_selection_joining_and_terminal_locks_remain_enforced(progress):
    engine, job, link, _ = progress
    data = data_for(
        progress,
        "JOINED",
        selected_on=unified.office_today() - timedelta(days=2),
        joined_on=unified.office_today() - timedelta(days=1),
        confirmation_evidence="Synthetic joining confirmation",
    )
    result = direct.move(engine, job, link, data, "OFFICE_LAN")
    assert result["selection_outcome"] == "JOINED_CONFIRMED"
    assert (
        result["selected_on"] == data.selected_on.isoformat()
        and result["joined_on"] == data.joined_on.isoformat()
    )
    assert direct.choices(engine, job, link)["destinations"] == []
    with engine.connect() as conn:
        assert not unified.eligibility(conn, result["candidate_id"])["can_allocate"]
    before = snapshot(progress)
    with pytest.raises(AtsError):
        direct.move(engine, job, link, data_for(progress, "SCREENING"), "OFFICE_LAN")
    assert snapshot(progress) == before


def test_intermediate_failure_rolls_back_every_completed_step(progress):
    engine, job, link, _ = progress
    before = snapshot(progress)
    move = jobs.move_candidate
    calls = 0

    def fail(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AtsError("Synthetic intermediate failure")
        return move(*args)

    with patch.object(jobs, "move_candidate", side_effect=fail), pytest.raises(AtsError):
        direct.move(engine, job, link, data_for(progress), "OFFICE_LAN")
    assert snapshot(progress) == before


def test_concurrent_same_key_completes_each_stage_once(progress):
    engine, job, link, _ = progress
    data = data_for(progress, round_index=2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        result = list(
            pool.map(lambda _: direct.move(engine, job, link, data, "OFFICE_LAN"), range(3))
        )
    assert len({r["round_id"] for r in result}) == 1
    history = jobs.history(engine, jd_candidate_id=link)["items"]
    assert len([r for r in history if r["event_type"] == "MOVED"]) == 6


def test_rejection_cannot_reopen(progress):
    engine, job, link, flow = progress
    jobs.move_candidate(engine, job, link, MoveInput(stage_code="NOT_SELECTED"))
    assert direct.choices(engine, job, link)["destinations"] == []
    before = snapshot(progress)
    with pytest.raises(AtsError):
        direct.move(engine, job, link, data_for(progress), "OFFICE_LAN")
    assert snapshot(progress) == before


def test_another_placement_blocks_direct_selection(progress):
    engine, job, link, _ = progress
    with engine.connect() as conn:
        original = jobs.linked(conn, job, link)
        company = conn.scalar(
            text("SELECT company_id FROM job_descriptions WHERE id=:id"), {"id": job}
        )
    other = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Other synthetic requirement",
            status="ACTIVE",
            target_date=unified.office_today(),
        ),
        CompanyGateway(engine),
    )
    flow = jobs.save_workflow(
        engine, other["id"], WorkflowInput(workflow_mode="DIRECT", workflow_version=0, rounds=[])
    )
    member = jobs.attach_contact(engine, other["id"], original["candidate_id"])
    other_progress = (engine, other["id"], member["id"], flow)
    direct.move(
        engine,
        other["id"],
        member["id"],
        data_for(
            other_progress,
            "JOINED",
            selected_on=unified.office_today(),
            joined_on=unified.office_today(),
            confirmation_evidence="Synthetic joining evidence",
        ),
        "OFFICE_LAN",
    )
    assert not any(
        d["stage_code"] in {"SELECTED", "JOINED"}
        for d in direct.choices(engine, job, link)["destinations"]
    )
    before = snapshot(progress)
    with pytest.raises(AtsError):
        direct.move(
            engine,
            job,
            link,
            data_for(progress, "SELECTED", selected_on=unified.office_today()),
            "OFFICE_LAN",
        )
    assert snapshot(progress) == before


def test_unconfirmed_workflow_does_not_invent_interview_or_selection_destinations(progress):
    engine, job, link, _ = progress
    with engine.connect() as conn:
        original = jobs.linked(conn, job, link)
        company = conn.scalar(
            text("SELECT company_id FROM job_descriptions WHERE id=:id"), {"id": job}
        )
    unknown = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Unconfirmed synthetic workflow",
            status="ACTIVE",
            target_date=unified.office_today(),
        ),
        CompanyGateway(engine),
    )
    member = jobs.attach_contact(engine, unknown["id"], original["candidate_id"])
    choices = direct.choices(engine, unknown["id"], member["id"])
    assert [d["stage_code"] for d in choices["destinations"]] == ["SCREENING", "COMPANY_SUBMISSION"]
    before = snapshot(progress)
    data = data_for(
        (engine, unknown["id"], member["id"], None), "SELECTED", selected_on=unified.office_today()
    )
    with pytest.raises(AtsError):
        direct.move(engine, unknown["id"], member["id"], data, "OFFICE_LAN")
    assert snapshot(progress) == before


def test_http_direct_move_validates_header_scope_and_idempotency(office, pg_store):
    engine, company, _, cid, _ = pg_store[0]
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="HTTP synthetic movement",
            status="ACTIVE",
            target_date=unified.office_today(),
        ),
        CompanyGateway(engine),
    )
    flow = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=0,
            rounds=[{"round_name": "Dynamic custom panel"}],
        ),
    )
    link = jobs.attach_contact(engine, job["id"], cid)
    url = f"/api/v12/approved/jobs/{job['id']}/candidates/{link['id']}"
    assert office.get(url + "/destinations").json()["current_stage"] == "CONTACT"
    data = data_for((engine, job["id"], link["id"], flow))
    body = data.model_dump(mode="json")
    assert (
        office.post(
            url + "/advance-to", json=body, headers={"Idempotency-Key": str(uuid4())}
        ).status_code
        == 422
    )
    headers = {"Idempotency-Key": str(data.idempotency_key)}
    first = office.post(url + "/advance-to", json=body, headers=headers)
    assert first.status_code == 200, first.text
    before = snapshot((engine,))
    assert office.post(url + "/advance-to", json=body, headers=headers).status_code == 200
    assert snapshot((engine,)) == before
