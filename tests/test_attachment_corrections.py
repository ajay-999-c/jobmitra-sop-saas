"""Correction ledger rehearsal on disposable remote schemas, never office records."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from jobmitra.modules.ats_v2 import attachment_corrections as correction
from jobmitra.modules.ats_v2 import candidates, jobs
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.schemas import FeedbackInput, JobCreate

pytest_plugins = ["test_workspace_employees"]


def fixture(office_workspace):
    engine, _, company, *_ = office_workspace
    c = candidates.create_candidate(engine, CandidateCreate(full_name="Correction fixture"))
    j = jobs.create_job(
        engine,
        JobCreate(company_id=company, title="Correction fixture", target_date="2099-01-01"),
        CompanyGateway(engine),
    )
    link = jobs.attach_contact(engine, j["id"], c["id"])
    return engine, j["id"], link, c


def action(engine, job, link, kind="REMOVE", **kw):
    with engine.connect() as conn:
        facts = correction.facts(conn, job, link)
    return correction.Correction(
        idempotency_key=uuid4(),
        expected_revision=facts["revision"],
        action=kind,
        reason="Synthetic accidental attachment correction",
        **kw,
    )


def test_reversible_ledger_replay_preserves_membership_and_master(office_workspace):
    engine, job, link, c = fixture(office_workspace)
    data = action(engine, job, link["id"])
    result = correction.correct(engine, job, link["id"], data, "OFFICE_LAN")
    assert result["removed"]
    assert jobs.pipeline(engine, job)["items"] == []
    assert jobs.pipeline(engine, job)["removed_items"][0]["id"] == link["id"]
    assert jobs.get_job(engine, job)["candidate_count"] == 0
    assert candidates.get_candidate(engine, c["id"])["participation"][0]["attachment_removed"]
    with engine.connect() as conn, pytest.raises(AtsError, match="removed"):
        jobs.linked(conn, job, link["id"])
    assert correction.correct(engine, job, link["id"], data, "OFFICE_LAN")["removed"]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidates WHERE id=:c"), {"c": c["id"]}) == 1
        assert (
            conn.scalar(text("SELECT stage_code FROM jd_candidates WHERE id=:l"), {"l": link["id"]})
            == "CONTACT"
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM recruitment_events WHERE jd_candidate_id=:l "
                    "AND event_type='ATTACHMENT_REMOVED'"
                ),
                {"l": link["id"]},
            )
            == 1
        )
    assert not correction.correct(
        engine, job, link["id"], action(engine, job, link["id"], "RESTORE"), "OFFICE_LAN"
    )["removed"]


def test_feedback_and_stale_action_fail_closed(office_workspace):
    engine, job, link, _ = fixture(office_workspace)
    data = action(engine, job, link["id"])
    jobs.feedback(engine, job, link["id"], FeedbackInput(feedback="Genuine screening feedback"))
    with pytest.raises(AtsError, match="Participation changed"):
        correction.correct(engine, job, link["id"], data, "OFFICE_LAN")
    with pytest.raises(AtsError, match="Recruitment activity exists"):
        correction.correct(engine, job, link["id"], action(engine, job, link["id"]), "OFFICE_LAN")


def test_explicit_closure_stale_guard_and_history_preservation(office_workspace):
    engine, job, link, candidate = fixture(office_workspace)
    current = jobs.get_job(engine, job)
    data = correction.CloseJD(
        idempotency_key=uuid4(),
        expected_revision=current["revision"],
        reason="Synthetic completed requirement",
        confirmed=True,
    )
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT * FROM jd_candidates WHERE id=:l"), {"l": link["id"]}
        ).first()
    assert correction.close_job(engine, job, data, "OFFICE_LAN")["status"] == "CLOSED"
    assert correction.close_job(engine, job, data, "OFFICE_LAN")["replayed"]
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT * FROM jd_candidates WHERE id=:l"), {"l": link["id"]}).first()
            == before
        )
        assert (
            conn.scalar(text("SELECT count(*) FROM candidates WHERE id=:c"), {"c": candidate["id"]})
            == 1
        )
    assert jobs.history(engine, job_id=job)["items"]
    with pytest.raises(AtsError, match="changed"):
        correction.close_job(
            engine, job, data.model_copy(update={"idempotency_key": uuid4()}), "OFFICE_LAN"
        )


def test_selected_jd_read_is_scoped_and_revision_changes(office_workspace):
    from jobmitra.modules.ats_v2 import approved

    engine, job, link, candidate = fixture(office_workspace)
    before = approved.state(engine, job)
    assert [j["id"] for j in before["jobs"]] == [job]
    assert [c["id"] for c in before["candidates"]] == [candidate["id"]]
    assert all(e["job_id"] == job for e in before["events"])
    assert before["resumes"] == []
    jobs.feedback(engine, job, link["id"], FeedbackInput(feedback="Scoped refresh fixture"))
    after = approved.state(engine, job)
    assert len(after["events"]) > len(before["events"])


def test_scoped_route_etag_and_poll_configuration(office_workspace, monkeypatch):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    monkeypatch.setenv("JOBMITRA_GMAIL_ENABLED", "false")
    from jobmitra.main import create_app

    engine, legacy, _, config, staff_schema = office_workspace
    _, job, _, _ = fixture(office_workspace)
    config = config.model_copy(
        update={
            "gmail_enabled": False,
            "office_lan_enabled": True,
            "office_lan_cidrs": "127.0.0.0/8",
            "office_lan_hosts": "",
            "jd_poll_seconds": 17,
        }
    )
    with (
        patch("jobmitra.main.build_engine", return_value=legacy),
        patch("jobmitra.modules.ats_v2.postgres.build_postgres_engine", return_value=engine),
    ):
        app = create_app(config)
        app.state.staff_schema = staff_schema
        with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5500)) as client:
            path = f"/api/v12/approved/jobs/{job}/state"
            result = client.get(path)
            assert result.status_code == 200
            assert result.json()["poll_seconds"] == 17
            unchanged = client.get(path, headers={"If-None-Match": result.headers["ETag"]})
            assert unchanged.status_code == 304 and not unchanged.content
