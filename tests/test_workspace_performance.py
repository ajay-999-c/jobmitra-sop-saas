"""Batch projections must match canonical individual reads on remote test schemas."""

from uuid import uuid4

from sqlalchemy import event
from test_attachment_corrections import fixture

from jobmitra.modules.ats_v2 import direct_movement, jobs, unified
from jobmitra.modules.ats_v2.schemas import WorkflowInput

pytest_plugins = ["test_workspace_employees"]


def test_batch_requirements_match_individual_canonical_reads(office_workspace):
    engine, job, _, _ = fixture(office_workspace)
    with engine.connect() as conn:
        batched = jobs.batch_requirements(conn)
    for item in batched:
        expected = jobs.get_job(engine, item["id"])
        assert {k: v for k, v in item.items() if k not in {"workflow", "pipeline"}} == expected
        assert item["workflow"] == jobs.get_workflow(engine, item["id"])
        assert item["pipeline"] == jobs.pipeline(engine, item["id"])
    calls = []

    def count(*args):
        calls.append(1)

    event.listen(engine, "before_cursor_execute", count)
    try:
        with engine.connect() as conn:
            jobs.batch_requirements(conn)
        all_count = len(calls)
        calls.clear()
        with engine.connect() as conn:
            jobs.batch_requirements(conn, job)
        assert len(calls) == all_count == 3
    finally:
        event.remove(engine, "before_cursor_execute", count)


def test_batch_eligibility_matches_real_contact_selection_and_joining(office_workspace):
    engine, job, link, candidate = fixture(office_workspace)
    flow = jobs.save_workflow(
        engine, job, WorkflowInput(workflow_mode="DIRECT", workflow_version=0)
    )
    for stage in ("CONTACT", "SELECTED", "JOINED"):
        if stage != "CONTACT":
            facts = direct_movement.choices(engine, job, link["id"])
            direct_movement.move(
                engine,
                job,
                link["id"],
                direct_movement.DirectMove(
                    idempotency_key=uuid4(),
                    destination_stage=stage,
                    expected_stage=facts["current_stage"],
                    workflow_version=flow["workflow_version"],
                    selected_on=unified.office_today() if stage == "SELECTED" else None,
                    joined_on=unified.office_today() if stage == "JOINED" else None,
                    confirmation_evidence="Synthetic joining evidence" if stage == "JOINED" else "",
                ),
                "OFFICE_LAN",
            )
        with engine.connect() as conn:
            assert unified.eligibility_many(conn, [candidate["id"]])[
                candidate["id"]
            ] == unified.eligibility(conn, candidate["id"])
