"""Synthetic service contracts for independent JD, workflow and recruitment writes."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from jobmitra.modules.ats_v2 import jobs
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.database import build_ats_engine, initialize, transaction
from jobmitra.modules.ats_v2.schemas import (
    ActivityInput,
    FeedbackInput,
    JobCreate,
    JobPatch,
    MoveInput,
    RoundInput,
    WorkflowInput,
)


class CompanyGateway:
    """A controllable company-service boundary backed by a seeded local company."""

    def __init__(self):
        self.company_id = uuid4()
        self.calls = []
        self.unavailable = False

    def require(self, company_id):
        self.calls.append(company_id)
        if self.unavailable:
            raise AtsError("Company service unavailable.", 503)
        if company_id != self.company_id:
            raise AtsError("Company not found.", 422)
        return {"id": str(self.company_id), "company_name": "Synthetic Company"}


@pytest.fixture
def store(tmp_path):
    engine = build_ats_engine(tmp_path / "jobs.sqlite3")
    initialize(engine)
    gateway = CompanyGateway()
    with transaction(engine) as connection:
        connection.exec_driver_sql(
            "INSERT INTO companies(id,company_name,company_name_key) VALUES(?,?,?)",
            (str(gateway.company_id), "Synthetic Company", "synthetic company"),
        )
    try:
        yield engine, gateway
    finally:
        engine.dispose()


def make_job(store, **changes):
    engine, gateway = store
    values = {
        "company_id": gateway.company_id,
        "title": "Synthetic engineer",
        "target_date": date.today() + timedelta(days=30),
        "status": "ACTIVE",
    }
    values.update(changes)
    return jobs.create_job(engine, JobCreate(**values), gateway)


def make_candidate(engine, name="Synthetic Candidate"):
    with transaction(engine) as connection:
        return connection.execute(
            text("INSERT INTO candidates(full_name) VALUES(:name) RETURNING id"), {"name": name}
        ).scalar_one()


def make_link(store):
    engine, _ = store
    job = make_job(store)
    candidate_id = make_candidate(engine)
    link = jobs.associate(engine, job["id"], candidate_id)
    return job, candidate_id, link


def configure(engine, job_id, names=("Technical Interview", "Final Interview")):
    current = jobs.get_workflow(engine, job_id)
    return jobs.save_workflow(
        engine,
        job_id,
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=current["workflow_version"],
            rounds=[RoundInput(round_name=name) for name in names],
        ),
    )


def move(engine, job_id, link_id, stage_code, **values):
    return jobs.move_candidate(engine, job_id, link_id, MoveInput(stage_code=stage_code, **values))


def to_submission(engine, job_id, link_id):
    for stage in ("CONTACT", "SCREENING", "COMPANY_SUBMISSION"):
        move(engine, job_id, link_id, stage)


def events(engine, **scope):
    return jobs.history(engine, page_size=100, **scope)["items"]


def test_create_requires_real_company_boundary_and_stores_exact_uuid(store):
    engine, gateway = store
    job = make_job(store, vacancies=None, salary_min_inr=None)
    assert gateway.calls == [gateway.company_id]
    assert job["company_id"] == str(gateway.company_id)
    assert UUID(job["company_id"]) == gateway.company_id
    assert job["vacancies"] is None and job["salary_min_inr"] is None
    assert job["created_at"].endswith("Z")
    with engine.connect() as connection:
        assert (
            "companies"
            in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            .scalars()
            .all()
        )
    invalid = JobCreate(
        company_id=uuid4(), title="Invalid company", target_date=date.today() + timedelta(days=1)
    )
    with pytest.raises(AtsError, match="Company not found"):
        jobs.create_job(engine, invalid, gateway)
    gateway.unavailable = True
    with pytest.raises(AtsError) as failure:
        make_job(store)
    assert failure.value.status == 503
    assert jobs.list_jobs(engine)["total"] == 1


@pytest.mark.parametrize(
    "values",
    [
        {"company_id": "not-a-uuid"},
        {"title": " "},
        {"target_date": "2026-02-30"},
        {"experience_min": 5, "experience_max": 2},
        {"salary_min_inr": 100, "salary_max_inr": 50},
    ],
)
def test_job_contract_rejects_invalid_identity_dates_and_ranges(store, values):
    _, gateway = store
    defaults = {
        "company_id": gateway.company_id,
        "title": "Synthetic",
        "target_date": date.today() + timedelta(days=10),
    }
    with pytest.raises(ValidationError):
        JobCreate(**(defaults | values))


def test_edits_log_changed_fields_and_company_reassignment_validates_first(store):
    engine, gateway = store
    job = make_job(store, skills=["Python"])
    new_target = date.today() + timedelta(days=31)
    updated = jobs.update_job(
        engine, job["id"], JobPatch(title="Changed title", target_date=new_target), gateway
    )
    assert updated["title"] == "Changed title" and updated["target_date"] == str(new_target)
    change = next(e for e in events(engine, job_id=job["id"]) if e["event_type"] == "JD_UPDATED")
    assert change["before_json"] == {
        "title": "Synthetic engineer",
        "target_date": job["target_date"],
    }
    assert change["after_json"] == {"title": "Changed title", "target_date": str(new_target)}
    before = events(engine, job_id=job["id"])
    with pytest.raises(AtsError):
        jobs.update_job(engine, job["id"], JobPatch(company_id=uuid4(), title="Bad"), gateway)
    assert events(engine, job_id=job["id"]) == before
    assert jobs.get_job(engine, job["id"])["title"] == "Changed title"
    with pytest.raises(ValidationError):
        jobs.update_job(engine, job["id"], JobPatch(experience_min=5, experience_max=2), gateway)


@pytest.mark.parametrize(
    "status,target_offset,vacancies,joined,expected",
    [
        ("ACTIVE", -1, 1, 0, "OVERDUE"),
        ("ACTIVE", 0, None, 0, "DUE"),
        ("ACTIVE", 2, 1, 0, "DUE"),
        ("ACTIVE", 3, 1, 0, "TRACK"),
        ("DRAFT", -1, 1, 0, "NEUTRAL"),
        ("ON_HOLD", -1, 1, 0, "NEUTRAL"),
        ("CLOSED", -1, 1, 1, "CLOSED"),
        ("ACTIVE", -1, 1, 1, "FILLED"),
        ("ACTIVE", None, 1, 0, "UNSET"),
    ],
)
def test_deadline_rules_use_calendar_dates(status, target_offset, vacancies, joined, expected):
    today = date(2026, 11, 17)
    target = (
        (today + timedelta(days=target_offset)).isoformat() if target_offset is not None else None
    )
    assert (
        jobs.target_state(
            {
                "status": status,
                "target_date": target,
                "vacancies": vacancies,
                "joined_count": joined,
            },
            today,
        )
        == expected
    )


def test_dashboard_uses_india_midnight_and_real_joined_counts(store, monkeypatch):
    engine, _ = store

    class BoundaryTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 16, 18, 31, tzinfo=UTC)

    monkeypatch.setattr(jobs, "datetime", BoundaryTime)
    with transaction(engine) as connection:
        for index, (status, target) in enumerate(
            [
                ("ACTIVE", "2026-11-16"),
                ("ACTIVE", "2026-11-17"),
                ("ACTIVE", "2026-11-20"),
                ("DRAFT", "2026-11-16"),
                ("ON_HOLD", "2026-11-16"),
                ("CLOSED", "2026-11-16"),
            ]
        ):
            connection.execute(
                text(
                    "INSERT INTO job_descriptions(jd_code,company_id,title,target_date,"
                    "status,created_at) "
                    "VALUES(:code,:company,'Synthetic',:target,:status,'2026-01-01T00:00:00Z')"
                ),
                {
                    "code": str(index),
                    "company": str(store[1].company_id),
                    "target": target,
                    "status": status,
                },
            )
    report = jobs.list_jobs(engine)
    assert report["summary"] == {"active": 3, "overdue": 1, "due_soon": 1, "filled_closed": 1}
    overdue = next(j for j in report["items"] if j["jd_code"] == "0")
    assert overdue["days_remaining"] == -1
    assert jobs.list_jobs(engine, status="ACTIVE", page=2, page_size=2)["total"] == 3
    assert len(jobs.list_jobs(engine, status="ACTIVE", page=2, page_size=2)["items"]) == 1


def test_one_master_links_to_multiple_jds_and_conflicts_are_safe(store):
    engine, _ = store
    job, candidate_id, link = make_link(store)
    second = make_job(store)
    another = jobs.associate(engine, second["id"], candidate_id)
    assert another["candidate_id"] == link["candidate_id"] == candidate_id
    assert another["stage_code"] == link["stage_code"] == "POOL"
    with pytest.raises(AtsError) as failure:
        jobs.associate(engine, job["id"], candidate_id)
    assert failure.value.status == 409
    assert "View Existing JD Pool" in str(failure.value)
    with pytest.raises(AtsError):
        jobs.associate(engine, make_job(store, status="ON_HOLD")["id"], candidate_id)
    with pytest.raises(AtsError) as missing:
        jobs.associate(engine, job["id"], 999999)
    assert missing.value.status == 404
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM candidates")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM jd_candidates")).scalar_one() == 2


def test_workflow_preserves_ids_impact_and_old_snapshots_without_moving_candidates(store):
    engine, _ = store
    job, candidate_id, link = make_link(store)
    flow = configure(engine, job["id"])
    first, second = flow["rounds"]
    to_submission(engine, job["id"], link["id"])
    move(engine, job["id"], link["id"], "ROUND", round_id=first["id"])
    saved_stage = jobs.pipeline(engine, job["id"])["items"][0]
    revised = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=flow["workflow_version"],
            rounds=[
                RoundInput(id=second["id"], round_name="Final Renamed", mode="PHONE"),
                RoundInput(id=first["id"], round_name="Technical Renamed", mode="VIDEO"),
            ],
        ),
    )
    assert revised["workflow_version"] == flow["workflow_version"] + 1
    assert [r["id"] for r in revised["rounds"]] == [second["id"], first["id"]]
    current = jobs.pipeline(engine, job["id"])["items"][0]
    assert (current["stage_code"], current["round_id"]) == (
        saved_stage["stage_code"],
        saved_stage["round_id"],
    )
    assert next(i for i in revised["impact"] if i["round_id"] == first["id"])["candidates"] == 1
    entered = next(
        e
        for e in events(engine, candidate_id=candidate_id)
        if e["event_type"] == "MOVED" and e["to_stage"] == "ROUND"
    )
    assert entered["to_label_snapshot"] == "Technical Interview"
    with pytest.raises(AtsError, match="Reload") as stale:
        jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(workflow_mode="UNKNOWN", workflow_version=flow["workflow_version"]),
        )
    assert stale.value.status == 409
    with pytest.raises(AtsError, match="before retiring"):
        jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(
                workflow_mode="CONFIGURED",
                workflow_version=revised["workflow_version"],
                rounds=[
                    RoundInput(id=first["id"], round_name="Technical Renamed", is_active=False),
                    RoundInput(id=second["id"], round_name="Final Renamed"),
                ],
            ),
        )
    assert jobs.get_workflow(engine, job["id"])["workflow_version"] == revised["workflow_version"]
    assert jobs.pipeline(engine, job["id"])["counts"]["ROUND:" + first["id"]] == 1


def test_workflow_round_retirement_restore_and_omission_rules(store):
    engine, _ = store
    job = make_job(store)
    flow = configure(engine, job["id"], names=("Technical Interview",))
    round_id = flow["rounds"][0]["id"]
    with pytest.raises(AtsError, match="retire them instead"):
        jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(workflow_mode="DIRECT", workflow_version=flow["workflow_version"]),
        )
    retired = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="DIRECT",
            workflow_version=flow["workflow_version"],
            rounds=[RoundInput(id=round_id, round_name="Technical Interview", is_active=False)],
        ),
    )
    assert retired["rounds"][0]["retired_at"] is not None
    restored = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=retired["workflow_version"],
            rounds=[RoundInput(id=round_id, round_name="Technical Restored")],
        ),
    )
    assert restored["rounds"][0]["id"] == round_id
    assert restored["rounds"][0]["retired_at"] is None
    types = [e["event_type"] for e in events(engine, job_id=job["id"])]
    assert types.count("ROUND_RETIRED") == types.count("ROUND_RESTORED") == 1
    assert types.count("JD_WORKFLOW_UPDATED") == 3


def test_unknown_cannot_skip_fixed_stages_or_advance_unconfirmed_process(store):
    engine, _ = store
    job, _, link = make_link(store)
    with pytest.raises(AtsError, match="next configured stage"):
        move(engine, job["id"], link["id"], "SCREENING")
    assert jobs.pipeline(engine, job["id"])["items"][0]["stage_code"] == "POOL"
    to_submission(engine, job["id"], link["id"])
    assert jobs.pipeline(engine, job["id"])["items"][0]["next_stage"] is None
    with pytest.raises(AtsError):
        move(engine, job["id"], link["id"], "SELECTED")


def test_direct_selection_and_joining_are_separate_manual_actions(store):
    engine, _ = store
    job, _, link = make_link(store)
    jobs.save_workflow(engine, job["id"], WorkflowInput(workflow_mode="DIRECT", workflow_version=0))
    to_submission(engine, job["id"], link["id"])
    selected = move(engine, job["id"], link["id"], "SELECTED")
    assert selected["stage_code"] == "SELECTED"
    assert jobs.get_job(engine, job["id"])["joined_count"] == 0
    with pytest.raises(AtsError):
        move(engine, job["id"], link["id"], "NOT_SELECTED")
    move(engine, job["id"], link["id"], "JOINED")
    assert jobs.get_job(engine, job["id"])["joined_count"] == 1
    with pytest.raises(AtsError) as closed:
        move(engine, job["id"], link["id"], "CONTACT")
    assert closed.value.status == 409


def test_configured_round_progression_stale_clicks_and_round_scope(store):
    engine, _ = store
    job, _, link = make_link(store)
    flow = configure(engine, job["id"])
    first, second = flow["rounds"]
    to_submission(engine, job["id"], link["id"])
    with pytest.raises(AtsError):
        move(engine, job["id"], link["id"], "ROUND", round_id=second["id"])
    move(engine, job["id"], link["id"], "ROUND", round_id=first["id"])
    with pytest.raises(AtsError) as stale:
        move(
            engine,
            job["id"],
            link["id"],
            "ROUND",
            round_id=second["id"],
            expected_stage="COMPANY_SUBMISSION",
            workflow_version=flow["workflow_version"],
        )
    assert stale.value.status == 409
    with pytest.raises(AtsError) as stale_flow:
        move(engine, job["id"], link["id"], "ROUND", round_id=second["id"], workflow_version=0)
    assert stale_flow.value.status == 409
    move(engine, job["id"], link["id"], "ROUND", round_id=second["id"])
    move(engine, job["id"], link["id"], "SELECTED")
    assert jobs.pipeline(engine, job["id"])["counts"]["SELECTED"] == 1
    assert jobs.pipeline(engine, job["id"])["counts"]["JOINED"] == 0


def test_rejection_snapshot_feedback_and_history_scopes(store):
    engine, _ = store
    job, candidate_id, link = make_link(store)
    flow = configure(engine, job["id"], names=("Original Technical Name",))
    round_id = flow["rounds"][0]["id"]
    to_submission(engine, job["id"], link["id"])
    move(engine, job["id"], link["id"], "ROUND", round_id=round_id)
    result = move(
        engine,
        job["id"],
        link["id"],
        "NOT_SELECTED",
        feedback="Synthetic feedback",
        feedback_source="COMPANY",
    )
    assert result["rejected_from_stage"] == "ROUND"
    assert result["rejected_round_name"] == "Original Technical Name"
    assert result["rejected_round_index"] == 1
    assert result["rejected_at"].endswith("Z")
    jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=flow["workflow_version"],
            rounds=[RoundInput(id=round_id, round_name="Later Round Name")],
        ),
    )
    other = make_job(store)
    jobs.associate(engine, other["id"], candidate_id)
    scoped = events(engine, job_id=job["id"], jd_candidate_id=link["id"])
    feedback = [e for e in scoped if e["event_type"] == "FEEDBACK"]
    rejected = [e for e in scoped if e["event_type"] == "REJECTED"]
    assert len(feedback) == len(rejected) == 1
    assert feedback[0]["feedback"] == "Synthetic feedback"
    assert feedback[0]["from_label_snapshot"] == "Original Technical Name"
    assert rejected[0]["from_label_snapshot"] == "Original Technical Name"
    assert {e["job_id"] for e in scoped} == {job["id"]}
    all_history = events(engine, candidate_id=candidate_id)
    assert {e["job_id"] for e in all_history if e["job_id"]} == {job["id"], other["id"]}
    assert "CANDIDATE_CREATED" in {e["event_type"] for e in all_history}
    assert jobs.history(engine, job_id=job["id"], page_size=1)["total"] > 1
    assert len(jobs.history(engine, job_id=job["id"], page_size=1)["items"]) == 1


def test_stage_and_optional_feedback_roll_back_together_on_event_failure(store):
    engine, _ = store
    job, _, link = make_link(store)
    before = events(engine, job_id=job["id"])
    invalid = MoveInput.model_construct(
        stage_code="CONTACT", feedback="Must roll back", feedback_source="INVALID_SOURCE"
    )
    with pytest.raises(IntegrityError):
        jobs.move_candidate(engine, job["id"], link["id"], invalid)
    assert jobs.pipeline(engine, job["id"])["items"][0]["stage_code"] == "POOL"
    assert events(engine, job_id=job["id"]) == before
    jobs.feedback(engine, job["id"], link["id"], FeedbackInput(feedback="Standalone note"))
    assert jobs.pipeline(engine, job["id"])["items"][0]["stage_code"] == "POOL"
    assert len(events(engine, job_id=job["id"])) == len(before) + 1


def test_candidate_activities_are_scoped_versioned_and_use_utc(store):
    engine, _ = store
    job, candidate_id, _ = make_link(store)
    activity = jobs.save_activity(
        engine,
        candidate_id,
        ActivityInput(
            job_id=job["id"],
            activity_type="FOLLOW_UP",
            due_at="2026-11-20T10:00:00+05:30",
            notes="Synthetic follow-up",
        ),
    )
    assert activity["due_at"] == "2026-11-20T04:30:00Z"
    updated = jobs.save_activity(
        engine,
        candidate_id,
        ActivityInput(
            job_id=job["id"],
            activity_type="FOLLOW_UP",
            status="DONE",
            notes="Completed",
        ),
        activity_id=activity["id"],
    )
    assert updated["status"] == "DONE" and updated["due_at"] == activity["due_at"]
    assert len(jobs.activities(engine, candidate_id)) == 1
    history = events(engine, candidate_id=candidate_id)
    assert len([e for e in history if e["event_type"] == "ACTIVITY_CREATED"]) == 1
    changed = next(e for e in history if e["event_type"] == "ACTIVITY_UPDATED")
    assert changed["before_json"]["status"] == "OPEN"
    assert changed["after_json"]["status"] == "DONE"
    unrelated = make_candidate(engine, "Other Synthetic Candidate")
    with pytest.raises(AtsError):
        jobs.save_activity(engine, unrelated, ActivityInput(job_id=job["id"]))
    with pytest.raises(AtsError) as wrong_owner:
        jobs.save_activity(engine, unrelated, ActivityInput(), activity_id=activity["id"])
    assert wrong_owner.value.status == 404
    with pytest.raises(ValidationError):
        ActivityInput(due_at="2026-11-20T10:00:00")
