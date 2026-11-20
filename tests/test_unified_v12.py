"""V12 migrations and workflows use only synthetic, isolated SQLite files."""

import copy
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import candidates, jobs, unified
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate, SearchParams
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import (
    build_ats_engine,
    initialize,
    transaction,
    upgrade_unified,
    validate,
)
from jobmitra.modules.ats_v2.master_import import local_state, preserve_existing
from jobmitra.modules.ats_v2.resumes import get_resume, upload_resume
from jobmitra.modules.ats_v2.schemas import JobCreate, MoveInput, WorkflowInput

OPERATOR = "isolated-operator-capability-0123456789"
SUPERVISOR = "isolated-supervisor-capability-0123456789"
HEADERS = {"Origin": "http://testserver", "X-Jobmitra-UI": "1"}
ROLE = "OPERATOR_TOKEN"


@pytest.fixture
def v2(tmp_path):
    engine = build_ats_engine(tmp_path / "isolated.sqlite3")
    initialize(engine)
    company, contact = str(uuid4()), str(uuid4())
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO "
                "companies(id,company_name,company_name_key,contacts_json) "
                "VALUES(:id,'Synthetic Client Company','synthetic client "
                "company',:contacts)"
            ),
            {
                "id": company,
                "contacts": json.dumps(
                    [
                        {
                            "id": contact,
                            "contact_name": "Synthetic HR",
                            "designation": None,
                            "phone_numbers": [],
                            "created_at": "2020-01-01T00:00:00Z",
                        }
                    ]
                ),
            },
        )
    candidate = candidates.create_candidate(
        engine,
        CandidateCreate(
            full_name="Synthetic Candidate", skills=["Python"], email="candidate@example.test"
        ),
    )
    yield engine, company, contact, candidate["id"], tmp_path
    engine.dispose()


@pytest.fixture
def store(v2):
    upgrade_unified(v2[0])
    return v2


def snapshot(engine):
    with engine.connect() as conn:
        return local_state(conn), list(
            conn.exec_driver_sql("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")
        )


def requirement(store):
    engine, company, _, candidate, _ = store
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Synthetic Engineer",
            target_date=unified.office_today() + timedelta(days=5),
            status="ACTIVE",
        ),
        CompanyGateway(engine),
    )
    jobs.save_workflow(
        engine, job["id"], WorkflowInput(workflow_mode="DIRECT", workflow_version=0, rounds=[])
    )
    link = jobs.associate(engine, job["id"], candidate)
    for stage in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION"]:
        jobs.move_candidate(engine, job["id"], link["id"], MoveInput(stage_code=stage))
    return job["id"], link["id"]


def action(kind, **changes):
    return unified.Action(
        action=kind,
        idempotency_key=uuid4(),
        actor_name="Declared test operator",
        effective_on=unified.office_today(),
        **changes,
    )


def test_upgrade_preserves_every_original_field_and_is_idempotent(v2):
    engine = v2[0]
    before, _ = snapshot(engine)
    upgrade_unified(engine)
    validate(engine)
    with engine.connect() as conn:
        preserve_existing(conn, before)
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 3
        assert conn.scalar(text("SELECT count(*) FROM company_audit_events")) == 0
        assert (
            len(list(conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")))
            == 9
        )
    after = snapshot(engine)
    upgrade_unified(engine)
    assert snapshot(engine) == after


def test_upgrade_rollback_and_interrupted_ddl_preserve_v2(v2):
    engine, _, _, _, root = v2
    before = snapshot(engine)
    with pytest.raises(RuntimeError):
        with transaction(engine) as conn:
            upgrade_unified(conn)
            raise RuntimeError("synthetic interruption")
    assert snapshot(engine) == before
    engine.dispose()
    code = """import os,sys
from jobmitra.modules.ats_v2.database import build_ats_engine,_statements,UNIFIED_UPGRADE_PATH
e=build_ats_engine(sys.argv[1]);c=e.connect();c.exec_driver_sql('BEGIN IMMEDIATE')
for i,s in enumerate(_statements(UNIFIED_UPGRADE_PATH)):
 c.exec_driver_sql(s)
 if i==5:os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(root / "isolated.sqlite3")], capture_output=True
    )
    assert result.returncode == 23
    assert snapshot(engine) == before
    validate(engine)


def test_selection_joining_eligibility_reporting_and_idempotency(store):
    engine, _, _, cid, _ = store
    jid, lid = requirement(store)
    selected = action("SELECT")
    before = len(snapshot(engine)[0]["recruitment_events"])
    unified.outcome(engine, jid, lid, selected, ROLE)
    unified.outcome(engine, jid, lid, selected, ROLE)
    assert len(snapshot(engine)[0]["recruitment_events"]) == before + 1
    assert candidates.get_candidate(engine, cid)["allocation_eligibility"] == "SELECTED_ON_HOLD"
    assert cid in [r["id"] for r in candidates.search_candidates(engine, SearchParams())["items"]]
    assert unified.report(engine)["metrics"]["confirmed_placements"] == 0
    with pytest.raises(Exception, match="unresolved"):
        jobs.associate(engine, jid, cid)
    with pytest.raises(ValidationError):
        action("JOIN")
    joined = action(
        "JOIN", confirmation_evidence="Candidate and recruiter confirmed actual joining"
    )
    unified.outcome(engine, jid, lid, joined, ROLE)
    assert candidates.get_candidate(engine, cid)["allocation_eligibility"] == "PLACED_LOCKED"
    assert unified.report(engine)["metrics"]["confirmed_placements"] == 1
    with pytest.raises(Exception, match="supervisor"):
        unified.outcome(
            engine, jid, lid, action("REACTIVATE", reason="Explicit new job search"), ROLE
        )
    unified.outcome(
        engine,
        jid,
        lid,
        action("REACTIVATE", reason="Approved sourcing reactivation"),
        "SUPERVISOR_TOKEN",
    )
    assert candidates.get_candidate(engine, cid)["allocation_eligibility"] == "AVAILABLE_AGAIN"
    assert unified.report(engine)["metrics"]["confirmed_placements"] == 1
    assert len(candidates.get_candidate(engine, cid)["participation"]) == 1
    with pytest.raises(Exception, match="request key"):
        unified.outcome(
            engine, jid, lid, selected.model_copy(update={"reason": "different request"}), ROLE
        )


@pytest.mark.parametrize("outcome", ["NOT_JOINED", "CANCEL"])
def test_closed_selections_restore_pool_access_and_keep_history(store, outcome):
    engine, _, _, cid, _ = store
    jid, lid = requirement(store)
    unified.outcome(engine, jid, lid, action("SELECT"), ROLE)
    unified.outcome(engine, jid, lid, action(outcome, reason="Explicit reviewed closure"), ROLE)
    profile = candidates.get_candidate(engine, cid)
    assert profile["can_allocate"]
    assert profile["participation"][0]["stage_code"] == "SELECTED"
    assert jobs.pipeline(engine, jid)["items"][0]["next_stage"] is None
    assert unified.report(engine)["metrics"]["confirmed_placements"] == 0
    other = requirement(store)
    assert other[1] != lid
    assert len(candidates.get_candidate(engine, cid)["participation"]) == 2


def test_concurrent_selections_have_one_winner_and_database_gate(store):
    engine, _, _, cid, _ = store
    first, second = requirement(store), requirement(store)

    def select(pair):
        try:
            unified.outcome(engine, *pair, action("SELECT"), ROLE)
            return "selected"
        except Exception as error:
            assert getattr(error, "status", None) == 409
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(select, [first, second])) == ["blocked", "selected"]
    assert len(candidates.get_candidate(engine, cid)["participation"]) == 2
    with pytest.raises(IntegrityError):
        with transaction(engine) as conn:
            conn.execute(
                text("INSERT INTO jd_candidates(job_id,candidate_id) VALUES(:job,:candidate)"),
                {"job": first[0], "candidate": cid},
            )


def test_calendar_boundaries_and_effective_joining_date(store):
    assert unified.period_bounds("week", today=date(2026, 11, 19)) == (
        date(2026, 11, 16),
        date(2026, 11, 22),
    )
    assert unified.period_bounds("month", today=date(2024, 2, 20)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )
    assert unified.period_bounds("year", today=date(2026, 11, 19)) == (
        date(2026, 1, 1),
        date(2026, 12, 31),
    )
    engine = store[0]
    jid, lid = requirement(store)
    earlier = unified.office_today() - timedelta(days=10)
    selected = action("SELECT").model_copy(update={"effective_on": earlier})
    unified.outcome(engine, jid, lid, selected, ROLE)
    unified.outcome(
        engine, jid, lid, action("JOIN", confirmation_evidence="Verified actual joining"), ROLE
    )
    past = unified.report(engine, "custom", earlier, earlier)
    assert (
        past["metrics"]["company_selections"] == 1 and past["metrics"]["confirmed_placements"] == 0
    )
    current = unified.report(engine, "custom", unified.office_today(), unified.office_today())
    assert (
        current["metrics"]["confirmed_placements"] == 1
        and current["metrics"]["company_selections"] == 0
    )
    with pytest.raises(IntegrityError):
        with transaction(engine) as conn:
            conn.execute(
                text("UPDATE jd_candidates SET joined_on='2026-02-30' WHERE id=:id"), {"id": lid}
            )


def test_company_emails_contact_ownership_audit_and_preview_no_send(store):
    engine, company, contact, cid, _ = store
    before = CompanyGateway(engine).detail(company)["contacts"]
    edit = unified.CompanyEdit(
        idempotency_key=uuid4(),
        actor_name="Declared operator",
        contacts=[unified.ContactEmail(id=contact, email="hr@example.test", is_primary_email=True)],
    )
    unified.edit_company(engine, company, edit, ROLE)
    unified.edit_company(engine, company, edit, ROLE)
    records = unified.company_records(engine, company)
    assert len(records["audit"]) == 1
    original = copy.deepcopy(records["contacts"])
    original[0].pop("email")
    original[0].pop("is_primary_email")
    assert original == before
    jid, lid = requirement(store)
    unified.choose_contact(
        engine,
        jid,
        unified.ContactChoice(
            contact_id=contact, idempotency_key=uuid4(), actor_name="Declared operator"
        ),
        ROLE,
    )
    event_count = len(snapshot(engine)[0]["recruitment_events"])
    candidate = unified.email_context(engine, cid, jid, "CANDIDATE")
    assert candidate["company_name"] is None and "Synthetic Client Company" not in candidate["body"]
    assert candidate["recipient_email"] == "candidate@example.test"
    assert (
        unified.email_context(engine, cid, jid, "COMPANY")["recipient_email"] == "hr@example.test"
    )
    assert len(snapshot(engine)[0]["recruitment_events"]) == event_count
    with pytest.raises(Exception):
        unified.choose_contact(
            engine,
            jid,
            unified.ContactChoice(
                contact_id=uuid4(), idempotency_key=uuid4(), actor_name="Declared operator"
            ),
            ROLE,
        )
    with pytest.raises(IntegrityError):
        with transaction(engine) as conn:
            conn.exec_driver_sql("DELETE FROM company_audit_events")


def test_v12_access_and_v2_fail_closed_without_automatic_migration(store):
    engine, _, _, cid, root = store
    config = Settings(
        _env_file=None,
        db_host="invalid.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=root / "isolated.sqlite3",
        ats_v2_resume_storage_root=root / "resumes",
        unified_v12_enabled=True,
        unified_v12_operator_token=OPERATOR,
        unified_v12_supervisor_token=SUPERVISOR,
    )
    pg = Mock()
    pg.connect.side_effect = AssertionError("Production PostgreSQL is forbidden")
    with (
        patch("jobmitra.main.build_engine", return_value=pg),
        TestClient(create_app(config)) as client,
    ):
        assert client.get("/api/v12/companies").status_code == 200
        assert (
            client.post(
                "/api/ats-v2/candidates", headers=HEADERS, json={"full_name": "Blocked"}
            ).status_code
            == 403
        )
        assert (
            client.post("/api/v12/access", headers=HEADERS, json={"token": OPERATOR}).status_code
            == 200
        )
        assert (
            "httponly" in client.cookies.get("jobmitra_v12_access", "")
            or client.get("/api/v12/access").json()["editing"]
        )
        assert client.get(f"/api/v12/candidates/{cid}/eligibility").json()["can_allocate"]
        assert client.get("/api/ats-v2/candidates").status_code == 200
        assert client.delete("/api/v12/access", headers=HEADERS).status_code == 200
        assert not client.get("/api/v12/access").json()["editing"]
    pg.connect.assert_not_called()


def test_reviewed_parse_diff_approval_versions_and_search_are_atomic(store):
    engine, _, _, cid, root = store
    original = upload_resume(
        engine, cid, root / "resumes", b"%PDF-1.4\nsynthetic\n%%EOF", "synthetic.pdf", 10000
    )
    parsed = unified.ParsedReview(
        profile={
            "current_job_title": "Reviewed Engineer",
            "skills": ["Rust"],
            "work_experience": [{"title": "Historical Engineer"}],
        },
        source_resume_id=original["id"],
        facts_reviewed=True,
        idempotency_key=uuid4(),
        actor_name="Declared reviewer",
        approved_fields=["skills"],
    )
    before = candidates.get_candidate(engine, cid)
    with engine.connect() as conn:
        raw = dict(
            conn.execute(text("SELECT * FROM candidates WHERE id=:id"), {"id": cid})
            .mappings()
            .one()
        )
    diff = unified.parsed_diff(raw, parsed.profile)
    assert {r["status"] for r in diff} == {"NEW", "CONFLICT"}
    assert candidates.get_candidate(engine, cid) == before
    result = unified.review_parse(engine, cid, parsed, ROLE)
    assert candidates.get_candidate(engine, cid)["skills"] == ["Rust"]
    assert candidates.get_candidate(engine, cid)["job_title"] is None
    assert candidates.search_candidates(engine, SearchParams(keywords="Rust"))["total"] == 1
    saved = get_resume(engine, cid, result["resume_id"])
    assert saved["profile"]["work_experience"] == [{"title": "Historical Engineer"}]
    count = len(snapshot(engine)[0]["candidate_resumes"])
    unified.review_parse(engine, cid, parsed, ROLE)
    assert len(snapshot(engine)[0]["candidate_resumes"]) == count
    assert get_resume(engine, cid, original["id"])["resume_kind"] == "ORIGINAL"


def test_new_company_and_new_contacts_are_canonical_and_idempotent(store):
    engine = store[0]
    data = unified.CompanyCreate(
        company_name="Another synthetic company",
        actor_name="Declared operator",
        idempotency_key=uuid4(),
        contacts=[unified.NewContact(contact_name="New HR", email="new@example.test")],
    )
    created = unified.create_company(engine, data, ROLE)
    assert created["id"] == unified.create_company(engine, data, ROLE)["id"]
    before = created["contacts"]
    edit = unified.CompanyEdit(
        actor_name="Declared operator",
        idempotency_key=uuid4(),
        new_contacts=[unified.NewContact(contact_name="Second contact")],
    )
    updated = unified.edit_company(engine, created["id"], edit, ROLE)
    assert updated["contacts"][0] == before[0]
    assert len(updated["contacts"]) == 2
    assert len(unified.edit_company(engine, created["id"], edit, ROLE)["contacts"]) == 2
    assert len(unified.company_records(engine, created["id"])["audit"]) == 2


def test_v2_gate_never_upgrades_at_startup(v2):
    engine, _, _, _, root = v2
    before = snapshot(engine)
    config = Settings(
        _env_file=None,
        db_host="invalid.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=root / "isolated.sqlite3",
        unified_v12_enabled=True,
    )
    pg = Mock()
    with (
        patch("jobmitra.main.build_engine", return_value=pg),
        TestClient(create_app(config)) as client,
    ):
        assert client.get("/api/v12/companies").status_code == 503
        assert client.get("/api/ats-v2/candidates").status_code == 200
    assert snapshot(engine) == before


def test_legacy_null_selected_is_conservatively_locked(v2):
    engine, _, _, cid, _ = v2
    jid, lid = requirement(v2)
    jobs.move_candidate(engine, jid, lid, MoveInput(stage_code="SELECTED"))
    upgrade_unified(engine)
    assert candidates.get_candidate(engine, cid)["allocation_eligibility"] == "SELECTED_ON_HOLD"
    assert unified.report(engine)["metrics"]["confirmed_placements"] == 0


def test_http_retries_do_not_duplicate_candidates_files_or_activities(store):
    engine, _, _, _, root = store
    config = Settings(
        _env_file=None,
        db_host="invalid.test",
        db_user="unused",
        db_name="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=root / "isolated.sqlite3",
        ats_v2_resume_storage_root=root / "resumes",
        unified_v12_enabled=True,
        unified_v12_operator_token=OPERATOR,
    )
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(create_app(config)) as client,
    ):
        assert (
            client.post("/api/v12/access", headers=HEADERS, json={"token": OPERATOR}).status_code
            == 200
        )
        headers = {**HEADERS, "Idempotency-Key": str(uuid4())}
        body = {"full_name": "Same-name source identities stay separate"}
        first = client.post("/api/ats-v2/candidates", headers=headers, json=body)
        assert first.status_code == 201
        cid = first.json()["id"]
        assert client.post("/api/ats-v2/candidates", headers=headers, json=body).json()["id"] == cid
        assert (
            client.post(
                "/api/ats-v2/candidates", headers=headers, json={"full_name": "Changed request"}
            ).status_code
            == 409
        )
        other = client.post(
            "/api/ats-v2/candidates",
            headers={**HEADERS, "Idempotency-Key": str(uuid4())},
            json=body,
        )
        assert other.status_code == 201 and other.json()["id"] != cid
        patch_headers = {**HEADERS, "Idempotency-Key": str(uuid4())}
        candidate_path = f"/api/ats-v2/candidates/{cid}"
        assert (
            client.patch(
                candidate_path, headers=patch_headers, json={"job_title": "First"}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                candidate_path,
                headers={**HEADERS, "Idempotency-Key": str(uuid4())},
                json={"job_title": "Later edit"},
            ).status_code
            == 200
        )
        assert (
            client.patch(candidate_path, headers=patch_headers, json={"job_title": "First"}).json()[
                "job_title"
            ]
            == "Later edit"
        )
        jid, _ = requirement(store)
        job_path = f"/api/ats-v2/jobs/{jid}"
        patch_headers = {**HEADERS, "Idempotency-Key": str(uuid4())}
        assert (
            client.patch(job_path, headers=patch_headers, json={"title": "First"}).status_code
            == 200
        )
        assert (
            client.patch(
                job_path,
                headers={**HEADERS, "Idempotency-Key": str(uuid4())},
                json={"title": "Later title"},
            ).status_code
            == 200
        )
        assert (
            client.patch(job_path, headers=patch_headers, json={"title": "First"}).json()["title"]
            == "Later title"
        )
        upload = {
            **HEADERS,
            "Idempotency-Key": str(uuid4()),
            "X-Resume-Filename": "synthetic.pdf",
            "Content-Type": "application/octet-stream",
        }
        path = f"/api/ats-v2/candidates/{cid}/resumes"
        from pdf_fixture import valid_pdf
        payload = valid_pdf()
        first_file = client.post(path, headers=upload, content=payload)
        assert first_file.status_code == 201
        assert (
            client.post(path, headers=upload, content=payload).json()["id"]
            == first_file.json()["id"]
        )
        assert len(list((root / "resumes").rglob("*.pdf"))) == 1
        activity = {**HEADERS, "Idempotency-Key": str(uuid4())}
        path = f"/api/ats-v2/candidates/{cid}/activities"
        a = client.post(path, headers=activity, json={"activity_type": "FOLLOW_UP"})
        assert a.status_code == 201
        assert (
            client.post(path, headers=activity, json={"activity_type": "FOLLOW_UP"}).json()["id"]
            == a.json()["id"]
        )
        assert (
            client.post(
                path,
                headers={**HEADERS, "Idempotency-Key": "invalid"},
                json={"activity_type": "FOLLOW_UP"},
            ).status_code
            == 422
        )
