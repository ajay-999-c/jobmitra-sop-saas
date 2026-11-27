"""SQLite JD/workflow transactions with PostgreSQL company validation at the boundary."""

import json
from contextlib import nullcontext
from datetime import UTC, date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import request_receipts as receipts
from .common import AtsError, event_record, one, utc_now
from .database import insert_result, transaction
from .schemas import ActivityInput, JobCreate

FIXED = {
    "POOL": "Candidate Pool",
    "CONTACT": "Candidate Contact",
    "SCREENING": "Jobmitra Screening",
    "COMPANY_SUBMISSION": "Company Submission",
}
OUTCOMES = {"SELECTED": "Selected by Company", "JOINED": "Joined", "NOT_SELECTED": "Not Selected"}


def target_state(job, today=None):
    today = today or datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
    if job["status"] == "CLOSED":
        return "CLOSED"
    if job["vacancies"] is not None and job.get("joined_count", 0) >= job["vacancies"]:
        return "FILLED"
    if not job.get("target_date"):
        return "UNSET"
    if job["status"] != "ACTIVE":
        return "NEUTRAL"
    days = (date.fromisoformat(job["target_date"]) - today).days
    return "OVERDUE" if days < 0 else "DUE" if days <= 2 else "TRACK"


def job_record(row):
    from .workspace_store import revision

    row = dict(row)
    row["revision"] = revision(row)
    if row.get("assigned_recruiter_id"):
        from uuid import UUID

        row["assigned_recruiter_id"] = str(UUID(str(row["assigned_recruiter_id"])))
    row["skills"] = json.loads(row.pop("skills_json", "[]"))
    row.pop("owner_name", None)
    row["target_state"] = target_state(row)
    row["days_remaining"] = (
        (
            date.fromisoformat(row["target_date"])
            - datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).date()
        ).days
        if row.get("target_date")
        else None
    )
    return row


JOB_SELECT = """SELECT j.*, (SELECT count(*) FROM jd_candidates l
    WHERE l.job_id=j.id AND l.stage_code='JOINED') AS joined_count,
    (SELECT count(*) FROM jd_candidates l WHERE l.job_id=j.id) AS candidate_count
    FROM job_descriptions j"""


def job_select(conn):
    from . import workspace_store
    from .unified import is_v3

    query = (
        JOB_SELECT.replace(
            "l.stage_code='JOINED'",
            "l.selection_outcome='JOINED_CONFIRMED' AND l.joined_on IS NOT NULL "
            "AND l.joining_confirmed_at_utc IS NOT NULL",
        )
        if is_v3(conn)
        else JOB_SELECT
    )
    if workspace_store.installed(conn):
        query = query.replace(
            "SELECT j.*",
            "SELECT j.*,e.display_name AS assigned_recruiter_name,e.is_active "
            "AS assigned_recruiter_active",
        )
        query += (
            " LEFT JOIN v_employee_directory e ON "
            "replace(e.id,'-','')=replace(CAST(j.assigned_recruiter_id AS TEXT),'-','')"
        )
    return query


def get_job(engine, job_id):
    with engine.connect() as conn:
        row = (
            conn.execute(text(job_select(conn) + " WHERE j.id=:id"), {"id": job_id})
            .mappings()
            .first()
        )
        if not row:
            raise AtsError("JD not found.", 404)
        return job_record(row)


def list_jobs(engine, *, status=None, page=1, page_size=50):
    where = " WHERE j.status=:status" if status else ""
    params = {"status": status, "limit": page_size, "offset": (page - 1) * page_size}
    with engine.connect() as conn:
        total = conn.execute(
            text("SELECT count(*) FROM job_descriptions j" + where), params
        ).scalar()
        items = [
            job_record(row)
            for row in conn.execute(
                text(
                    job_select(conn)
                    + where
                    + " ORDER BY j.created_at DESC,j.id DESC LIMIT :limit OFFSET :offset"
                ),
                params,
            ).mappings()
        ]
        all_jobs = [job_record(row) for row in conn.execute(text(job_select(conn))).mappings()]
    summary = {
        "active": sum(j["status"] == "ACTIVE" for j in all_jobs),
        "overdue": sum(j["target_state"] == "OVERDUE" for j in all_jobs),
        "due_soon": sum(j["target_state"] == "DUE" for j in all_jobs),
        "filled_closed": sum(j["target_state"] in {"CLOSED", "FILLED"} for j in all_jobs),
    }
    return {
        "items": items,
        "total": total,
        "summary": summary,
        "page": page,
        "page_size": page_size,
    }


def create_job(engine, data, companies):
    companies.require(data.company_id)
    values = data.model_dump(mode="json")
    values["skills_json"] = json.dumps(values.pop("skills"))
    values["jd_code"] = "JD-" + uuid4().hex[:12].upper()
    with transaction(engine) as conn:
        prior = receipts.replay(conn, "job-create", data.model_dump(mode="json"))
        if prior is not None:
            return get_job(engine, prior)
        from . import workspace_store

        if workspace_store.installed(conn):
            workspace_store.assignment(conn, values.get("assigned_recruiter_id"))
            values["assigned_recruiter_id"] = workspace_store.storage_id(
                conn, values.get("assigned_recruiter_id")
            )
        elif values.pop("assigned_recruiter_id", None):
            workspace_store.require(conn)
        columns = ",".join(values)
        result = insert_result(
            conn,
            text(
                f"INSERT INTO job_descriptions({columns}) "
                f"VALUES({','.join(':' + k for k in values)})"
            ),
            values,
        )
        job_id = result.lastrowid
        receipts.record(conn, "job-create", data.model_dump(mode="json"), job_id, job_id=job_id)
    return get_job(engine, job_id)


def update_job(engine, job_id, data, companies):
    # Company validation must succeed before any SQLite changes. No cross-store SQL joins.
    changes = data.model_dump(mode="json", exclude_unset=True)
    if "company_id" in changes:
        companies.require(data.company_id)
    with transaction(engine) as conn:
        request_data = {"job_id": job_id, **changes}
        if receipts.replay(conn, "job-update", request_data) is not None:
            return get_job(engine, job_id)
        from . import workspace_store

        raw_current = one(conn, "job_descriptions", job_id)
        expected = changes.pop("expected_revision", None)
        if workspace_store.installed(conn):
            if expected != workspace_store.revision(raw_current):
                raise AtsError(
                    "This JD changed. Reload and review the latest details before saving.",
                    409,
                    "JD_CONFLICT",
                )
            if "assigned_recruiter_id" in changes:
                workspace_store.assignment(
                    conn, changes["assigned_recruiter_id"], raw_current.get("assigned_recruiter_id")
                )
        elif changes.pop("assigned_recruiter_id", None):
            workspace_store.require(conn)
        current = job_record(raw_current)
        merged = {name: current.get(name) for name in JobCreate.model_fields}
        merged.update(changes)
        validated = JobCreate.model_validate(merged)
        # Validate the complete patch, while preserving only fields that were explicitly submitted.
        values = {key: validated.model_dump(mode="json")[key] for key in changes}
        if "assigned_recruiter_id" in values:
            values["assigned_recruiter_id"] = workspace_store.storage_id(
                conn, values["assigned_recruiter_id"]
            )
        from .unified import is_v3

        if is_v3(conn) and values.get("company_id", current["company_id"]) != current["company_id"]:
            values.update(
                company_contact_id=None,
                company_contact_name_snapshot=None,
                company_contact_email_snapshot=None,
                contact_request_key=None,
                contact_request_fingerprint=None,
                contact_actor_name=None,
                contact_actor_role=None,
            )
        if "skills" in values:
            values["skills_json"] = json.dumps(values.pop("skills"))
        if values:
            conn.execute(
                text(
                    "UPDATE job_descriptions SET "
                    + ",".join(f"{key}=:{key}" for key in values)
                    + " WHERE id=:id"
                ),
                {**values, "id": job_id},
            )
        receipts.record(conn, "job-update", request_data, job_id, job_id=job_id)
    return get_job(engine, job_id)


def workflow(conn, job_id):
    job = one(conn, "job_descriptions", job_id)
    rounds = [
        dict(r)
        for r in conn.execute(
            text("SELECT * FROM jd_interview_rounds WHERE job_id=:id ORDER BY display_order,id"),
            {"id": job_id},
        ).mappings()
    ]
    impact = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT r.id AS round_id,r.round_name,count(l.id) AS candidates "
                "FROM jd_interview_rounds r LEFT JOIN jd_candidates l ON l.round_id=r.id "
                "AND l.stage_code='ROUND' WHERE r.job_id=:id GROUP BY r.id ORDER BY r.display_order"
            ),
            {"id": job_id},
        ).mappings()
    ]
    return {
        "workflow_mode": job["workflow_mode"],
        "workflow_version": job["workflow_version"],
        "rounds": rounds,
        "impact": impact,
        "fixed_stages": [{"stage_code": k, "label": v} for k, v in FIXED.items()],
        "outcomes": [{"stage_code": k, "label": v} for k, v in OUTCOMES.items()],
    }


def get_workflow(engine, job_id):
    with engine.connect() as conn:
        return workflow(conn, job_id)


def save_workflow(engine, job_id, data):
    with transaction(engine) as conn:
        request_data = {"job_id": job_id, "workflow": data.model_dump(mode="json")}
        if receipts.replay(conn, "workflow", request_data) is not None:
            return workflow(conn, job_id)
        current = workflow(conn, job_id)
        if current["workflow_version"] != data.workflow_version:
            raise AtsError(
                "Workflow changed. Reload and review candidate impact before saving.", 409
            )
        saved = {r["id"]: r for r in current["rounds"]}
        seen = [str(r.id) for r in data.rounds if r.id]
        if len(seen) != len(set(seen)) or not set(seen) <= saved.keys():
            raise AtsError("Round IDs must be unique and belong to this JD.")
        # Omitting saved rounds would erase context; callers must explicitly retire them.
        if set(seen) != set(saved):
            raise AtsError("Retain saved rounds in the workflow; retire them instead of deleting.")
        active = [r for r in data.rounds if r.is_active]
        occupied = {r["round_id"] for r in current["impact"] if r["candidates"]}
        active_ids = {str(r.id) for r in active if r.id}
        if occupied - active_ids:
            raise AtsError("Move candidates out of a round before retiring it.")
        if data.workflow_mode != "CONFIGURED" and (active or occupied):
            raise AtsError("Retire unused company rounds before choosing Direct or Unknown.")
        if data.workflow_mode == "CONFIGURED" and not active:
            raise AtsError("Configured interview mode requires an active round.")
        conn.execute(
            text(
                "UPDATE job_descriptions SET workflow_mode=:mode,"
                "workflow_version=workflow_version+1 WHERE id=:id"
            ),
            {"mode": data.workflow_mode, "id": job_id},
        )
        for order, values in enumerate(data.rounds, 1):
            record = values.model_dump(mode="json")
            record.update(
                id=str(values.id) if values.id else str(uuid4()), display_order=order, job_id=job_id
            )
            prior = saved.get(record["id"])
            record["retired_at"] = (
                None if record["is_active"] else (prior or {}).get("retired_at") or utc_now()
            )
            if prior:
                conn.execute(
                    text(
                        "UPDATE jd_interview_rounds SET round_name=:round_name,"
                        "mode=:mode,is_active=:is_active,display_order=:display_order,"
                        "retired_at=:retired_at WHERE id=:id AND job_id=:job_id"
                    ),
                    record,
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO jd_interview_rounds(id,job_id,round_name,mode,"
                        "is_active,display_order,retired_at) VALUES(:id,:job_id,:round_name,:mode,"
                        ":is_active,:display_order,:retired_at)"
                    ),
                    record,
                )
        receipts.record(conn, "workflow", request_data, job_id, job_id=job_id)
        return workflow(conn, job_id)


def stage_label(link, rounds):
    if link.get("selection_outcome") in {"NOT_JOINED", "SELECTION_CANCELLED"}:
        return link["selection_outcome"].replace("_", " ").title()
    if link["stage_code"] == "ROUND":
        return next(
            (r["round_name"] for r in rounds if r["id"] == link["round_id"]),
            "Retained interview round",
        )
    return {**FIXED, **OUTCOMES}[link["stage_code"]]


def next_stage(link, flow):
    if link.get("selection_outcome") in {"NOT_JOINED", "SELECTION_CANCELLED"}:
        return None, None
    code = link["stage_code"]
    if code in {"JOINED", "NOT_SELECTED"}:
        return None, None
    fixed = list(FIXED)
    if code in fixed[:-1]:
        return fixed[fixed.index(code) + 1], None
    if code == "SELECTED":
        return "JOINED", None
    if flow["workflow_mode"] == "UNKNOWN":
        return None, None
    rounds = [r for r in flow["rounds"] if r["is_active"]]
    if flow["workflow_mode"] == "DIRECT":
        return "SELECTED", None
    if code == "COMPANY_SUBMISSION":
        return ("ROUND", rounds[0]["id"]) if rounds else (None, None)
    if code == "ROUND":
        index = next((i for i, r in enumerate(rounds) if r["id"] == link["round_id"]), None)
        if index is None:
            return None, None
        return ("ROUND", rounds[index + 1]["id"]) if index + 1 < len(rounds) else ("SELECTED", None)
    return None, None


def pipeline(engine, job_id):
    with engine.connect() as conn:
        flow = workflow(conn, job_id)
        items = []
        counts = dict.fromkeys([*FIXED, *OUTCOMES], 0)
        counts.update({"ROUND:" + r["id"]: 0 for r in flow["rounds"]})
        for row in conn.execute(
            text(
                "SELECT l.*,c.full_name,c.job_title,c.current_city,"
                "c.skills_json,c.experience_years,c.phone,c.email FROM jd_candidates l "
                "JOIN candidates c ON c.id=l.candidate_id "
                "WHERE l.job_id=:id ORDER BY l.added_at,l.id"
            ),
            {"id": job_id},
        ).mappings():
            item = dict(row)
            item["skills"] = json.loads(item.pop("skills_json"))
            item.pop("added_by", None)
            item.pop("changed_by", None)
            item["stage_label"] = stage_label(item, flow["rounds"])
            item["effective_status"] = (
                item.get("selection_outcome")
                if item.get("selection_outcome") in {"NOT_JOINED", "SELECTION_CANCELLED"}
                else item["stage_code"]
            )
            item["next_stage"], item["next_round_id"] = next_stage(item, flow)
            if item["next_stage"]:
                item["next_stage_label"] = stage_label(
                    {"stage_code": item["next_stage"], "round_id": item["next_round_id"]},
                    flow["rounds"],
                )
            key = (
                "ROUND:" + item["round_id"]
                if item["stage_code"] == "ROUND"
                else item["effective_status"]
            )
            counts[key] = counts.get(key, 0) + 1
            items.append(item)
        return {"items": items, "counts": counts, "workflow": flow}


def associate(engine, job_id, candidate_id):
    with nullcontext(engine) if isinstance(engine, Connection) else transaction(engine) as conn:
        request_data = [job_id, candidate_id]
        prior = receipts.replay(conn, "association", request_data)
        if prior is not None:
            return one(conn, "jd_candidates", prior)
        job = one(conn, "job_descriptions", job_id)
        candidate = one(conn, "candidates", candidate_id)
        if job["status"] != "ACTIVE":
            raise AtsError("Only ACTIVE JDs can accept candidates.")
        if not candidate["is_active"]:
            raise AtsError("An inactive candidate cannot be added to a JD.")
        from .unified import is_v3, require_available

        if is_v3(conn):
            require_available(conn, candidate_id)
        if conn.execute(
            text("SELECT id FROM jd_candidates WHERE job_id=:j AND candidate_id=:c"),
            {"j": job_id, "c": candidate_id},
        ).first():
            raise AtsError("Already associated. View Existing JD Pool.", 409)
        result = insert_result(
            conn,
            text("INSERT INTO jd_candidates(job_id,candidate_id) VALUES(:j,:c)"),
            {"j": job_id, "c": candidate_id},
        )
        receipts.record(
            conn,
            "association",
            request_data,
            result.lastrowid,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        return one(conn, "jd_candidates", result.lastrowid)


def attach_contact(engine, job_id, candidate_id):
    """V12 sourcing: retain the canonical Pool event then complete it atomically."""
    with transaction(engine) as conn:
        data = [job_id, candidate_id]
        prior = receipts.replay(conn, "contact-association", data)
        if prior is not None:
            return linked(conn, job_id, prior)
        existing = conn.execute(
            text("SELECT id FROM jd_candidates WHERE job_id=:j AND candidate_id=:c"),
            {"j": job_id, "c": candidate_id},
        ).scalar_one_or_none()
        if existing is not None:
            result = linked(conn, job_id, existing)
        else:
            from .schemas import MoveInput

            # Internal steps share the outer transaction, not its request receipt.
            token = receipts.request_key.set(None)
            try:
                result = associate(conn, job_id, candidate_id)
                result = move_candidate(
                    conn,
                    job_id,
                    result["id"],
                    MoveInput(
                        stage_code="CONTACT",
                        expected_stage="POOL",
                    ),
                )
            finally:
                receipts.request_key.reset(token)
        receipts.record(
            conn,
            "contact-association",
            data,
            result["id"],
            candidate_id=candidate_id,
            job_id=job_id,
        )
        return result


def linked(conn, job_id, link_id):
    link = one(conn, "jd_candidates", link_id)
    if link["job_id"] != job_id:
        raise AtsError("Candidate participation not found in this JD.", 404)
    return link


def reached_context(conn, job, link, stage_code=None, round_id=None):
    """Resolve a stage without moving a membership or inventing interview attendance.

    Standard steps keep the existing cumulative-reach inference. Custom rounds
    require their stable ID in the current membership or retained journey.
    Feedback itself is never evidence that a stage was reached.
    """
    if stage_code is None:
        if round_id is not None:
            raise AtsError("Choose a stage for this interview round.")
        return dict(link)
    if stage_code not in {*FIXED, *OUTCOMES, "ROUND"}:
        raise AtsError("Unknown recruitment stage.")
    if (stage_code == "ROUND") != bool(round_id):
        raise AtsError("Use the stable round ID only with an interview stage.")
    rounds = workflow(conn, job["id"])["rounds"]
    if round_id and not any(r["id"] == round_id for r in rounds):
        raise AtsError("This interview round does not belong to the selected JD.")
    evidence = [(link["stage_code"], link.get("round_id"), None)]
    if link.get("rejected_from_stage") in FIXED:
        evidence.append((link["rejected_from_stage"], None, None))
    rows = conn.execute(
        text(
            "SELECT * FROM recruitment_events WHERE jd_candidate_id=:id "
            "AND event_type NOT IN ('FEEDBACK','REQUEST_COMPLETED') ORDER BY id"
        ),
        {"id": link["id"]},
    ).mappings()
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        payload = payload if isinstance(payload, dict) else {}
        for side in ("before", "after"):
            fact = json.loads(row[side + "_json"] or "{}")
            if isinstance(fact, dict) and isinstance(fact.get("stage_code"), str):
                evidence.append((fact["stage_code"], fact.get("round_id"), None))
        for side in ("from", "to"):
            if row[side + "_stage"]:
                evidence.append(
                    (
                        row[side + "_stage"],
                        payload.get(side + "_round_id"),
                        row[side + "_label_snapshot"],
                    )
                )
    evidence = [
        ("ROUND", code[6:], label) if code.startswith("ROUND:") else (code, rid, label)
        for code, rid, label in evidence
    ]
    exact = [
        label
        for code, rid, label in evidence
        if code == stage_code and (code != "ROUND" or rid == round_id)
    ]
    order = list(FIXED)
    standard_reached = stage_code in FIXED and any(
        code in {"ROUND", "SELECTED", "JOINED"}
        or (code in FIXED and order.index(code) >= order.index(stage_code))
        for code, _, _ in evidence
    )
    if not exact and not standard_reached:
        raise AtsError("This candidate has not reached the selected stage in this JD.", 409)
    target = dict(link, stage_code=stage_code, round_id=round_id, selection_outcome=None)
    target["_feedback_label"] = (
        next((label for label in exact if label), None) if stage_code == "ROUND" else None
    )
    target["_historical"] = (
        stage_code != link["stage_code"]
        or round_id != link.get("round_id")
        or link.get("selection_outcome") in {"NOT_JOINED", "SELECTION_CANCELLED"}
    )
    return target


def add_feedback(conn, job, link, feedback, source, *, target=None):
    target = target or link
    label = target.get("_feedback_label") or stage_label(
        target, workflow(conn, job["id"])["rounds"]
    )
    conn.execute(
        text(
            "INSERT INTO recruitment_events(job_id,candidate_id,jd_candidate_id,"
            "event_type,from_stage,to_stage,from_label_snapshot,to_label_snapshot,feedback,"
            "feedback_source,workflow_version,payload_json) "
            "VALUES(:job_id,:candidate_id,:link_id,'FEEDBACK',"
            ":stage,:stage,:label,:label,:feedback,:source,:version,:payload)"
        ),
        {
            "job_id": job["id"],
            "candidate_id": link["candidate_id"],
            "link_id": link["id"],
            "stage": target["stage_code"],
            "label": label,
            "feedback": feedback,
            "source": source,
            "version": job["workflow_version"],
            "payload": json.dumps(
                {
                    "feedback_stage": {
                        "stage_code": target["stage_code"],
                        "round_id": target.get("round_id"),
                        "label": label,
                        "historical": target.get("_historical", False),
                    }
                }
            ),
        },
    )


def move_candidate(engine, job_id, link_id, data):
    with nullcontext(engine) if isinstance(engine, Connection) else transaction(engine) as conn:
        request_data = [job_id, link_id, data.model_dump(mode="json")]
        if receipts.replay(conn, "movement", request_data) is not None:
            return one(conn, "jd_candidates", link_id)
        from .unified import is_v3

        if is_v3(conn) and data.stage_code in {"SELECTED", "JOINED"}:
            raise AtsError(
                "Use the explicit company-selection or actual-joining confirmation action.", 409
            )
        job = one(conn, "job_descriptions", job_id)
        link = linked(conn, job_id, link_id)
        if job["status"] != "ACTIVE":
            raise AtsError("Activate the JD before moving candidates.")
        flow = workflow(conn, job_id)
        if data.workflow_version is not None and data.workflow_version != job["workflow_version"]:
            raise AtsError("Workflow changed. Reload before moving candidates.", 409)
        if data.expected_stage and (
            data.expected_stage != link["stage_code"]
            or (str(data.expected_round_id) if data.expected_round_id else None) != link["round_id"]
        ):
            raise AtsError("Candidate stage changed. Reload the pipeline.", 409)
        destination = (data.stage_code, str(data.round_id) if data.round_id else None)
        if link["stage_code"] in {"JOINED", "NOT_SELECTED"}:
            raise AtsError("This outcome is terminal; its history is retained.", 409)
        rejection = data.stage_code == "NOT_SELECTED" and link["stage_code"] != "SELECTED"
        if not rejection and destination != next_stage(link, flow):
            raise AtsError("Only the next configured stage or rejection is permitted.")
        if data.stage_code != "ROUND" and data.round_id:
            raise AtsError("A round ID is valid only for company interview stages.")
        values = {"id": link_id, "stage_code": data.stage_code, "round_id": destination[1]}
        extra = ""
        if rejection:
            active_rounds = [r for r in flow["rounds"] if r["is_active"]]
            index = next(
                (i + 1 for i, r in enumerate(active_rounds) if r["id"] == link["round_id"]), None
            )
            values.update(
                rejected_from_stage=link["stage_code"],
                rejected_round_name=stage_label(link, flow["rounds"]),
                rejected_round_index=index,
                rejected_at=utc_now(),
            )
            extra = (
                ",rejected_from_stage=:rejected_from_stage,rejected_round_name=:rejected_round_name,"
                "rejected_round_index=:rejected_round_index,rejected_at=:rejected_at"
            )
        conn.execute(
            text(
                "UPDATE jd_candidates SET stage_code=:stage_code,round_id=:round_id"
                + extra
                + " WHERE id=:id"
            ),
            values,
        )
        if data.feedback:
            add_feedback(conn, job, link, data.feedback, data.feedback_source)
        receipts.record(
            conn,
            "movement",
            request_data,
            link_id,
            candidate_id=link["candidate_id"],
            job_id=job_id,
        )
        return one(conn, "jd_candidates", link_id)


def feedback(engine, job_id, link_id, data):
    with transaction(engine) as conn:
        job = one(conn, "job_descriptions", job_id)
        link = linked(conn, job_id, link_id)
        request_data = [job_id, link_id, data.model_dump(mode="json", exclude_none=True)]
        if receipts.replay(conn, "feedback", request_data) is not None:
            return {"saved": True}
        target = reached_context(conn, job, link, data.stage_code, data.round_id)
        add_feedback(conn, job, link, data.feedback, data.feedback_source, target=target)
        receipts.record(
            conn,
            "feedback",
            request_data,
            link_id,
            candidate_id=link["candidate_id"],
            job_id=job_id,
        )
    return {"saved": True}


def history(engine, *, candidate_id=None, job_id=None, jd_candidate_id=None, page=1, page_size=50):
    if not any((candidate_id, job_id, jd_candidate_id)):
        raise AtsError("Choose a candidate, JD or candidate-in-JD history.")
    with engine.connect() as conn:
        for record_id, table in [
            (candidate_id, "candidates"),
            (job_id, "job_descriptions"),
            (jd_candidate_id, "jd_candidates"),
        ]:
            if record_id:
                one(conn, table, record_id)
        clauses, params = (
            ["event_type<>'REQUEST_COMPLETED'"],
            {"limit": page_size, "offset": (page - 1) * page_size},
        )
        for key, value in [
            ("candidate_id", candidate_id),
            ("job_id", job_id),
            ("jd_candidate_id", jd_candidate_id),
        ]:
            if value:
                clauses.append(f"{key}=:{key}")
                params[key] = value
        where = " WHERE " + " AND ".join(clauses)
        total = conn.execute(
            text("SELECT count(*) FROM recruitment_events" + where), params
        ).scalar()
        rows = conn.execute(
            text(
                "SELECT * FROM recruitment_events"
                + where
                + " ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).mappings()
        return {
            "items": [event_record(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def activities(engine, candidate_id):
    with engine.connect() as conn:
        one(conn, "candidates", candidate_id)
        return [
            event_record(r)
            for r in conn.execute(
                text(
                    "SELECT * FROM candidate_activities WHERE candidate_id=:id "
                    "ORDER BY created_at DESC,id DESC"
                ),
                {"id": candidate_id},
            ).mappings()
        ]


def save_activity(engine, candidate_id, data, activity_id=None):
    with transaction(engine) as conn:
        one(conn, "candidates", candidate_id)
        request_data = [candidate_id, activity_id, data.model_dump(mode="json", exclude_unset=True)]
        prior = receipts.replay(conn, "activity", request_data)
        if prior is not None:
            return event_record(one(conn, "candidate_activities", prior))
        if activity_id:
            row = one(conn, "candidate_activities", activity_id)
            if row["candidate_id"] != candidate_id:
                raise AtsError("Activity not found.", 404)
            values = {key: row[key] for key in ActivityInput.model_fields}
            values.update(data.model_dump(exclude_unset=True))
            data = ActivityInput.model_validate(values)
        if data.job_id:
            one(conn, "job_descriptions", data.job_id)
            if not conn.execute(
                text("SELECT id FROM jd_candidates WHERE job_id=:j AND candidate_id=:c"),
                {"j": data.job_id, "c": candidate_id},
            ).first():
                raise AtsError("Link the candidate to this JD before recording its activity.")
        values = data.model_dump()
        for key in ("due_at", "occurred_at"):
            values[key] = (
                values[key].astimezone(UTC).isoformat().replace("+00:00", "Z")
                if values[key]
                else None
            )
        if activity_id:
            conn.execute(
                text(
                    "UPDATE candidate_activities SET "
                    + ",".join(f"{key}=:{key}" for key in values)
                    + " WHERE id=:id"
                ),
                {**values, "id": activity_id},
            )
        else:
            result = insert_result(
                conn,
                text(
                    "INSERT INTO candidate_activities(candidate_id,"
                    + ",".join(values)
                    + ") VALUES(:candidate_id,"
                    + ",".join(":" + k for k in values)
                    + ")"
                ),
                {**values, "candidate_id": candidate_id},
            )
            activity_id = result.lastrowid
        receipts.record(conn, "activity", request_data, activity_id, candidate_id=candidate_id)
        return event_record(one(conn, "candidate_activities", activity_id))
