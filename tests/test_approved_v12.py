"""Approved UI service adapters: isolated SQLite, synthetic identities and files only."""

import base64
import hashlib
import json
import re
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_unified_v12 import HEADERS, OPERATOR, requirement, snapshot
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.core.config import Settings
from jobmitra.main import create_app
from jobmitra.modules.ats_v2 import jobs, resumes, unified

PDF = b"%PDF-1.4\nsynthetic approval evidence\n%%EOF"


@pytest.fixture
def client(store):
    root = store[-1]
    config = Settings(
        _env_file=None,
        db_host="127.0.0.1",
        db_port=9,
        db_name="unused",
        db_user="unused",
        db_password="unused",
        ats_v2_enabled=True,
        ats_v2_database=root / "isolated.sqlite3",
        ats_v2_resume_storage_root=root / "resumes",
        unified_v12_enabled=True,
        unified_v12_operator_token=OPERATOR,
    )
    with (
        patch("jobmitra.main.build_engine", return_value=Mock()),
        TestClient(create_app(config)) as c,
    ):
        c.headers.update(HEADERS)
        assert c.post("/api/v12/access", json={"token": OPERATOR}).status_code == 200
        yield c


def headers():
    return {"Idempotency-Key": str(uuid4())}


def test_approved_shell_and_bootstrap_do_not_mutate_canonical_records(client, store):
    before = snapshot(store[0])
    for area in ("companies", "candidates", "jobs"):
        response = client.get("/workspace-v12/" + area)
        assert response.status_code == 200
        assert f'data-section="{area}"' in response.text
        assert "/static/ats-v2/approved.mjs" in response.text
    data = client.get("/api/v12/approved/state").json()
    assert [p["id"] for p in data["candidates"]] == [store[3]]
    assert data["companies"][0]["id"] == store[1]
    names = client.get('/api/v12/approved/search?keywords="Synthetic Candidate"').json()
    assert [p["id"] for p in names["items"]] == [store[3]]
    assert snapshot(store[0]) == before


def test_approved_registration_upload_is_atomic_and_retry_safe(client, store):
    body = {
        "candidate": {"full_name": "Separate Canonical Person", "phone": "9876543210"},
        "filename": "original.pdf",
        "file_base64": base64.b64encode(PDF).decode(),
    }
    key = headers()
    first = client.post("/api/v12/approved/registration", headers=key, json=body)
    assert first.status_code == 201, first.text
    cid = first.json()["id"]
    assert client.post("/api/v12/approved/registration", headers=key, json=body).json()["id"] == cid
    files = client.get(f"/api/ats-v2/candidates/{cid}/resumes").json()
    assert len(files) == 1
    assert (
        client.get(f"/api/ats-v2/candidates/{cid}/resumes/{files[0]['id']}/download").content == PDF
    )
    assert len(list((store[-1] / "resumes").rglob("*.pdf"))) == 1
    before = snapshot(store[0])
    with patch.object(resumes, "_publish", side_effect=OSError("synthetic failure")):
        other = {**body, "candidate": {"full_name": "Failed registration", "phone": "9876543211"}}
        assert (
            client.post("/api/v12/approved/registration", headers=headers(), json=other).status_code
            == 503
        )
    assert snapshot(store[0]) == before
    assert (
        client.post("/api/v12/approved/registration", headers=headers(), json=body).status_code
        == 409
    )
    distinct = client.post(
        "/api/v12/approved/registration", headers=headers(), json={**body, "allow_duplicate": True}
    )
    assert distinct.status_code == 201 and distinct.json()["id"] != cid


def test_company_contact_edits_retain_identity_and_removed_evidence(client, store):
    cid, contact = store[1:3]
    body = {
        "idempotency_key": str(uuid4()),
        "actor_name": "Declared reviewer",
        "expected_revision": client.get("/api/v12/approved/state").json()["companies"][0][
            "revision"
        ],
        "name": "Synthetic renamed client",
        "contacts": [
            {
                "id": contact,
                "name": "HR Edited",
                "email": "hr@example.test",
                "phone": "0123\n0456",
                "primary": True,
            }
        ],
    }
    response = client.patch("/api/v12/approved/companies/" + cid, headers=headers(), json=body)
    assert response.status_code == 200, response.text
    current = client.get("/api/v12/companies/" + cid).json()
    assert current["contacts"][0]["id"] == contact
    assert current["contacts"][0]["created_at"] == "2020-01-01T00:00:00Z"
    assert current["contacts"][0]["phone_numbers"] == ["0123", "0456"]
    before = snapshot(store[0])
    assert (
        client.patch("/api/v12/approved/companies/" + cid, headers=headers(), json=body).status_code
        == 200
    )
    assert snapshot(store[0]) == before
    # New request from an older form must never overwrite newer company/contact values.
    stale = {**body, "idempotency_key": str(uuid4()), "name": "Stale overwrite"}
    assert (
        client.patch(
            "/api/v12/approved/companies/" + cid, headers=headers(), json=stale
        ).status_code
        == 409
    )
    assert snapshot(store[0]) == before
    body["expected_revision"] = client.get("/api/v12/approved/state").json()["companies"][0][
        "revision"
    ]
    jid, _ = requirement(store)
    choice = {
        "idempotency_key": str(uuid4()),
        "actor_name": "Declared reviewer",
        "contact_id": contact,
    }
    assert client.put(f"/api/v12/jobs/{jid}/contact", json=choice).status_code == 200
    removed = {**body, "idempotency_key": str(uuid4()), "contacts": [], "archive": True}
    assert (
        client.patch(
            "/api/v12/approved/companies/" + cid, headers=headers(), json=removed
        ).status_code
        == 200
    )
    current = client.get("/api/v12/companies/" + cid).json()
    assert current["contacts"][0]["id"] == contact and current["contacts"][0]["is_archived"]
    assert not current["is_active"]
    # Historical contact snapshots remain, but archived recipients cannot be selected or prefilled.
    saved_job = client.get(f"/api/ats-v2/jobs/{jid}").json()
    assert saved_job["company_contact_id"] == contact
    assert saved_job["company_contact_email_snapshot"] == "hr@example.test"
    assert (
        client.get(
            "/api/v12/email-context",
            params={"candidate_id": store[3], "job_id": jid, "audience": "COMPANY"},
        ).status_code
        == 422
    )
    candidate_context = client.get(
        "/api/v12/email-context",
        params={"candidate_id": store[3], "job_id": jid, "audience": "CANDIDATE"},
    )
    assert candidate_context.status_code == 200
    assert candidate_context.json()["recipient_email"] == "candidate@example.test"
    choice["idempotency_key"] = str(uuid4())
    assert client.put(f"/api/v12/jobs/{jid}/contact", json=choice).status_code == 422

    bad = {
        **body,
        "expected_revision": client.get("/api/v12/approved/state").json()["companies"][0][
            "revision"
        ],
        "idempotency_key": str(uuid4()),
        "contacts": [{**body["contacts"][0], "id": str(uuid4())}],
    }
    assert (
        client.patch("/api/v12/approved/companies/" + cid, headers=headers(), json=bad).status_code
        == 422
    )


def test_parsed_approval_preserves_exact_raw_json_and_only_selected_fields(client, store):
    cid = store[3]
    original = resumes.upload_resume(
        store[0], cid, store[-1] / "resumes", PDF, "original.pdf", 10000
    )
    raw = (
        '{\n  "name": "Other Name", "skills": ["NativeReviewEvidence"], '
        '"private_original": {"keep": 1}\n}'
    )
    body = {
        "idempotency_key": str(uuid4()),
        "actor_name": "Declared reviewer",
        "source_resume_id": original["id"],
        "raw_json": raw,
        "approved": ["skills", "extra:projects"],
        "changes": {"skills": ["Python", "NativeReviewEvidence"]},
        "professional_extras": {"projects": ["Reviewed app project"]},
    }
    path = f"/api/v12/approved/candidates/{cid}/parsed"
    assert client.post(path, headers=headers(), json=body).status_code == 422
    response = client.post(path, headers=headers(), json={**body, "identity_confirmed": True})
    assert response.status_code == 200, response.text
    rid = response.json()["resume_id"]
    stored = client.get(path + f"/{rid}").json()
    assert stored["original_json_text"] == raw
    person = client.get(f"/api/ats-v2/candidates/{cid}").json()
    assert person["full_name"] == "Synthetic Candidate" and person["skills"] == [
        "Python",
        "NativeReviewEvidence",
    ]
    matches = client.get("/api/ats-v2/candidates?keywords=Reviewed%20app%20project").json()
    assert any(p["id"] == cid for p in matches["items"])
    before = snapshot(store[0])
    assert (
        client.post(path, headers=headers(), json={**body, "identity_confirmed": True}).status_code
        == 200
    )
    assert snapshot(store[0]) == before
    illegal = {
        **body,
        "idempotency_key": str(uuid4()),
        "changes": {"full_name": "Silent replacement"},
        "approved": ["full_name"],
    }
    assert client.post(path, headers=headers(), json=illegal).status_code == 422
    assert client.get(f"/api/v12/approved/candidates/{cid + 100}/parsed/{rid}").status_code == 404


def test_activity_schedule_and_manual_status_are_persistent_not_delivery(client, store):
    jid, _ = requirement(store)
    cid = store[3]
    body = {
        "job_id": jid,
        "activity_type": "INTERVIEW",
        "due_at": "2026-12-01T10:30:00+05:30",
        "details": {"kind": "INTERVIEW_SCHEDULED", "mode": "VIDEO", "invitation_sent": False},
        "notes": "Confirmed schedule",
    }
    key = headers()
    path = f"/api/v12/approved/candidates/{cid}/activity"
    first = client.post(path, headers=key, json=body)
    assert first.status_code == 200, first.text
    assert client.post(path, headers=key, json=body).json()["id"] == first.json()["id"]
    data = client.get("/api/v12/approved/state").json()
    assert data["activities"][0]["details"]["invitation_sent"] is False
    assert data["activities"][0]["due_at"].endswith("+05:30")
    before = snapshot(store[0])
    bad = {**body, "job_id": jid + 100}
    assert client.post(path, headers=headers(), json=bad).status_code == 409
    assert snapshot(store[0]) == before


def test_approved_css_is_copied_exactly_and_original_hash_is_unchanged():
    root = Path(__file__).parents[1]
    data = (root / "Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html").read_bytes()
    assert (
        hashlib.sha256(data).hexdigest()
        == "a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e"
    )
    source = data.decode()
    generated = (root / "src/jobmitra/static/ats_v2/approved.mjs").read_text()
    for area in ("company", "candidate", "jd"):
        pattern = area + r'Shadow\.innerHTML = ("(?:\\.|[^"\\])*");'
        original = json.loads(re.search(pattern, source).group(1))
        integrated = json.loads(re.search(pattern, generated).group(1))
        assert re.findall(r"<style>(.*?)</style>", original, re.S) == re.findall(
            r"<style>(.*?)</style>", integrated, re.S
        )
        if area != "jd":
            assert re.findall(r'\bid="([^"]+)"', original) == re.findall(
                r'\bid="([^"]+)"', integrated
            )
        else:
            assert "jd-clean.css" in integrated
            assert 'id="versionPill"' not in integrated
            assert 'id="editJDBtn"' not in integrated
    assert "localStorage." not in generated and "indexedDB." not in generated


def test_outcome_and_typed_feedback_commit_together_and_retry_once(client, store):
    jid, lid = requirement(store)
    key = str(uuid4())
    body = {
        "idempotency_key": key,
        "actor_name": "Declared reviewer",
        "action": "SELECT",
        "effective_on": unified.office_today().isoformat(),
        "feedback": "Confirmed by hiring team",
        "feedback_source": "COMPANY",
    }
    path = f"/api/v12/approved/jobs/{jid}/candidates/{lid}/outcome"
    before = snapshot(store[0])
    with patch.object(jobs, "add_feedback", side_effect=OSError("Synthetic feedback failure")):
        assert client.post(path, headers={"Idempotency-Key": key}, json=body).status_code == 503
    assert snapshot(store[0]) == before
    assert client.post(path, headers={"Idempotency-Key": key}, json=body).status_code == 200
    events = client.get(f"/api/ats-v2/history?job_id={jid}").json()["items"]
    assert sum(e["event_type"] == "COMPANY_SELECTED" for e in events) == 1
    assert sum(e.get("feedback") == body["feedback"] for e in events) == 1
    before = snapshot(store[0])
    assert client.post(path, headers={"Idempotency-Key": key}, json=body).status_code == 200
    assert snapshot(store[0]) == before
    assert (
        client.post(
            path, headers={"Idempotency-Key": key}, json={**body, "feedback": "Different"}
        ).status_code
        == 409
    )
