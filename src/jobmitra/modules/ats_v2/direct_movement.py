"""Atomic forward movement composed from canonical transitions, not new statuses."""

from datetime import date
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from . import jobs, unified
from . import request_receipts as receipts
from .common import AtsError, one, utc_now
from .database import transaction
from .schemas import MoveInput, Stage


class DirectMove(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: UUID
    destination_stage: Literal[
        "CONTACT", "SCREENING", "COMPANY_SUBMISSION", "ROUND", "SELECTED", "JOINED"
    ]
    destination_round_id: str | None = Field(default=None, max_length=200)
    expected_stage: Stage
    expected_round_id: str | None = Field(default=None, max_length=200)
    workflow_version: int = Field(ge=0)
    selected_on: date | None = None
    joined_on: date | None = None
    confirmation_evidence: str = Field(default="", max_length=5000)


def destinations(conn, job, link):
    flow = jobs.workflow(conn, job["id"])
    if (
        job["status"] != "ACTIVE"
        or link["stage_code"] in {"JOINED", "NOT_SELECTED"}
        or link.get("selection_outcome") in {"NOT_JOINED", "SELECTION_CANCELLED"}
    ):
        return []
    result, probe = [], dict(link)
    for _ in range(len(flow["rounds"]) + 7):
        code, round_id = jobs.next_stage(probe, flow)
        if code is None:
            break
        if (
            code in {"SELECTED", "JOINED"}
            and not unified.eligibility(conn, link["candidate_id"], link["id"])["can_allocate"]
        ):
            break
        probe.update(stage_code=code, round_id=round_id)
        result.append(
            {
                "stage_code": code,
                "round_id": round_id,
                "key": "ROUND:" + round_id if code == "ROUND" else code,
                "label": jobs.stage_label(probe, flow["rounds"]),
                "requires_selection_date": code in {"SELECTED", "JOINED"}
                and link["stage_code"] != "SELECTED",
                "requires_joining": code == "JOINED",
            }
        )
    return result


def choices(engine, job_id, link_id):
    with engine.connect() as conn:
        job, link = one(conn, "job_descriptions", job_id), jobs.linked(conn, job_id, link_id)
        return {
            "current_stage": link["stage_code"],
            "current_round_id": link["round_id"],
            "current_label": jobs.stage_label(link, jobs.workflow(conn, job_id)["rounds"]),
            "workflow_version": job["workflow_version"],
            "selected_on": link.get("selected_on"),
            "destinations": destinations(conn, job, link),
        }


def move(engine, job_id, link_id, data: DirectMove, role):
    key = str(data.idempotency_key)
    if receipts.request_key.get() not in {None, key}:
        raise AtsError("The action reference and request key must match.")
    token = receipts.set_key(key)
    try:
        return _move(engine, job_id, link_id, data, role)
    finally:
        receipts.request_key.reset(token)


def _move(engine, job_id, link_id, data, role):
    request_data = [job_id, link_id, data.model_dump(mode="json")]
    with transaction(engine) as conn:
        link = jobs.linked(conn, job_id, link_id)
        if receipts.replay(conn, "direct-movement", request_data) is not None:
            return link
        job = one(conn, "job_descriptions", job_id)
        if (link["stage_code"], link["round_id"]) != (data.expected_stage, data.expected_round_id):
            raise AtsError("Candidate stage changed. Reload before confirming.", 409)
        if job["workflow_version"] != data.workflow_version:
            raise AtsError("Workflow changed. Reload before confirming.", 409)
        path = destinations(conn, job, link)
        index = next(
            (
                i
                for i, target in enumerate(path)
                if (target["stage_code"], target["round_id"])
                == (data.destination_stage, data.destination_round_id)
            ),
            None,
        )
        if index is None:
            raise AtsError(
                "Choose a valid later stage in this active JD. Closed records cannot reopen.", 409
            )
        path = path[: index + 1]
        target = path[-1]
        if target["requires_selection_date"] and data.selected_on is None:
            raise AtsError("Enter the actual company selection date.")
        if target["requires_joining"] and (
            data.joined_on is None or not data.confirmation_evidence
        ):
            raise AtsError("Enter the actual joining date and joining confirmation details.")
        if data.selected_on and not target["requires_selection_date"]:
            raise AtsError("An existing selection date cannot be changed by stage movement.")
        if (data.joined_on or data.confirmation_evidence) and not target["requires_joining"]:
            raise AtsError("Joining details apply only when confirming actual joining.")
        actor = {
            "OFFICE_LAN": "Office LAN user (individual identity unverified)",
            "LOCAL_DEVELOPMENT": "Local development user (individual identity unverified)",
        }.get(role, "Capability-authorized user (individual identity unverified)")
        original = dict(link)
        # Only the outer operation claims the HTTP key. Each normal canonical
        # movement and outcome remains in the same transaction and is auditable.
        token = receipts.request_key.set(None)
        try:
            for step, destination in enumerate(path):
                code = destination["stage_code"]
                if code in {"SELECTED", "JOINED"}:
                    action = unified.Action(
                        action="SELECT" if code == "SELECTED" else "JOIN",
                        idempotency_key=uuid5(data.idempotency_key, f"direct:{step}:{code}"),
                        actor_name=actor,
                        effective_on=data.selected_on if code == "SELECTED" else data.joined_on,
                        confirmation_evidence=data.confirmation_evidence
                        if code == "JOINED"
                        else "",
                        expected_stage=link["stage_code"],
                        workflow_version=data.workflow_version,
                    )
                    link = unified.outcome(conn, job_id, link_id, action, role)
                else:
                    link = jobs.move_candidate(
                        conn,
                        job_id,
                        link_id,
                        MoveInput(
                            stage_code=code,
                            round_id=destination["round_id"],
                            expected_stage=link["stage_code"],
                            expected_round_id=link["round_id"],
                            workflow_version=data.workflow_version,
                        ),
                    )
        finally:
            receipts.request_key.reset(token)
        current = {"stage_code": original["stage_code"], "round_id": original["round_id"]}
        receipts.record(
            conn,
            "direct-movement",
            request_data,
            link_id,
            candidate_id=link["candidate_id"],
            job_id=job_id,
            details={
                "manual_stage_confirmation": True,
                "previous_stage": current,
                "destination": target,
                "completed_stages": [current, *path[:-1]],
                "recorded_at": utc_now(),
                "employee_id": None,
                "authorization_policy": role,
                "individual_authenticated": False,
            },
        )
        return link
