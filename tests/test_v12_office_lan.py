"""Office policy uses synthetic temporary SQLite fixtures; no live data writes."""

import inspect
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
import test_approved_v12 as approved_tests
import test_v12_candidate_complete as profile_tests
import test_v12_parsed_documents as parsed_tests
import test_v12_proposal_pdf as proposal_tests
from fastapi.testclient import TestClient
from test_unified_v12 import requirement, snapshot
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from jobmitra.core.config import Settings
from jobmitra.core.office_lan import OFFICE_ACTOR, OfficePolicy
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import profile_store, proposal_store, unified

BASE = "http://192.168.1.51:8002"


@pytest.fixture
def office_settings(store):
    profile_store.install(store[0])
    proposal_store.install(store[0])
    return Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="unused",
        db_user="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=store[-1] / "isolated.sqlite3",
        ats_v2_resume_storage_root=store[-1] / "resumes",
        unified_v12_enabled=True,
        unified_v12_proposals_enabled=True,
        unified_v12_proposal_storage_root=store[-1] / "private-proposals",
        office_lan_enabled=True,
        office_lan_cidrs="192.168.1.0/24,127.0.0.1/32,::1/128",
    )


@pytest.fixture
def office_client(office_settings):
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        with TestClient(
            create_app(office_settings), base_url=BASE, client=("192.168.1.25", 50000)
        ) as c:
            c.headers.update({"Origin": BASE, "X-Jobmitra-UI": "1"})
            assert not c.cookies
            access = c.get("/api/v12/access").json()
            assert (
                access["office_lan"] and access["editing"] and access["actor_name"] == OFFICE_ACTOR
            )
            yield c
            assert not c.cookies


WORKFLOWS = [
    approved_tests.test_approved_registration_upload_is_atomic_and_retry_safe,
    approved_tests.test_company_contact_edits_retain_identity_and_removed_evidence,
    profile_tests.test_complete_fields_precision_months_audit_and_search,
    profile_tests.test_omitted_fields_explicit_clear_stale_and_retry,
    profile_tests.test_foundit_preview_registration_duplicates_and_enrichment,
    parsed_tests.test_pdf_labelled_partial_extraction_is_draft_until_explicit_approval,
    parsed_tests.test_json_raw_bytes_bom_unapproved_information_versions_and_source,
    proposal_tests.test_signed_versions_and_explicit_acceptance_do_not_overwrite,
    proposal_tests.test_read_only_email_preview_copy_and_missing_email,
]


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda f: f.__name__.removeprefix("test_"))
def test_workflows_without_tokens(workflow, store, office_client):
    fixtures = {
        "store": store,
        "client": office_client,
        "complete": office_client,
        "pdf_client": office_client,
    }
    workflow(**{key: fixtures[key] for key in inspect.signature(workflow).parameters})


def test_company_jd_creation_edits_and_supervisor_reactivation(office_client, store):
    c = office_client
    company = c.post(
        "/api/v12/companies",
        json={
            "idempotency_key": str(uuid4()),
            "actor_name": OFFICE_ACTOR,
            "company_name": "Office policy synthetic company",
        },
    )
    assert company.status_code == 201, company.text
    created = c.post(
        "/api/ats-v2/jobs",
        json={
            "company_id": company.json()["id"],
            "title": "Office synthetic JD",
            "target_date": unified.office_today().isoformat(),
            "status": "ACTIVE",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 201, created.text
    new_job = created.json()["id"]
    workflow = c.put(
        f"/api/ats-v2/jobs/{new_job}/workflow",
        json={
            "workflow_mode": "CONFIGURED",
            "workflow_version": 0,
            "rounds": [{"round_name": "Office interview"}],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert workflow.status_code == 200, workflow.text
    assert (
        c.post(
            f"/api/ats-v2/jobs/{new_job}/candidates",
            json={"candidate_id": store[3]},
            headers={"Idempotency-Key": str(uuid4())},
        ).status_code
        == 201
    )
    jid, lid = requirement(store)
    job = c.patch(
        f"/api/ats-v2/jobs/{jid}",
        json={"location": "Office synthetic location"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert job.status_code == 200, job.text
    assert c.get(f"/api/ats-v2/jobs/{jid}").json()["location"] == "Office synthetic location"
    path = f"/api/v12/approved/jobs/{jid}/candidates/{lid}/outcome"
    for action in ["SELECT", "JOIN", "REACTIVATE"]:
        body = {
            "idempotency_key": str(uuid4()),
            "actor_name": OFFICE_ACTOR,
            "action": action,
            "effective_on": unified.office_today().isoformat(),
            "confirmation_evidence": "Synthetic joining confirmation",
            "reason": "New job search confirmed",
        }
        response = c.post(path, json=body, headers={"Idempotency-Key": body["idempotency_key"]})
        assert response.status_code == 200, response.text
        assert (
            c.post(
                path, json=body, headers={"Idempotency-Key": body["idempotency_key"]}
            ).status_code
            == 200
        )
    assert c.get(f"/api/v12/candidates/{store[3]}/eligibility").json()["can_allocate"]
    history = c.get(f"/api/ats-v2/history?job_id={jid}").json()["items"]
    events = [e for e in history if e["event_type"] == "OFFICE_LAN_SUPERVISOR_AUTHORIZED"]
    assert len(events) == 1 and events[0]["payload_json"]["authorization_policy"] == "OFFICE_LAN"
    assert events[0]["payload_json"]["individual_authenticated"] is False
    for page in ["/email", "/email/updates", "/email/proposal", "/email/submission"]:
        assert c.get(page).status_code == 200


@pytest.mark.parametrize("peer", ["192.168.2.25", "203.0.113.2", "10.1.2.3"])
def test_outside_allowlist_rejected_everywhere(office_settings, store, peer):
    before = snapshot(store[0])
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        with TestClient(create_app(office_settings), base_url=BASE, client=(peer, 5000)) as c:
            for path in [
                "/",
                "/email",
                "/api/v12/access",
                "/api/ats-v2/health",
                "/static/ats-v2/approved-api.mjs",
                "/api/v12/companies",
            ]:
                assert c.get(path).status_code == 403
            assert c.post("/api/v12/companies", json={}).status_code == 403
    assert snapshot(store[0]) == before


@pytest.mark.parametrize(
    "header", ["Forwarded", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "X-Real-IP"]
)
def test_forwarded_headers_rejected_even_after_uvicorn_rewrites_peer(office_settings, header):
    app = ProxyHeadersMiddleware(create_app(office_settings), trusted_hosts="*")
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        with TestClient(app, base_url=BASE, client=("203.0.113.2", 5000)) as c:
            assert c.get("/api/v12/access", headers={header: "192.168.1.25"}).status_code == 403


def test_host_rebinding_and_same_origin_still_rejected(office_client):
    assert office_client.get("/api/v12/access", headers={"Host": "evil.example"}).status_code == 403
    assert (
        office_client.post(
            "/api/v12/companies", headers={"Origin": "http://evil.example"}, json={}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "cidrs",
    ["", "0.0.0.0/0", "192.168.1.5/24", "8.8.8.0/24", "::/0", "192.168.1.0/24,", "169.254.0.0/16"],
)
def test_invalid_or_public_allowlist_fails_startup(office_settings, cidrs):
    with pytest.raises(RuntimeError, match="CIDRs"):
        create_app(office_settings.model_copy(update={"office_lan_cidrs": cidrs}))


def test_conflicting_modes_and_missing_flags_fail_closed(office_settings):
    for update in [
        {"unified_v12_local_direct_editing": True},
        {"unified_v12_enabled": False},
        {"ats_v2_enabled": False},
    ]:
        with pytest.raises(RuntimeError):
            create_app(office_settings.model_copy(update=update))


def test_ipv6_mapped_peer_and_explicit_hostname(office_settings):
    policy = OfficePolicy.from_settings(
        office_settings.model_copy(update={"office_lan_hosts": "jobmitra.office"})
    )
    scope = {
        "type": "http",
        "scheme": "http",
        "server": ("192.168.1.51", 8002),
        "client": ("::ffff:192.168.1.25", 5000),
        "path": "/",
        "query_string": b"",
        "headers": [(b"host", b"jobmitra.office:8002")],
    }
    assert policy.allows(scope)
    scope["client"] = ("::ffff:192.168.2.25", 5000)
    assert not policy.allows(scope)


def test_resume_versions_download_without_cookie_and_keep_ownership(office_client, store):
    from pdf_fixture import valid_pdf

    c = office_client
    cid = store[3]
    blob = valid_pdf()
    for kind in ["ORIGINAL", "JOBMITRA_STANDARD"]:
        for version in range(2):
            response = c.post(
                f"/api/ats-v2/candidates/{cid}/resumes",
                content=blob,
                headers={
                    "Idempotency-Key": str(uuid4()),
                    "X-Resume-Kind": kind,
                    "X-Resume-Filename": f"office-{version}.pdf",
                },
            )
            assert response.status_code == 201, response.text
            rid = response.json()["id"]
            url = f"/api/ats-v2/candidates/{cid}/resumes/{rid}/download"
            assert c.get(url).content == blob
            assert (
                c.get(f"/api/ats-v2/candidates/{cid + 1}/resumes/{rid}/download").status_code == 404
            )
    versions = c.get(f"/api/ats-v2/candidates/{cid}/resumes").json()
    assert len(versions) == 4 and sum(v["is_current"] for v in versions) == 2


def test_protected_mode_still_requires_operator_and_supervisor(office_settings, store):
    config = office_settings.model_copy(
        update={
            "office_lan_enabled": False,
            "unified_v12_operator_token": None,
            "unified_v12_supervisor_token": None,
        }
    )
    # Validate through Settings so SecretStr typing matches real configuration.
    config = Settings(
        **{
            **config.model_dump(),
            "unified_v12_operator_token": "synthetic-operator-0123456789",
            "unified_v12_supervisor_token": "synthetic-supervisor-0123456789",
        },
        _env_file=None,
    )
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        with TestClient(create_app(config), base_url=BASE, client=("203.0.113.2", 5000)) as c:
            c.headers.update({"Origin": BASE, "X-Jobmitra-UI": "1"})
            assert c.post("/api/v12/companies", json={}).status_code == 403
            assert (
                c.post(
                    "/api/v12/access", json={"token": "synthetic-operator-0123456789"}
                ).status_code
                == 200
            )
            jid, lid = requirement(store)
            path = f"/api/v12/approved/jobs/{jid}/candidates/{lid}/outcome"
            for action in ["SELECT", "JOIN"]:
                body = {
                    "action": action,
                    "idempotency_key": str(uuid4()),
                    "actor_name": "Declared operator",
                    "effective_on": unified.office_today().isoformat(),
                    "confirmation_evidence": "Synthetic joining",
                }
                assert (
                    c.post(
                        path, json=body, headers={"Idempotency-Key": body["idempotency_key"]}
                    ).status_code
                    == 200
                )
            body = {
                **body,
                "action": "REACTIVATE",
                "reason": "Confirmed new job search",
                "idempotency_key": str(uuid4()),
            }
            assert (
                c.post(
                    path, json=body, headers={"Idempotency-Key": body["idempotency_key"]}
                ).status_code
                == 403
            )
            assert (
                c.post(
                    "/api/v12/access", json={"token": "synthetic-supervisor-0123456789"}
                ).status_code
                == 200
            )
            assert (
                c.post(
                    path, json=body, headers={"Idempotency-Key": body["idempotency_key"]}
                ).status_code
                == 200
            )


def test_office_dotenv_selection_precedes_automatic_sqlite_profile(tmp_path, monkeypatch):
    from jobmitra.core import config, local_v12

    env = tmp_path / ".env"
    env.write_text("JOBMITRA_OFFICE_LAN_ENABLED=true\n")
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", env)
    monkeypatch.delenv("JOBMITRA_OFFICE_LAN_ENABLED", raising=False)
    monkeypatch.delenv("JOBMITRA_LOCAL_V12", raising=False)
    config.get_settings.cache_clear()
    expected = object()
    try:
        with (
            patch.object(config, "Settings", return_value=expected),
            patch.object(local_v12, "local_settings") as local,
        ):
            assert config.get_settings() is expected
            local.assert_not_called()
        config.get_settings.cache_clear()
        monkeypatch.setenv("JOBMITRA_LOCAL_V12", "1")
        with pytest.raises(RuntimeError, match="conflicts"):
            config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_office_missing_store_never_falls_back(office_settings, tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with patch("jobmitra.main.build_engine", return_value=Mock()):
        with pytest.raises(RuntimeError, match="existing valid V12"):
            with TestClient(
                create_app(office_settings.model_copy(update={"ats_v2_database": missing}))
            ):
                pass
    assert not missing.exists()
