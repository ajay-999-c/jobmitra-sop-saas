"""Approved services exercised unchanged against disposable PostgreSQL schemas.

Opt in with JOBMITRA_PG_TEST_SOCKET pointing at our Unix-socket-only restore.
No production configuration, legacy rows or SQLite source is used for fixtures.
"""

import inspect
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import candidates, jobs, unified
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import CORE_TABLES, transaction
from jobmitra.modules.ats_v2.postgres import build_postgres_engine, scoped_sql, validate_postgres
from jobmitra.modules.ats_v2.schemas import JobCreate, MoveInput, WorkflowInput

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import test_approved_v12 as approved_tests  # noqa: E402
import test_unified_v12 as unified_tests  # noqa: E402
import test_v12_candidate_complete as profile_tests  # noqa: E402
import test_v12_parsed_documents as parsed_tests  # noqa: E402
import test_v12_proposal_pdf as proposal_tests  # noqa: E402
from prepare_postgres_v12_dev import provision  # noqa: E402
from stage_v12_postgres import public_fingerprint  # noqa: E402


def core_state(conn):
    return {
        t: sorted([tuple(r) for r in conn.execute(text(f"SELECT * FROM {t}"))], key=repr)
        for t in sorted(CORE_TABLES)
    }


def snapshot(engine):
    with engine.connect() as conn:
        metadata = conn.execute(
            text("""SELECT c.relname,t.tgname,pg_catalog.pg_get_triggerdef(t.oid)
            FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s
            ORDER BY c.relname,t.tgname"""),
            {"s": engine._v12_schema},
        ).all()
        return core_state(conn), metadata


@pytest.fixture
def pg_store(tmp_path, monkeypatch):
    value = os.environ.get("JOBMITRA_PG_TEST_SOCKET")
    if not value:
        pytest.skip("Explicit disposable PostgreSQL socket required")
    socket = Path(value).resolve()
    assert socket.name == "socket" and socket.parent.name.startswith("jobmitra-v12-restore-")
    assert str(socket).startswith("/private/tmp/")
    schema = "jobmitra_v12_dev_test_" + uuid4().hex[:16]
    with psycopg.connect(host=str(socket), dbname="postgres", user="restore_owner") as conn:
        assert conn.execute("SELECT inet_server_addr()").fetchone() == (None,)
        provision(conn, schema)
    config = Settings(
        _env_file=None,
        db_host=str(socket),
        db_name="postgres",
        db_user="restore_owner",
        db_password="unused",
        db_sslmode="disable",
        ats_v2_enabled=True,
        unified_v12_enabled=True,
        v12_backend="postgresql",
        v12_postgres_development=True,
        v12_postgres_schema=schema,
        ats_v2_resume_storage_root=tmp_path / "resumes",
        unified_v12_proposals_enabled=True,
        unified_v12_proposal_storage_root=tmp_path / "private-proposals",
        unified_v12_operator_token=unified_tests.OPERATOR,
        unified_v12_supervisor_token=unified_tests.SUPERVISOR,
    )
    engine = build_postgres_engine(config)
    validate_postgres(engine)
    company, contact = str(uuid4()), str(uuid4())
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key,contacts_json) "
                "VALUES(:id,'Synthetic Client Company','synthetic client company',:contacts)"
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
    person = candidates.create_candidate(
        engine,
        CandidateCreate(
            full_name="Synthetic Candidate", skills=["Python"], email="candidate@example.test"
        ),
    )
    for module in [unified_tests, approved_tests]:
        monkeypatch.setattr(module, "snapshot", snapshot)
    monkeypatch.setattr(proposal_tests, "local_state", core_state)
    try:
        yield (engine, company, contact, person["id"], tmp_path), config
    finally:
        engine.dispose()  # Schemas remain in the disposable cluster as evidence.


@pytest.fixture
def pg_client(pg_store):
    store, config = pg_store
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(create_app(config)) as c,
    ):
        c.headers.update(unified_tests.HEADERS)
        assert c.post("/api/v12/access", json={"token": unified_tests.OPERATOR}).status_code == 200
        yield c


WORKFLOWS = [
    approved_tests.test_approved_shell_and_bootstrap_do_not_mutate_canonical_records,
    approved_tests.test_approved_registration_upload_is_atomic_and_retry_safe,
    approved_tests.test_company_contact_edits_retain_identity_and_removed_evidence,
    approved_tests.test_parsed_approval_preserves_exact_raw_json_and_only_selected_fields,
    approved_tests.test_activity_schedule_and_manual_status_are_persistent_not_delivery,
    approved_tests.test_outcome_and_typed_feedback_commit_together_and_retry_once,
    unified_tests.test_selection_joining_eligibility_reporting_and_idempotency,
    unified_tests.test_concurrent_selections_have_one_winner_and_database_gate,
    unified_tests.test_reviewed_parse_diff_approval_versions_and_search_are_atomic,
    unified_tests.test_new_company_and_new_contacts_are_canonical_and_idempotent,
    profile_tests.test_complete_fields_precision_months_audit_and_search,
    profile_tests.test_omitted_fields_explicit_clear_stale_and_retry,
    profile_tests.test_foundit_preview_registration_duplicates_and_enrichment,
    profile_tests.test_resume_versions_metadata_link_current_hashes_and_private_access,
    parsed_tests.test_pdf_labelled_partial_extraction_is_draft_until_explicit_approval,
    parsed_tests.test_json_raw_bytes_bom_unapproved_information_versions_and_source,
    parsed_tests.test_stale_approval_and_transaction_failure_preserve_draft_and_master,
    parsed_tests.test_parsed_upload_reuses_standard_version_or_immutable_bytes_without_duplicate_copies,
    parsed_tests.test_unified_parent_paths_exact_json_and_tamper_rejection,
    parsed_tests.test_parsed_file_cleanup_after_failed_transaction,
    proposal_tests.test_generation_retry_concurrency_and_failed_publish_roll_back,
    proposal_tests.test_signed_versions_and_explicit_acceptance_do_not_overwrite,
    proposal_tests.test_private_access_and_cross_company_every_resource,
    proposal_tests.test_read_only_email_preview_copy_and_missing_email,
    proposal_tests.test_status_stale_cross_document_confirm_dates_and_integrity,
]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda f: f.__name__.removeprefix("test_"))
def test_existing_approved_workflow_on_postgres(workflow, pg_store, pg_client):
    fixtures = {
        "store": pg_store[0],
        "client": pg_client,
        "complete": pg_client,
        "pdf_client": pg_client,
    }
    workflow(**{name: fixtures[name] for name in inspect.signature(workflow).parameters})


@pytest.mark.parametrize("fee,amount,days", [("6", "36000.00", 21), ("8.33", "49980.00", 30)])
def test_proposal_pdf_exact_content_bytes_and_hash(pg_store, pg_client, fee, amount, days):
    proposal_tests.test_pdf_exact_terms_and_decimal_amounts_no_master_changes(
        pg_client, pg_store[0], fee, amount, days
    )


def test_scoping_preserves_literals_parameters_and_rejects_protected_namespaces():
    schema = "jobmitra_v12_dev_test"
    query = "SELECT 'FROM candidates',:companies FROM candidates WHERE full_name LIKE :q"
    scoped = scoped_sql(query, schema)
    assert "'FROM candidates'" in scoped and ":companies" in scoped
    assert 'FROM "jobmitra_v12_dev_test"."candidates"' in scoped and "ILIKE" in scoped
    for forbidden in [
        "SELECT * FROM public.candidates",
        'SELECT * FROM "public"."staff_members"',
        'SELECT "public".unapproved_function()',
        "SELECT 1; DELETE FROM candidates",
        "UPDATE jobmitra_v12_stage.companies SET city='x'",
        "PRAGMA user_version",
        "DROP TABLE candidates",
    ]:
        with pytest.raises(RuntimeError):
            scoped_sql(forbidden, schema)


def test_protected_schema_configuration_rejected(pg_store):
    from jobmitra.modules.ats_v2.postgres import validate_configuration

    for name in ["public", "jobmitra_v12_stage", 'jobmitra_v12_dev_x";DROP SCHEMA public']:
        config = pg_store[1].model_copy(update={"v12_postgres_schema": name})
        with pytest.raises(RuntimeError):
            validate_configuration(config)


def test_unauthenticated_pg_mutation_rejected_without_side_effect(pg_client, pg_store):
    before = snapshot(pg_store[0][0])
    pg_client.cookies.clear()
    r = pg_client.post(
        "/api/v12/approved/registration",
        headers={"Idempotency-Key": str(uuid4())},
        json={"candidate": {"full_name": "Blocked unverified operation"}},
    )
    assert r.status_code == 403
    assert snapshot(pg_store[0][0]) == before


def test_dashboard_directory_registration_purpose_and_email_source(pg_client, pg_store):
    data = {
        "candidate": {"full_name": "Directory Purpose Fixture", "source": "EMAIL"},
        "registration_purpose": "Discuss a new engineering role",
    }
    r = pg_client.post(
        "/api/v12/approved/registration", json=data, headers={"Idempotency-Key": str(uuid4())}
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    dashboard = pg_client.get(
        "/api/v12/approved/candidate-dashboard", params={"period": "TODAY", "source": "EMAIL"}
    )
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["new_candidates_selected_period"] == 1
    directory = pg_client.get(
        "/api/v12/approved/candidate-directory",
        params={"q": "directory purpose", "source": "EMAIL", "period": "TODAY"},
    )
    assert directory.status_code == 200, directory.text
    assert [r["id"] for r in directory.json()["items"]] == [cid]
    profile = pg_client.get(f"/api/v12/approved/candidates/{cid}/profile").json()
    assert profile["extra"]["registration_purpose"] == data["registration_purpose"]
    for url in ["/email", "/email/updates", "/email/submission", "/email/proposal"]:
        assert pg_client.get(url).status_code == 200


def test_concurrent_candidate_duplicates_have_one_winner(pg_store):
    def register(_):
        try:
            return candidates.create_candidate(
                pg_store[0][0],
                CandidateCreate(full_name="Concurrent Candidate Fixture", phone="9876543210"),
            )["id"]
        except Exception as error:
            assert getattr(error, "status", None) == 409
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(register, range(2)))
    assert result.count("blocked") == 1


def test_interview_rounds_stale_workflow_feedback_and_retirement(pg_store):
    engine, company, _, cid, _ = pg_store[0]
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Round Parity Fixture",
            status="ACTIVE",
            target_date=unified.office_today() + timedelta(days=7),
        ),
        CompanyGateway(engine),
    )
    flow = jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="CONFIGURED",
            workflow_version=0,
            rounds=[{"round_name": "Technical interview"}],
        ),
    )
    round_id = flow["rounds"][0]["id"]
    link = jobs.associate(engine, job["id"], cid)
    for stage in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION"]:
        jobs.move_candidate(engine, job["id"], link["id"], MoveInput(stage_code=stage))
    jobs.move_candidate(
        engine,
        job["id"],
        link["id"],
        MoveInput(
            stage_code="ROUND",
            round_id=round_id,
            feedback="Technical interview scheduled",
            feedback_source="COMPANY",
        ),
    )
    with pytest.raises(Exception, match="retir"):
        jobs.save_workflow(
            engine,
            job["id"],
            WorkflowInput(
                workflow_mode="CONFIGURED",
                workflow_version=flow["workflow_version"],
                rounds=[{"id": round_id, "round_name": "Technical interview", "is_active": False}],
            ),
        )
    with pytest.raises(Exception, match="changed"):
        jobs.save_workflow(
            engine, job["id"], WorkflowInput(workflow_mode="DIRECT", workflow_version=0)
        )
    jobs.move_candidate(
        engine,
        job["id"],
        link["id"],
        MoveInput(
            stage_code="NOT_SELECTED",
            feedback="Company declined after technical review",
            feedback_source="COMPANY",
        ),
    )
    with engine.connect() as conn:
        record = dict(
            conn.execute(text("SELECT * FROM jd_candidates WHERE id=:id"), {"id": link["id"]})
            .mappings()
            .one()
        )
        assert record["rejected_from_stage"] == "ROUND"
        assert record["rejected_round_name"] == "Technical interview"
    jobs.save_workflow(
        engine,
        job["id"],
        WorkflowInput(
            workflow_mode="DIRECT",
            workflow_version=flow["workflow_version"],
            rounds=[{"id": round_id, "round_name": "Technical interview", "is_active": False}],
        ),
    )


def test_configured_postgres_startup_never_falls_back(pg_store):
    config = pg_store[1].model_copy(update={"v12_postgres_schema": "jobmitra_v12_dev_missing"})
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        patch("jobmitra.main.build_ats_engine") as sqlite_builder,
    ):
        with pytest.raises(Exception), TestClient(create_app(config)):
            pass
        sqlite_builder.assert_not_called()


def test_postgres_direct_editing_refuses_nonloopback_bind(pg_store, monkeypatch):
    config = pg_store[1].model_copy(
        update={
            "unified_v12_local_direct_editing": True,
            "ats_v2_resume_storage_root": None,
            "unified_v12_proposal_storage_root": None,
        }
    )
    monkeypatch.setattr(sys, "argv", ["uvicorn", "jobmitra.main:app", "--host", "0.0.0.0"])
    with pytest.raises(RuntimeError, match="loopback"):
        create_app(config)


def test_server_side_stage_clone_preserves_every_row_identity_and_label():
    value = os.environ.get("JOBMITRA_PG_TEST_SOCKET")
    if not value:
        pytest.skip("Explicit disposable PostgreSQL restore required")
    socket = Path(value).resolve()
    assert socket.name == "socket" and socket.parent.name.startswith("jobmitra-v12-restore-")
    assert str(socket).startswith("/private/tmp/")
    schema = "jobmitra_v12_dev_clone_" + uuid4().hex[:16]
    with psycopg.connect(
        host=str(socket), dbname="postgres", user="restore_owner", options="-c timezone=UTC"
    ) as conn:
        before = public_fingerprint(conn)
        counts = provision(conn, schema, clone_verified_stage=True)
        assert sum(counts.values()) == 664 and counts["candidates"] == 190
        assert (
            conn.execute(f'SELECT count(*) FROM "{schema}".development_source_records').fetchone()[
                0
            ]
            == 779
        )
        assert (
            conn.execute(
                f'SELECT count(*) FROM "{schema}".development_source_records '
                "WHERE classification='DEVELOPMENT_TEST'"
            ).fetchone()[0]
            == 125
        )
        assert public_fingerprint(conn) == before
    config = Settings(
        _env_file=None,
        db_host=str(socket),
        db_name="postgres",
        db_user="restore_owner",
        db_password="unused",
        db_sslmode="disable",
        ats_v2_enabled=True,
        unified_v12_enabled=True,
        v12_backend="postgresql",
        v12_postgres_development=True,
        v12_postgres_schema=schema,
    )
    engine = build_postgres_engine(config)
    try:
        validate_postgres(engine)
        from jobmitra.modules.ats_v2.approved import state

        data = state(engine)
        assert len(data["candidates"]) == 190 and len(data["companies"]) == 139
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM recruitment_events")) == 288
            visible = conn.scalar(
                text(
                    "SELECT count(*) FROM recruitment_events WHERE event_type<>'REQUEST_COMPLETED'"
                )
            )
        assert len(data["events"]) == visible  # The approved UI excludes retry receipts.
        # Real imported stage keys are opaque TEXT, not UUID-only request fields.
        with engine.connect() as conn:
            jid = conn.scalar(text("SELECT job_id FROM jd_interview_rounds ORDER BY id LIMIT 1"))
        flow = jobs.get_workflow(engine, jid)
        keys = [r["id"] for r in flow["rounds"]]
        saved = jobs.save_workflow(
            engine,
            jid,
            WorkflowInput(
                workflow_mode=flow["workflow_mode"],
                workflow_version=flow["workflow_version"],
                rounds=[
                    {k: r[k] for k in ["id", "round_name", "mode", "is_active"]}
                    for r in flow["rounds"]
                ],
            ),
        )
        assert [r["id"] for r in saved["rounds"]] == keys
    finally:
        engine.dispose()


def test_bootstrap_query_count_does_not_grow_per_candidate(pg_store):
    from jobmitra.modules.ats_v2.approved import state

    engine = pg_store[0][0]

    def counted():
        statements = []

        def capture(*args):
            statements.append(1)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = state(engine)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        return len(statements), result

    small, _ = counted()
    for index in range(20):
        candidates.create_candidate(
            engine, CandidateCreate(full_name=f"Batch Query Fixture {index}")
        )
    large, data = counted()
    assert len(data["candidates"]) == 21
    assert large == small


def test_untrusted_transport_rejected_before_connecting(pg_store):
    from jobmitra.modules.ats_v2.postgres import validate_configuration

    config = pg_store[1].model_copy(
        update={"db_host": "8.8.8.8", "db_sslmode": "prefer", "v12_postgres_trusted_lan": False}
    )
    with pytest.raises(RuntimeError, match="verified TLS"):
        validate_configuration(config)


def test_readiness_checks_selected_postgres_store(pg_client):
    assert pg_client.get("/health/ready").status_code == 200
    assert pg_client.get("/api/ats-v2/health").json()["storage"] == "postgresql"
