"""Dynamic recipients on synthetic fixtures and mocked Gmail only; no live delivery."""

import base64
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_gmail_phase1 import settings as settings_fixture
from test_unified_v12 import store, v2  # noqa: F401
from test_v12_postgres_backend import pg_store  # noqa: F401

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import candidates, jobs, unified
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate, CandidatePatch
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.ats_v2.schemas import JobCreate
from jobmitra.modules.email_studio import gmail_history as audit
from jobmitra.modules.email_studio import gmail_service as gmail

settings = settings_fixture


@pytest.fixture(params=["sqlite", "postgresql"])
def fixture_store(request):
    return (
        request.getfixturevalue("store")
        if request.param == "sqlite"
        else request.getfixturevalue("pg_store")[0]
    )


@pytest.fixture
def live(settings):
    return settings.model_copy(update={"gmail_mode": "live", "gmail_test_recipient": ""})


@pytest.fixture
def people(fixture_store):
    engine = fixture_store[0]
    return [
        candidates.create_candidate(engine, CandidateCreate(full_name=name, email=email))
        for name, email in [
            ("Pooja Jobmitra", "pooja.jobmitra@gmail.com"),
            ("Jobmitra", "jobs@jobmitra.com"),
        ]
    ]


def draft(engine, settings, person, **changes):
    with engine.connect() as conn:
        context = audit.recipient_context(conn, settings, person["id"])
    return audit.SendInput(
        reference=uuid4(),
        candidate_id=person["id"],
        template_id="screening_completed",
        intended_recipient=context["intended_recipient"],
        actual_recipient=context["actual_recipient"],
        recipient_context=context["recipient_context"],
        subject="Mocked candidate update",
        html=f"<p>Hello {person['full_name']}</p>",
        plain=f"Hello {person['full_name']}",
        **changes,
    )


def records(engine):
    with engine.connect() as conn:
        return {
            table: conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
            for table in [
                "candidates",
                "companies",
                "job_descriptions",
                "jd_candidates",
                "candidate_activities",
            ]
        }


def test_canonical_recipient_switch_mime_history_and_no_stage_changes(fixture_store, live, people):
    engine, company, *_ = fixture_store
    jd = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Mocked live recipient JD",
            status="ACTIVE",
            target_date=unified.office_today(),
        ),
        CompanyGateway(engine),
    )
    for person in people:
        jobs.attach_contact(engine, jd["id"], person["id"])
    before = records(engine)
    outgoing = []

    def accepted(settings, raw):
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
        outgoing.append(str(message["To"]))
        assert not message["Cc"] and not message["Bcc"]
        return {"message_id": f"mock-live-{len(outgoing)}", "thread_id": "mock-thread"}

    with patch.object(gmail, "send", side_effect=accepted) as sending:
        for person in people:
            data = draft(engine, live, person, job_id=jd["id"], company_id=company)
            first = audit.dispatch(engine, live, data)
            assert first["actual_recipient"] == person["email"]
            assert first["test_mode"] is False and first["delivery_mode"] == "live"
            assert first["candidate_id"] == person["id"] and first["job_id"] == jd["id"]
            assert first["gmail_message_id"].startswith("mock-live-")
            assert audit.dispatch(engine, live, data)["email_reference"] == first["email_reference"]
            assert (
                audit.dispatch(engine, live, data.model_copy(update={"reference": uuid4()}))[
                    "email_reference"
                ]
                == first["email_reference"]
            )
        assert sending.call_count == 2
    assert outgoing == ["pooja.jobmitra@gmail.com", "jobs@jobmitra.com"]
    assert records(engine) == before
    with engine.connect() as conn:
        for person in people:
            history = audit.history(conn, person["id"])
            assert len(history) == 1 and history[0]["status"] == "Accepted by Gmail"
            assert history[0]["actual_recipient"] == person["email"]
            assert history[0]["jd_candidate_id"] is not None


@pytest.mark.parametrize(
    "change",
    ["intended", "actual", "candidate", "missing_snapshot", "name_changed", "email_changed"],
)
def test_stale_or_overridden_recipient_never_claims_or_sends(fixture_store, live, people, change):
    engine = fixture_store[0]
    data = draft(engine, live, people[1])
    if change in {"intended", "actual"}:
        data = data.model_copy(update={change + "_recipient": "pooja.jobmitra@gmail.com"})
    elif change == "candidate":
        data = data.model_copy(update={"candidate_id": people[0]["id"]})
    elif change == "missing_snapshot":
        data = data.model_copy(update={"recipient_context": None})
    else:
        candidates.update_candidate(
            engine,
            people[1]["id"],
            CandidatePatch(full_name="Changed Name")
            if change == "name_changed"
            else CandidatePatch(email="changed@example.test"),
        )
    with patch.object(gmail, "send") as sending, pytest.raises((AtsError, gmail.GmailError)):
        audit.dispatch(engine, live, data)
    sending.assert_not_called()
    with engine.connect() as conn:
        assert not audit.history(conn)


@pytest.mark.parametrize(
    "email",
    [
        None,
        "",
        "invalid",
        "two@example.com,other@example.com",
        "bad..name@example.com",
        "a@-bad.example",
        "a@example..com",
    ],
)
def test_missing_invalid_email_blocks_context_and_send(fixture_store, live, people, email):
    engine = fixture_store[0]
    data = draft(engine, live, people[1])
    with transaction(engine) as conn:
        conn.execute(
            text("UPDATE candidates SET email=:email WHERE id=:id"),
            {"email": email, "id": people[1]["id"]},
        )
    with engine.connect() as conn:
        context = audit.recipient_context(conn, live, people[1]["id"])
        assert not context["allowed"] and "missing or invalid" in context["detail"]
        assert "actual_recipient" not in context
    with patch.object(gmail, "send") as sending, pytest.raises(AtsError):
        audit.dispatch(engine, live, data)
    sending.assert_not_called()


def test_test_mode_restriction_and_mode_specific_fingerprint(fixture_store, settings, live, people):
    engine = fixture_store[0]
    with engine.connect() as conn:
        assert not audit.recipient_context(conn, settings, people[1]["id"])["allowed"]
        assert (
            audit.recipient_context(conn, settings, people[0]["id"])["actual_recipient"]
            == settings.gmail_test_recipient
        )
    data = draft(engine, live, people[0])
    assert gmail.fingerprint(data, mode="live") != gmail.fingerprint(data, mode="test")
    legacy = data.model_copy(update={"recipient_context": None})
    assert gmail.fingerprint(data) == gmail.fingerprint(legacy)
    import hashlib

    body = legacy.model_dump(
        mode="json", exclude={"reference", "resend_of", "confirm_resend", "recipient_context"}
    )
    assert (
        gmail.fingerprint(legacy)
        == hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    )


def test_concurrent_unknown_outcome_is_not_resent(fixture_store, live, people):
    engine = fixture_store[0]
    data = draft(engine, live, people[1])
    with patch.object(
        gmail, "send", side_effect=gmail.GmailError("Mock interrupted response", unknown=True)
    ) as sending:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(
                pool.map(
                    lambda _: audit.dispatch(
                        engine, live, data.model_copy(update={"reference": uuid4()})
                    ),
                    range(3),
                )
            )
        assert sending.call_count == 1
        final = audit.dispatch(engine, live, data)
        assert final["status"] == "Send outcome unknown"
        assert final["gmail_message_id"] is None
        assert len({r["email_reference"] for r in results}) == 1


def test_live_configuration_keeps_mac_loopback_boundaries(live, monkeypatch):
    gmail.validate_configuration(live)
    status = gmail.connection_status(live)
    assert status["enabled"] and status["mode"] == "live" and not status["test_mode"]
    assert status["actual_recipient"] is None
    for options in [
        {"office_lan_enabled": True},
        {"unified_v12_local_direct_editing": False},
        {"unified_v12_enabled": False},
    ]:
        with pytest.raises(gmail.GmailError):
            gmail.validate_configuration(live.model_copy(update=options))
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(gmail.GmailError):
        gmail.validate_configuration(live)
    assert not Settings(
        _env_file=None, db_host="unused", db_name="unused", db_user="unused", db_password="unused"
    ).gmail_enabled


def test_api_recipient_snapshot_access_and_explicit_send_only(
    live, people, fixture_store, monkeypatch, request
):
    engine = fixture_store[0]
    monkeypatch.setattr("jobmitra.core.local_v12.validate_direct_editing", lambda _: None)
    if engine.dialect.name == "postgresql":
        pg_config = request.getfixturevalue("pg_store")[1]
        config = live.model_copy(
            update={
                key: getattr(pg_config, key)
                for key in [
                    "db_host",
                    "db_port",
                    "db_name",
                    "db_user",
                    "db_password",
                    "db_sslmode",
                    "v12_backend",
                    "v12_postgres_development",
                    "v12_postgres_schema",
                ]
            }
        )
    else:
        config = live.model_copy(update={"ats_v2_database": Path(engine.url.database)})
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(
            create_app(config), base_url="http://127.0.0.1", client=("127.0.0.1", 40000)
        ) as client,
    ):
        url = f"/api/v12/gmail/context/{people[1]['id']}"
        with patch.object(gmail, "send") as sending:
            context = client.get(url).json()
            assert context["actual_recipient"] == "jobs@jobmitra.com"
            assert client.get(url, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
            sending.assert_not_called()
        data = draft(engine, live, people[1])
        headers = {
            "Origin": "http://127.0.0.1",
            "X-Jobmitra-UI": "1",
            "Idempotency-Key": str(data.reference),
        }
        assert (
            client.post("/api/v12/gmail/send", json=data.model_dump(mode="json")).status_code == 403
        )
        with patch.object(
            gmail, "send", return_value={"message_id": "mock-api-live", "thread_id": "mock-thread"}
        ) as sending:
            sent = client.post(
                "/api/v12/gmail/send", json=data.model_dump(mode="json"), headers=headers
            )
            assert sent.status_code == 200, sent.text
            assert sent.json()["actual_recipient"] == "jobs@jobmitra.com"
            assert sending.call_count == 1
        assert (
            client.get(f"/api/v12/gmail/history/{people[1]['id']}").json()["items"][0][
                "gmail_message_id"
            ]
            == "mock-api-live"
        )
