"""Synthetic stores and mocked Gmail only: this suite never sends real email."""

import base64
import gzip
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
import test_unified_v12 as unified_tests
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response
from sqlalchemy import text

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import candidates, jobs
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.email_studio import gmail_history as audit
from jobmitra.modules.email_studio import gmail_service as gmail

v2 = unified_tests.v2
store = unified_tests.store


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    root = (tmp_path / "oauth").resolve()
    root.mkdir(mode=0o700)
    client = {"client_id": "synthetic-client", "client_secret": "synthetic-secret"}
    token = {
        **client,
        "token": "synthetic-access",
        "refresh_token": "synthetic-refresh",
        "token_uri": gmail.TOKEN_URI,
        "scopes": [gmail.SCOPE],
        "expiry": "2099-01-01T00:00:00Z",
    }
    for name, value in (("credentials.json", {"installed": client}), ("token.json", token)):
        path = root / name
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    return Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_name="unused",
        db_user="unused",
        db_password="unused",
        unified_v12_enabled=True,
        ats_v2_enabled=True,
        unified_v12_local_direct_editing=True,
        gmail_enabled=True,
        gmail_sender="jobmitra@gmail.com",
        gmail_test_recipient="pooja.jobmitra@gmail.com",
        gmail_credentials_file=root / "credentials.json",
        gmail_token_file=root / "token.json",
    )


@pytest.fixture
def sample(store):
    person = candidates.create_candidate(
        store[0],
        CandidateCreate(
            full_name="Pooja Jobmitra",
            email="pooja.jobmitra@gmail.com",
            job_title="Synthetic Test Role",
        ),
    )
    return store[0], person["id"]


def draft(candidate, **extra):
    return audit.SendInput(
        reference=uuid4(),
        candidate_id=candidate,
        template_id="jobmitra_screening",
        intended_recipient="pooja.jobmitra@gmail.com",
        actual_recipient="pooja.jobmitra@gmail.com",
        subject="Synthetic screening test",
        html="<p>Hello Pooja Jobmitra</p>",
        plain="Hello Pooja Jobmitra",
        **extra,
    )


def test_permissions_scope_and_refresh(settings):
    assert gmail.credentials(settings).valid
    token = json.loads(settings.gmail_token_file.read_text())
    token["expiry"] = "2020-01-01T00:00:00Z"
    settings.gmail_token_file.write_text(json.dumps(token))

    def refresh(value, request):
        from datetime import datetime

        value.token = "synthetic-refreshed"
        value.expiry = datetime(2099, 1, 1)

    with patch("google.oauth2.credentials.Credentials.refresh", refresh):
        assert gmail.credentials(settings).token == "synthetic-refreshed"
    assert json.loads(settings.gmail_token_file.read_text())["token"] == "synthetic-refreshed"
    assert settings.gmail_token_file.stat().st_mode & 0o777 == 0o600
    assert not list(settings.gmail_token_file.parent.glob(".gmail-refresh-*"))
    token["scopes"].append("https://www.googleapis.com/auth/gmail.readonly")
    settings.gmail_token_file.write_text(json.dumps(token))
    assert gmail.connection_status(settings)["status"] == "Reconnect Required"


def test_revoked_token_and_safe_errors(settings):
    token = json.loads(settings.gmail_token_file.read_text())
    token["expiry"] = "2020-01-01T00:00:00Z"
    settings.gmail_token_file.write_text(json.dumps(token))
    with patch(
        "google.oauth2.credentials.Credentials.refresh", side_effect=RefreshError("private-secret")
    ):
        status = gmail.connection_status(settings)
        assert status["status"] == "Reconnect Required"
        assert "private-secret" not in str(status)


def test_known_unauthorized_token_reports_reconnect(settings):
    service = Mock()
    execute = service.users.return_value.messages.return_value.send.return_value.execute
    execute.side_effect = HttpError(Response({"status": "401"}), b"not-public")
    key = hashlib.sha256(b"synthetic-access").hexdigest()
    try:
        with patch("googleapiclient.discovery.build", return_value=service):
            with pytest.raises(gmail.GmailError):
                gmail.send(settings, "synthetic-raw")
        assert gmail.connection_status(settings)["status"] == "Reconnect Required"
    finally:
        gmail._reconnect_tokens.discard(key)


def test_concurrent_refresh_persists_one_private_token(settings):
    token = json.loads(settings.gmail_token_file.read_text())
    token["expiry"] = "2020-01-01T00:00:00Z"
    settings.gmail_token_file.write_text(json.dumps(token))

    def refresh(value, request):
        value.token = "synthetic-concurrent-refresh"
        value.expiry = datetime(2099, 1, 1)

    with patch(
        "google.oauth2.credentials.Credentials.refresh", side_effect=refresh, autospec=True
    ) as refreshing:
        with ThreadPoolExecutor(max_workers=4) as pool:
            tokens = list(pool.map(lambda _: gmail.credentials(settings).token, range(4)))
        assert tokens == ["synthetic-concurrent-refresh"] * 4
        assert refreshing.call_count == 1
    assert settings.gmail_token_file.stat().st_mode & 0o777 == 0o600


def test_hard_linked_token_is_rejected(settings):
    import os

    os.link(settings.gmail_token_file, settings.gmail_token_file.with_suffix(".hardlink"))
    assert not gmail.connection_status(settings)["enabled"]


@pytest.mark.parametrize("change", ["missing", "mode", "symlink", "directory", "client", "uri"])
def test_invalid_private_files(settings, change):
    path = settings.gmail_token_file
    if change == "missing":
        path.unlink()
    elif change == "mode":
        path.chmod(0o644)
    elif change == "symlink":
        other = path.with_suffix(".copy")
        path.rename(other)
        path.symlink_to(other)
    elif change == "directory":
        path.parent.chmod(0o755)
    else:
        token = json.loads(path.read_text())
        token["client_id" if change == "client" else "token_uri"] = "untrusted"
        path.write_text(json.dumps(token))
    assert not gmail.connection_status(settings)["enabled"]


def test_no_implicit_enabled_mode_or_lan(settings, monkeypatch):
    assert not Settings(
        _env_file=None, db_host="unused", db_name="unused", db_user="unused", db_password="unused"
    ).gmail_enabled
    for options in (
        {"office_lan_enabled": True},
        {"unified_v12_local_direct_editing": False},
        {"gmail_test_recipient": "another@example.test"},
    ):
        with pytest.raises(gmail.GmailError):
            gmail.validate_configuration(settings.model_copy(update=options))
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(gmail.GmailError):
        gmail.validate_configuration(settings)


def test_mime_branding_and_recipient_stripping(settings):
    data = draft(1, cc=["private@example.test"], bcc=["hidden@example.test"])
    data.html = (
        '<table><tr><td>Hello Pooja<img alt="Jobmitra" src="'
        + gmail.approved_logo()
        + '"></td></tr></table>'
    )
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(gmail.message(settings, data, str(data.reference)))
    )
    assert message["To"] == settings.gmail_test_recipient
    assert not message["Cc"] and not message["Bcc"]
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == data.plain
    assert "cid:jobmitra-logo" in message.get_body(preferencelist=("html",)).get_content()
    assert not list(message.iter_attachments())
    image = next(p for p in message.walk() if p.get_content_type() == "image/jpeg")
    assert image.get_content_disposition() == "inline"


@pytest.mark.parametrize(
    "html",
    [
        "<script>alert(1)</script>",
        '<img src="https://example.test/a">',
        '<p onclick="steal()">Pooja</p>',
        '<p style="background:url(https://example.test)">Pooja</p>',
    ],
)
def test_unsafe_html_rejected(settings, html):
    data = draft(1)
    data.html = html
    with pytest.raises(gmail.GmailError):
        gmail.message(settings, data, str(data.reference))


def test_send_claim_precedes_network_and_is_idempotent(settings, sample):
    engine, candidate = sample
    data = draft(candidate)

    def accepted(*args):
        with engine.connect() as conn:
            assert audit.history(conn)[0]["status"] == "Sending"
        return {"message_id": "synthetic-gmail-id", "thread_id": "synthetic-thread"}

    with patch.object(gmail, "send", side_effect=accepted) as sending:
        first = audit.dispatch(engine, settings, data)
        assert first["status"] == "Accepted by Gmail" and first["sent_by"] is None
        assert audit.dispatch(engine, settings, data)["email_reference"] == str(data.reference)
        other = data.model_copy(update={"reference": uuid4()})
        assert audit.dispatch(engine, settings, other)["email_reference"] == str(data.reference)
        assert sending.call_count == 1
    with engine.connect() as conn:
        assert len(audit.history(conn)) == 1
        assert (
            conn.scalar(
                text("SELECT count(*) FROM recruitment_events WHERE event_type LIKE 'EMAIL_SEND_%'")
            )
            == 2
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM candidates WHERE email='pooja.jobmitra@gmail.com'")
            )
            == 1
        )
        assert conn.scalar(text("SELECT count(*) FROM jd_candidates")) == 0


def test_concurrent_duplicates_and_explicit_resend(settings, sample):
    engine, candidate = sample
    data = draft(candidate)
    with patch.object(
        gmail, "send", return_value={"message_id": "synthetic", "thread_id": None}
    ) as sending:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda _: audit.dispatch(
                        engine, settings, data.model_copy(update={"reference": uuid4()})
                    ),
                    range(4),
                )
            )
        assert len({e["email_reference"] for e in results}) == 1
        assert sending.call_count == 1
        parent = UUID(results[0]["email_reference"])
        data = data.model_copy(
            update={"reference": uuid4(), "resend_of": parent, "confirm_resend": True}
        )
        audit.dispatch(engine, settings, data)
        audit.dispatch(engine, settings, data.model_copy(update={"reference": uuid4()}))
        assert sending.call_count == 2


@pytest.mark.parametrize("unknown", [True, False])
def test_failures_never_automatically_retry(settings, sample, unknown):
    engine, candidate = sample
    data = draft(candidate)
    with patch.object(
        gmail, "send", side_effect=gmail.GmailError("Sanitized failure", unknown=unknown)
    ) as sending:
        result = audit.dispatch(engine, settings, data)
        assert result["status"] == ("Send outcome unknown" if unknown else "Failed")
        audit.dispatch(engine, settings, data)
        assert sending.call_count == 1


def test_result_persistence_failure_never_authorizes_automatic_resend(settings, sample):
    engine, candidate = sample
    data = draft(candidate)
    append = audit._append

    def failing_result(conn, kind, entry):
        if kind == audit.RESULT:
            raise RuntimeError("synthetic database outage after acceptance")
        append(conn, kind, entry)

    with patch.object(
        gmail, "send", return_value={"message_id": "mock", "thread_id": None}
    ) as sending:
        with (
            patch.object(audit, "_append", side_effect=failing_result),
            pytest.raises(RuntimeError),
        ):
            audit.dispatch(engine, settings, data)
        assert audit.dispatch(engine, settings, data)["status"] == "Sending"
        assert sending.call_count == 1

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(minutes=3)

    with patch.object(audit, "datetime", Later), engine.connect() as conn:
        assert audit.history(conn)[0]["status"] == "Send outcome unknown"


def test_canonical_jd_history_keeps_membership_and_company_context(settings, sample, store):
    engine, candidate = sample
    job, _ = unified_tests.requirement(store)
    link = jobs.associate(engine, job, candidate)
    settings = settings.model_copy(update={"gmail_test_job_ids": str(job)})
    data = draft(candidate, job_id=job, company_id=UUID(store[1]))
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT * FROM jd_candidates WHERE id=:id"), {"id": link["id"]}
        ).one()
    with patch.object(gmail, "send", return_value={"message_id": "mock-jd", "thread_id": None}):
        result = audit.dispatch(engine, settings, data)
    assert result["job_id"] == job and result["jd_candidate_id"] == link["id"]
    assert result["company_id"] == store[1]
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT * FROM jd_candidates WHERE id=:id"), {"id": link["id"]}).one()
            == before
        )


def test_context_and_recipient_guards(settings, sample, store):
    engine, candidate = sample
    invalid = [
        draft(store[3]),
        draft(candidate).model_copy(update={"actual_recipient": "bad@example.test"}),
        draft(candidate).model_copy(update={"intended_recipient": "bad@example.test"}),
        draft(candidate).model_copy(update={"template_id": "candidate_submission"}),
        draft(candidate).model_copy(update={"job_id": 999}),
        draft(candidate).model_copy(update={"company_id": uuid4()}),
    ]
    with patch.object(gmail, "send") as sending:
        for data in invalid:
            with pytest.raises(AtsError):
                audit.dispatch(engine, settings, data)
        sending.assert_not_called()
    with engine.connect() as conn:
        assert not audit.history(conn)


@pytest.mark.parametrize("template", sorted(audit.TEMPLATES))
def test_all_candidate_templates_mocked(settings, sample, template):
    engine, candidate = sample
    data = draft(candidate).model_copy(update={"template_id": template})
    with patch.object(gmail, "send", return_value={"message_id": "mock-id", "thread_id": None}):
        assert audit.dispatch(engine, settings, data)["template_id"] == template


def test_transport_uses_me_and_zero_api_retries(settings):
    service = Mock()
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "mock-id"
    }
    with (
        patch.object(gmail, "credentials", return_value=Mock(token="not-real")),
        patch("googleapiclient.discovery.build", return_value=service),
    ):
        assert gmail.send(settings, "synthetic-raw")["message_id"] == "mock-id"
    service.users().messages().send.assert_called_once_with(
        userId="me", body={"raw": "synthetic-raw"}
    )
    service.users().messages().send().execute.assert_called_once_with(num_retries=0)


def test_transport_socket_failure_is_not_retried():
    with patch("http.client.HTTPSConnection") as connection:
        connection.return_value.getresponse.side_effect = ConnectionResetError("sensitive")
        with pytest.raises(ConnectionResetError):
            gmail._SingleRequestHTTP("synthetic").request(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                method="POST",
                body="{}",
            )
        assert connection.return_value.request.call_count == 1


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_google_errors_are_sanitized_and_never_retried(settings, status):
    service = Mock()
    execute = service.users.return_value.messages.return_value.send.return_value.execute
    execute.side_effect = HttpError(Response({"status": str(status)}), b"private-body-and-secret")
    with (
        patch.object(gmail, "credentials", return_value=Mock(token="synthetic")),
        patch("googleapiclient.discovery.build", return_value=service),
        pytest.raises(gmail.GmailError) as error,
    ):
        gmail.send(settings, "synthetic-raw")
    assert error.value.unknown == (status >= 500)
    assert error.value.reconnect == (status == 401)
    assert "private-body" not in error.value.reason
    execute.assert_called_once_with(num_retries=0)


def test_actual_discovery_send_path_uses_one_transport_request(settings):
    with (
        patch.object(gmail, "credentials", return_value=Mock(token="synthetic")),
        patch("http.client.HTTPSConnection") as connection,
    ):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = [("content-type", "application/json")]
        response.read.return_value = b'{"id":"mock-discovery-id","threadId":"mock-thread"}'
        assert gmail.send(settings, "synthetic-raw")["message_id"] == "mock-discovery-id"
        assert connection.return_value.request.call_count == 1
        args = connection.return_value.request.call_args
        assert args.args[0] == "POST" and "/users/me/messages/send" in args.args[1]


def test_compressed_gmail_acceptance_is_decoded_without_resending(settings):
    with (
        patch.object(gmail, "credentials", return_value=Mock(token="synthetic")),
        patch("http.client.HTTPSConnection") as connection,
    ):
        response = connection.return_value.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = [
            ("Content-Type", "application/json"),
            ("Content-Encoding", "gzip"),
        ]
        response.read.return_value = gzip.compress(b'{"id":"mock-compressed-id"}')
        assert gmail.send(settings, "synthetic-raw")["message_id"] == "mock-compressed-id"
        assert connection.return_value.request.call_count == 1


def test_api_guards_without_touching_running_app(settings, sample, monkeypatch):
    engine, candidate = sample
    # Only bypass startup path checks for this synthetic fixture outside runtime/.
    monkeypatch.setattr("jobmitra.core.local_v12.validate_direct_editing", lambda _: None)
    settings = settings.model_copy(update={"ats_v2_database": Path(engine.url.database)})
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(
            create_app(settings), base_url="http://127.0.0.1", client=("127.0.0.1", 40000)
        ) as client,
    ):
        assert client.get("/api/v12/gmail/status").json()["enabled"]
        data = draft(candidate)
        body = data.model_dump(mode="json")
        assert client.post("/api/v12/gmail/send", json=body).status_code == 403
        headers = {
            "Origin": "http://127.0.0.1",
            "X-Jobmitra-UI": "1",
            "Idempotency-Key": str(data.reference),
        }
        with patch.object(
            gmail, "send", return_value={"message_id": "mock-api", "thread_id": None}
        ):
            response = client.post("/api/v12/gmail/send", json=body, headers=headers)
            assert response.status_code == 200, response.text
        assert len(client.get(f"/api/v12/gmail/history/{candidate}").json()["items"]) == 1
        assert (
            client.post(
                "/api/v12/gmail/send", json=body, headers={**headers, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v12/gmail/status", headers={"X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 403
        )
