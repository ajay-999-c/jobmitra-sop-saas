"""Complete Candidate Desk services: real private files and isolated canonical SQLite only."""

import hashlib
import json
from uuid import uuid4

import pytest
from pdf_fixture import valid_pdf
from sqlalchemy import text
from test_approved_v12 import client as client
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.modules.ats_v2 import candidates, profile_store
from jobmitra.modules.ats_v2.database import transaction, validate


@pytest.fixture
def complete(client, store):
    profile_store.install(store[0])
    return client


def path(store):
    return f"/api/v12/approved/candidates/{store[3]}/profile"


def change(client, store, changes=None, extra=None, **kwargs):
    current = client.get(path(store)).json()
    core, extra = changes or {}, extra or {}
    data = {
        "changes": core,
        "extra": extra,
        "approved_fields": list(core) + ["extra:" + k for k in extra],
        "actor_name": "Synthetic reviewer",
        "expected_revision": current.get("revision", "a" * 64),
        "idempotency_key": str(uuid4()),
        **kwargs,
    }
    return client.patch(
        path(store), json=data, headers={"Idempotency-Key": data["idempotency_key"]}
    ), data


def test_complete_fields_precision_months_audit_and_search(complete, store):
    cid = store[3]
    with store[0].connect() as c:
        before = dict(
            c.execute(text("SELECT * FROM candidates WHERE id=:c"), {"c": cid}).mappings().one()
        )
    core = {
        "full_name": "Synthetic Revised Name",
        "phone": "9876554321",
        "email": "reviewed@example.test",
        "links": {"LinkedIn": "https://linkedin.com/in/example"},
        "current_city": "Pune",
        "preferred_cities": ["Pune", "Indore"],
        "job_title": "Senior Engineer",
        "current_employer": "Fictional Works",
        "qualification": "M.Tech",
        "primary_domain": "Engineering",
        "skills": ["ExactServiceSkill"],
        "professional_summary": "Reviewed experience",
        "availability": "AVAILABLE",
        "source": "FOUNDIT_PASTE",
        "current_salary_inr": "12345.6789",
        "current_salary_period": "MONTHLY",
        "current_salary_basis": "IN_HAND",
        "expected_salary_inr": "250000.75",
        "expected_salary_period": "ANNUAL",
        "expected_salary_basis": "GROSS",
        "notice_days": 17,
    }
    extra = {
        "hometown": "Indore",
        "home_state": "MP",
        "subdomain": "Automation",
        "experience_months": 49,
        "ready_to_relocate": False,
        "notice_period_text": "17 days after discussion",
        "employment_history": [
            {
                "employer": "Past Fictional",
                "job_title": "PrecisionHistorySkill",
                "start_date": "2020-01",
                "end_date": "2022-04",
                "responsibilities": "Review only",
                "achievements": "Confirmed",
            }
        ],
        "education_history": [
            {
                "qualification": "M.Tech",
                "institution": "Fictional University",
                "start_year": 2015,
                "end_year": 2017,
            }
        ],
        "certifications": [
            {"name": "Fictional Certificate", "issuer": "Example", "issued_on": "2021"}
        ],
        "projects": [{"name": "Fictional Project", "role": "Lead", "description": "Reviewed"}],
    }
    response, _ = change(complete, store, core, extra, notice_days_verified=True)
    assert response.status_code == 200, response.text
    actual = complete.get(path(store)).json()
    for k, v in core.items():
        assert actual["candidate"][k] == v, (k, actual["candidate"][k])
    assert actual["extra"]["experience_months"] == 49
    assert actual["candidate"]["experience_years"] == 49 / 12
    assert (
        candidates.search_candidates(
            store[0],
            __import__(
                "jobmitra.modules.ats_v2.candidate_schemas", fromlist=["SearchParams"]
            ).SearchParams(keywords="PrecisionHistorySkill"),
        )["total"]
        == 1
    )
    with store[0].connect() as c:
        now = dict(
            c.execute(text("SELECT * FROM candidates WHERE id=:c"), {"c": cid}).mappings().one()
        )
        assert (
            now["id"] == before["id"] and now["legacy_postgres_id"] == before["legacy_postgres_id"]
        )
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM recruitment_events "
                    "WHERE event_type='CANDIDATE_PROFILE_REVIEWED'"
                )
            )
            == 1
        )
    history = complete.get(path(store) + "-history").json()
    assert len(history) == 1 and "before_json" in history[0] and "after_json" in history[0]
    validate(store[0])


def test_omitted_fields_explicit_clear_stale_and_retry(complete, store):
    with transaction(store[0]) as c:
        c.execute(
            text("UPDATE candidates SET current_salary_inr=12345.675 WHERE id=:c"), {"c": store[3]}
        )
    old = complete.get(path(store)).json()
    response, data = change(complete, store, {"job_title": "Reviewed"})
    assert response.status_code == 200, response.text
    assert complete.get(path(store)).json()["candidate"]["current_salary_inr"] == "12345.675"
    assert (
        complete.patch(
            path(store), json=data, headers={"Idempotency-Key": data["idempotency_key"]}
        ).status_code
        == 200
    )
    stale = {**data, "idempotency_key": str(uuid4()), "expected_revision": old["revision"]}
    assert (
        complete.patch(
            path(store), json=stale, headers={"Idempotency-Key": stale["idempotency_key"]}
        ).status_code
        == 409
    )
    response, _ = change(
        complete, store, {"phone": None, "links": {}, "skills": []}, {"hometown": None}
    )
    assert response.status_code == 200
    now = complete.get(path(store)).json()
    assert (
        now["candidate"]["phone"] is None
        and now["candidate"]["links"] == {}
        and now["extra"]["hometown"] is None
    )


@pytest.mark.parametrize(
    "core,extra",
    [
        ({"phone": 123}, {}),
        ({"email": "not an email"}, {}),
        ({"current_salary_inr": "1.123456"}, {}),
        ({"links": {"x": "javascript:alert(1)"}}, {}),
        ({"notice_days": 12}, {}),
        (
            {},
            {
                "employment_history": [
                    {
                        "employer": "X",
                        "job_title": "Y",
                        "start_date": "2024-12",
                        "end_date": "2023-02",
                    }
                ]
            },
        ),
    ],
)
def test_bad_edits_do_not_write(complete, store, core, extra):
    before = complete.get(path(store)).json()
    r, _ = change(complete, store, core, extra)
    assert r.status_code == 422, r.text
    assert complete.get(path(store)).json() == before


def test_profile_authorization_and_approval_required(complete, store):
    r, _ = change(complete, store, {"job_title": "unapproved"}, approved_fields=[])
    assert r.status_code == 422
    complete.cookies.clear()
    assert complete.get(path(store)).status_code == 403
    r, _ = change(complete, store, {"job_title": "Unauthorized"}, expected_revision="a" * 64)
    assert r.status_code == 403


def test_foundit_preview_registration_duplicates_and_enrichment(complete, store):
    raw = (
        "Name: Foundit Synthetic Person\n"
        "Mobile: 9876556789\n"
        "Email: foundit@example.test\n"
        "Current Designation: QA Engineer\n"
        "Current Company: Example Works\n"
        "Experience: 4 years 1 month\n"
        "Current CTC: 4.50 LPA\n"
        "Expected CTC: 6.25 LPA\n"
        "Current Location: Pune\n"
        "Preferred Locations: Pune, Indore\n"
        "Notice Period: Serving 20 days\n"
        "Skills: FounditReviewSkill, Python\n"
        "Qualification: B.Tech\n"
        "Professional Summary: Reviewed test profile"
    )
    preview = complete.post(
        "/api/v12/approved/foundit/preview",
        json={"raw": raw},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["candidate"]["current_employer"] == "Example Works"
    assert p["candidate"]["expected_salary_inr"] == "625000.00"
    assert p["extra"]["experience_months"] == 49
    assert not p["raw_text_persisted"]
    request = {
        "candidate": p["candidate"],
        "extra": p["extra"],
        "source_digest": p["source_digest"],
        "actor_name": "Reviewed by test",
        "confirmed": True,
        "idempotency_key": str(uuid4()),
    }
    save = complete.post(
        "/api/v12/approved/foundit/candidates",
        json=request,
        headers={"Idempotency-Key": request["idempotency_key"]},
    )
    assert save.status_code == 201, save.text
    record = save.json()
    cid = record["candidate"]["id"]
    assert record["candidate"]["source"] == "FOUNDIT_PASTE"
    same = complete.post(
        "/api/v12/approved/foundit/candidates",
        json=request,
        headers={"Idempotency-Key": request["idempotency_key"]},
    )
    assert same.json()["candidate"]["id"] == cid
    request["idempotency_key"] = str(uuid4())
    duplicate = complete.post(
        "/api/v12/approved/foundit/candidates",
        json=request,
        headers={"Idempotency-Key": request["idempotency_key"]},
    )
    assert duplicate.status_code == 409
    check = complete.post(
        "/api/v12/approved/foundit/preview",
        json={"raw": raw},
        headers={"Idempotency-Key": str(uuid4())},
    ).json()
    assert check["possible_matches"][0]["id"] == cid
    edit = {
        "actor_name": "Test",
        "idempotency_key": str(uuid4()),
        "expected_revision": record["revision"],
        "changes": {"skills": ["FounditEnrichedSkill"]},
        "extra": {},
        "approved_fields": ["skills"],
        "source_digest": p["source_digest"],
    }
    assert (
        complete.patch(
            f"/api/v12/approved/candidates/{cid}/profile",
            json=edit,
            headers={"Idempotency-Key": edit["idempotency_key"]},
        ).status_code
        == 200
    )
    request["separate_person_reason"] = (
        "Verified different person sharing a contact for synthetic test"
    )
    separate = complete.post(
        "/api/v12/approved/foundit/candidates",
        json=request,
        headers={"Idempotency-Key": request["idempotency_key"]},
    )
    assert separate.status_code == 201
    with store[0].connect() as c:
        assert all(
            raw not in row[0]
            for row in c.execute(text("SELECT provenance_json FROM candidate_profile_versions"))
        )


def upload(client, store, data, kind="ORIGINAL", metadata=None):
    from urllib.parse import quote

    return client.post(
        f"/api/ats-v2/candidates/{store[3]}/resumes",
        content=data,
        headers={
            "Idempotency-Key": str(uuid4()),
            "X-Resume-Filename": "sample.pdf",
            "X-Resume-Kind": kind,
            "X-Resume-Metadata": quote(
                json.dumps(metadata or {"uploaded_by": "Synthetic reviewer"})
            ),
            "Content-Type": "application/octet-stream",
        },
    )


def test_resume_versions_metadata_link_current_hashes_and_private_access(complete, store):
    blob = valid_pdf()
    first = upload(complete, store, blob)
    assert first.status_code == 201, first.text
    original = first.json()
    assert original["sha256"] == hashlib.sha256(blob).hexdigest()
    altered = upload(
        complete,
        store,
        blob,
        "JOBMITRA_STANDARD",
        {
            "uploaded_by": "Reviewer",
            "preparation_source": "Claude",
            "source_original_id": original["id"],
            "upload_notes": "Manual review",
        },
    )
    assert altered.status_code == 201, altered.text
    alternate = altered.json()
    assert alternate["source_original_id"] == original["id"]
    second = upload(complete, store, blob)
    assert second.status_code == 201
    history = complete.get(f"/api/ats-v2/candidates/{store[3]}/resumes").json()
    assert (
        len(history) == 3 and next(r for r in history if r["id"] == alternate["id"])["is_current"]
    )
    p = f"/api/ats-v2/candidates/{store[3]}/resumes/{original['id']}/download"
    assert complete.get(p).content == blob
    current = f"/api/v12/approved/candidates/{store[3]}/resumes/{original['id']}/current"
    r = complete.post(
        current,
        json={"expected_current_id": second.json()["id"], "actor_name": "Reviewer"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert r.status_code == 200, r.text
    assert complete.get(p).content == blob
    assert upload(complete, store, b"%PDF-fake%%EOF").status_code == 422
    assert (
        upload(
            complete,
            store,
            blob,
            "JOBMITRA_STANDARD",
            {"preparation_source": "ChatGPT", "source_original_id": 999999},
        ).status_code
        == 404
    )
    complete.cookies.clear()
    assert complete.get(p).status_code == 403
    assert upload(complete, store, blob).status_code == 403


def test_v12_verified_frontend_redirects_and_legacy_flag(client, store):
    for old, new in [
        ("/candidate-desk", "/workspace-v12/candidates"),
        ("/candidates/foundit-import", "/workspace-v12/candidates?section=foundit"),
        ("/companies", "/workspace-v12/companies"),
        ("/requirements", "/workspace-v12/jobs"),
        ("/candidate-search-v2", "/workspace-v12/candidates"),
    ]:
        r = client.get(old, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == new
    assert client.get("/email/proposal").status_code == 200
    client.app.state.settings.unified_v12_enabled = False
    assert client.get("/candidate-search-v2", follow_redirects=False).status_code == 200
