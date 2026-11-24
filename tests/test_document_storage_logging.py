"""Actual route logging with synthetic API failures; no live server/database writes."""

import ctypes
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from jobmitra.modules.ats_v2 import proposal_windows as win
from jobmitra.modules.ats_v2 import storage_diagnostics as diagnostic
from jobmitra.modules.ats_v2.router import AtsRoute

RESUME = "/api/ats-v2/candidates/{candidate_id}/resumes"
PROPOSAL = "/api/v12/approved/companies/{company_id}/proposals"
SETTINGS = SimpleNamespace(
    ats_v2_resume_storage_root="D:/JobmitraData/resumes",
    unified_v12_proposal_storage_root="D:/JobmitraData/proposals",
)


def request():
    return SimpleNamespace(
        method="POST", app=SimpleNamespace(state=SimpleNamespace(settings=SETTINGS))
    )


def events(caplog):
    return [
        json.loads(r.getMessage().split("document_storage_failure ", 1)[1])
        for r in caplog.records
        if "document_storage_failure " in r.getMessage()
    ]


def api_with_acl(protected=True, owner=win.ADMINS):
    api = object.__new__(win.Win32)
    api.actor = win.SYSTEM
    acl = win.Acl()
    acl.count = 1
    ace = ctypes.create_string_buffer(20)
    ctypes.c_uint16.from_buffer(ace, 2).value = 20
    win.D.from_buffer(ace, 4).value = 0x1F01FF

    def get_security(handle, kind, flags, out_owner, group, dacl, sacl, descriptor):
        ctypes.cast(out_owner, ctypes.POINTER(win.P)).contents.value = 123
        ctypes.cast(dacl, ctypes.POINTER(win.P)).contents.value = ctypes.addressof(acl)
        ctypes.cast(descriptor, ctypes.POINTER(win.P)).contents.value = 456
        return 0

    def control(descriptor, out, revision):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_uint16)).contents.value = (
            0x1000 if protected else 0
        )
        return True

    def get_ace(dacl, index, out):
        ctypes.cast(out, ctypes.POINTER(win.P)).contents.value = ctypes.addressof(ace)
        return True

    api.k = SimpleNamespace(LocalFree=Mock())
    api.a = SimpleNamespace(
        GetSecurityInfo=get_security,
        GetSecurityDescriptorControl=control,
        GetAce=get_ace,
        IsValidSid=lambda p: True,
        GetLengthSid=lambda p: 12,
    )
    api.sid = lambda p: owner if p.value == 123 else win.SYSTEM
    return api


@pytest.mark.parametrize("route", [RESUME, PROPOSAL])
@pytest.mark.parametrize(
    "protected,owner,reason",
    [
        (False, win.ADMINS, "unprotected_dacl"),
        (True, "S-1-5-21-100-1001", "untrusted_owner"),
    ],
)
def test_actual_503_route_logs_native_acl_state_from_threadpool(
    route, protected, owner, reason, caplog
):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    api = api_with_acl(protected, owner)
    app = FastAPI()
    app.router.route_class = AtsRoute
    app.state.settings = SETTINGS

    def fail():
        diagnostic.note(acl_target="directory")
        api.private(1)

    app.add_api_route(route, fail, methods=["POST"])
    url = route.replace("{candidate_id}", "987654321").replace("{company_id}", "PRIVATE_COMPANY")
    with TestClient(app) as client:
        response = client.post(
            url,
            content=b"PRIVATE_DOCUMENT_BYTES",
            headers={"X-Resume-Filename": "PRIVATE_CANDIDATE.pdf"},
        )
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Windows proposal storage requires a protected private ACL."
    }
    (event,) = events(caplog)
    assert event["operation"] == ("resume.post" if route == RESUME else "proposal.post")
    assert event["storage_root"] == (
        SETTINGS.ats_v2_resume_storage_root
        if route == RESUME
        else SETTINGS.unified_v12_proposal_storage_root
    )
    assert event["process_sid"] == win.SYSTEM
    assert event["owner_sid"] == owner and event["owner_valid"] == (owner == win.ADMINS)
    assert event["acl_protected"] == protected
    assert event["validation_stage"] == "private_acl"
    assert event["validation_reason"] == reason
    assert event["original_exception_type"] == "AtsError"
    assert event["sanitized_traceback"]
    for private in ["PRIVATE_DOCUMENT_BYTES", "PRIVATE_COMPANY", "987654321", "PRIVATE_CANDIDATE"]:
        assert private not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)
    assert diagnostic.CURRENT.get() is None


def test_direct_security_error_code_logged_even_if_getlasterror_differs(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 32, raising=False)
    api = object.__new__(win.Win32)
    api.a = SimpleNamespace(GetSecurityInfo=Mock(return_value=5))
    token = diagnostic.begin(request(), RESUME)
    try:
        with pytest.raises(OSError) as failure:
            api.private(1)
        assert failure.value.errno == 32  # Original application's exception is unchanged.
        diagnostic.emit(failure.value)
    finally:
        diagnostic.end(token)
    (event,) = events(caplog)
    assert event["windows_error_code"] == 5 and event["native_api"] == "GetSecurityInfo"
    assert event["validation_stage"] == "Win32.private"
    assert event["acl_protected"] is None  # Not inspected, never fabricated.


def test_createfile_error_captured_before_security_descriptor_cleanup(monkeypatch, caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    last_error = [0]
    monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error[0], raising=False)
    api = object.__new__(win.Win32)

    @contextmanager
    def security():
        try:
            yield win.SecurityAttributes()
        finally:
            last_error[0] = 0  # Simulate LocalFree clobbering the native failure.

    def create(*args):
        last_error[0] = 5
        return win.P(-1).value

    api.security = security
    api.k = SimpleNamespace(CreateFileW=create)
    token = diagnostic.begin(request(), PROPOSAL)
    try:
        with pytest.raises(OSError) as failure:
            with api.open("PRIVATE_LEAF_MUST_NOT_BE_LOGGED", create=True):
                pytest.fail("Unexpected successful open")
        diagnostic.emit(failure.value)
    finally:
        diagnostic.end(token)
    (event,) = events(caplog)
    assert event["windows_error_code"] == 5 and event["native_api"] == "CreateFileW"
    assert event["validation_stage"] == "Win32.open"
    assert "PRIVATE_LEAF" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        OSError(5, "PRIVATE_DOCUMENT postgres://USER:PASSWORD@server PRIVATE_CANDIDATE"),
        OperationalError("PRIVATE_SQL", {"password": "PASSWORD"}, Exception("PRIVATE_CANDIDATE")),
    ],
)
def test_database_and_os_failure_messages_and_parameters_never_logged(error, caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    app = FastAPI()
    app.router.route_class = AtsRoute
    app.state.settings = SETTINGS

    def fail():
        raise error

    app.add_api_route(RESUME, fail, methods=["POST"])
    with TestClient(app) as client:
        assert client.post(RESUME.replace("{candidate_id}", "987654321")).status_code == 503
    (event,) = events(caplog)
    assert event["original_exception_type"] == type(error).__name__
    for private in ["PRIVATE_SQL", "PASSWORD", "PRIVATE_DOCUMENT", "PRIVATE_CANDIDATE"]:
        assert private not in caplog.text


def test_logging_sink_failure_does_not_replace_http_503(monkeypatch):
    monkeypatch.setattr(diagnostic.LOGGER, "error", Mock(side_effect=OSError("log sink failed")))
    app = FastAPI()
    app.router.route_class = AtsRoute
    app.state.settings = SETTINGS

    def fail():
        raise OSError(5, "do not dump")

    app.add_api_route(RESUME, fail, methods=["POST"])
    with TestClient(app) as client:
        response = client.post(RESUME.replace("{candidate_id}", "987654321"))
    assert response.status_code == 503
    assert response.json() == {"detail": "ATS storage is unavailable. No change was confirmed."}
    assert diagnostic.CURRENT.get() is None


def test_primary_failure_is_preserved_before_secondary_cleanup_failure(caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    token = diagnostic.begin(request(), PROPOSAL)
    try:
        try:
            raise OperationalError("PRIVATE_SQL", {}, Exception("PRIVATE_DRIVER_DATA"))
        except OperationalError as primary:
            diagnostic.capture("proposal_documents.generate", primary)
            try:
                raise OSError(5, "PRIVATE_CLEANUP_PATH")
            except OSError as secondary:
                diagnostic.capture("Win32.delete", secondary)
            diagnostic.emit(primary)
    finally:
        diagnostic.end(token)
    (event,) = events(caplog)
    assert event["original_exception_type"] == "OperationalError"
    assert event["validation_stage"] == "proposal_documents.generate"
    assert "PRIVATE_" not in caplog.text


def test_concurrent_request_diagnostic_contexts_do_not_mix(caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    def fail(route):
        token = diagnostic.begin(request(), route)
        try:
            diagnostic.emit(OSError(5, "not logged"))
        finally:
            diagnostic.end(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fail, [RESUME, PROPOSAL]))
    records = events(caplog)
    assert len({e["event_id"] for e in records}) == 2
    assert {(e["operation"], e["storage_root"]) for e in records} == {
        ("resume.post", SETTINGS.ats_v2_resume_storage_root),
        ("proposal.post", SETTINGS.unified_v12_proposal_storage_root),
    }


def test_non_document_routes_do_not_create_storage_logs(caplog):
    assert diagnostic.begin(request(), "/api/v12/approved/state") is None
    diagnostic.emit(OSError(5, "secret"))
    assert not events(caplog)


def test_uri_like_root_is_redacted(caplog):
    caplog.set_level(logging.ERROR, logger="uvicorn.error")
    req = request()
    req.app = SimpleNamespace(
        state=SimpleNamespace(
            settings=SimpleNamespace(ats_v2_resume_storage_root="postgresql:/USER:PASSWORD@server")
        )
    )
    token = diagnostic.begin(req, RESUME)
    try:
        diagnostic.emit(OSError(5, "secret"))
    finally:
        diagnostic.end(token)
    (event,) = events(caplog)
    assert event["storage_root"] == "[invalid URI root redacted]"
    assert "PASSWORD" not in caplog.text
