"""Real PDF/JSON drafts, canonical approvals and atomic version history on isolated V3."""

import base64
import hashlib
import io
import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from pdf_fixture import valid_pdf
from reportlab.pdfgen import canvas
from test_approved_v12 import client as client
from test_unified_v12 import store as store
from test_unified_v12 import v2 as v2

from jobmitra.modules.ats_v2 import candidates, parsed_documents, profile_store, resumes
from jobmitra.modules.ats_v2.candidate_schemas import SearchParams


@pytest.fixture
def complete(client, store):
    profile_store.install(store[0])
    return client


def pdf(text_value):
    if not text_value:
        return valid_pdf()
    output = io.BytesIO()
    c = canvas.Canvas(output)
    for i, line in enumerate(text_value.splitlines()):
        c.drawString(40, 800 - i * 18, line)
    c.save()
    return output.getvalue()


def source(
    complete,
    store,
    text_value=(
        "Current job title: Parsed Role\nCurrent employer: Fictional Employer\n"
        "Skills: ExtractedSkill, Python\nQualification: B.Tech\n"
        "Total experience: 4 years 1 month\nProfessional summary: Explicit labelled summary"
    ),
    kind="JOBMITRA_STANDARD",
):
    blob = pdf(text_value)
    r = complete.post(
        f"/api/ats-v2/candidates/{store[3]}/resumes",
        content=blob,
        headers={
            "Idempotency-Key": str(uuid4()),
            "X-Resume-Filename": "altered.pdf",
            "X-Resume-Kind": kind,
            "Content-Type": "application/octet-stream",
        },
    )
    assert r.status_code == 201, r.text
    return r.json(), blob


def base(store):
    return f"/api/v12/approved/candidates/{store[3]}"


def post(client, path, data, key=None):
    return client.post(path, json=data, headers={"Idempotency-Key": key or str(uuid4())})


def draft(complete, store, rid, raw):
    response = post(
        complete,
        base(store) + "/parsed-drafts",
        {"source_resume_id": rid, "raw_json": raw, "actor_name": "Synthetic reviewer"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pdf_labelled_partial_extraction_is_draft_until_explicit_approval(complete, store):
    original, original_blob = source(complete, store, kind="ORIGINAL")
    altered, blob = source(complete, store)
    before = complete.get(base(store) + "/profile").json()
    request = {"actor_name": "Synthetic reviewer"}
    key = str(uuid4())
    path = base(store) + f"/resumes/{altered['id']}/extract"
    response = post(complete, path, request, key)
    assert response.status_code == 201, response.text
    d = response.json()
    assert d["status"] == "PARTIAL_STRUCTURED_DRAFT"
    assert d["proposed_fields"]["skills"] == ["ExtractedSkill", "Python"]
    assert d["proposed_fields"]["job_title"] == "Parsed Role"
    assert d["proposed_fields"]["extra:experience_months"] == 49
    assert (
        d["source"]["id"] == altered["id"]
        and d["source_sha256"] == hashlib.sha256(blob).hexdigest()
    )
    assert d["field_evidence"]["skills"]["line"] > 0
    assert complete.get(base(store) + "/profile").json() == before
    assert post(complete, path, request, key).json()["id"] == d["id"]
    approval = {
        "actor_name": "Synthetic reviewer",
        "expected_revision": d["profile_revision"],
        "approved_fields": ["skills", "job_title"],
    }
    k = str(uuid4())
    approved = post(complete, base(store) + f"/parsed-drafts/{d['id']}/approve", approval, k)
    assert approved.status_code == 200, approved.text
    reviewed = approved.json()["parsed_version"]
    assert reviewed["source"]["id"] == altered["id"]
    assert reviewed["status"] == "APPROVED_FIELDS"
    actual = complete.get(base(store) + "/profile").json()
    assert actual["candidate"]["skills"] == ["ExtractedSkill", "Python"]
    assert actual["candidate"]["job_title"] == "Parsed Role"
    assert actual["candidate"]["current_employer"] == before["candidate"]["current_employer"]
    assert actual["extra"].get("experience_months") == before["extra"].get("experience_months")
    assert post(complete, base(store) + f"/parsed-drafts/{d['id']}/approve", approval, k).json()[
        "replayed"
    ]
    assert (
        candidates.search_candidates(store[0], SearchParams(keywords="ExtractedSkill"))["total"]
        == 1
    )
    assert (
        candidates.search_candidates(store[0], SearchParams(keywords="Fictional Employer"))["total"]
        == 0
    )
    assert (
        complete.get(f"/api/ats-v2/candidates/{store[3]}/resumes/{original['id']}/download").content
        == original_blob
    )
    assert (
        complete.get(f"/api/ats-v2/candidates/{store[3]}/resumes/{altered['id']}/download").content
        == blob
    )
    assert complete.get(base(store) + f"/resumes/{altered['id']}/preview").content == blob


def test_json_raw_bytes_bom_unapproved_information_versions_and_source(complete, store):
    altered, _ = source(complete, store)
    blob = (
        b'\xef\xbb\xbf  {"skills": ["ReviewedJSONSkill"], '
        b'"current_job_title": "Approved JSON role", "unknown_fact": "Must remain preserved", '
        b'"current_employer": "Do not apply"}\n'
    )
    body = {
        "source_resume_id": altered["id"],
        "json_base64": base64.b64encode(blob).decode(),
        "filename": "source.json",
        "actor_name": "Reviewer",
    }
    r = post(complete, base(store) + "/parsed-drafts", body)
    assert r.status_code == 201, r.text
    d = r.json()
    download = base(store) + f"/parsed-drafts/{d['id']}/download"
    assert complete.get(download).content == blob
    assert d["json_sha256"] == hashlib.sha256(blob).hexdigest()
    before = complete.get(base(store) + "/profile").json()
    r = post(
        complete,
        base(store) + f"/parsed-drafts/{d['id']}/approve",
        {
            "actor_name": "Reviewer",
            "expected_revision": d["profile_revision"],
            "approved_fields": ["skills"],
        },
    )
    assert r.status_code == 200, r.text
    approved = r.json()["parsed_version"]
    assert complete.get(base(store) + f"/parsed-drafts/{approved['id']}/download").content == blob
    now = complete.get(base(store) + "/profile").json()
    assert now["candidate"]["job_title"] == before["candidate"]["job_title"]
    assert now["candidate"]["current_employer"] == before["candidate"]["current_employer"]
    assert complete.get(download).content == blob
    history = complete.get(f"/api/ats-v2/candidates/{store[3]}/resumes").json()
    assert len([r for r in history if r["resume_kind"] == "PARSED_TEXT"]) == 2
    assert next(r for r in history if r["id"] == d["id"])["review_status"] == "STRUCTURED_DRAFT"
    assert next(r for r in history if r["id"] == approved["id"])["reviewed_draft_id"] == d["id"]


@pytest.mark.parametrize(
    "text_value,status",
    [
        ("", "OCR_REQUIRED"),
        (
            "A narrative resume without explicit labels. Work experience is described in prose.",
            "TEXT_ONLY_PARSER_PENDING",
        ),
    ],
)
def test_incomplete_pdf_has_truthful_pending_status_and_no_proposed_fields(
    complete, store, text_value, status
):
    doc, _ = source(complete, store, text_value)
    before = complete.get(base(store) + "/profile").json()
    r = post(complete, base(store) + f"/resumes/{doc['id']}/extract", {"actor_name": "Reviewer"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == status and not d["proposed_fields"]
    assert complete.get(base(store) + "/profile").json() == before


def test_pdf_extraction_failure_is_not_reported_as_success(complete, store):
    doc, _ = source(complete, store)
    with patch.object(
        parsed_documents, "PdfReader", side_effect=RuntimeError("Synthetic extraction failure")
    ):
        r = post(
            complete, base(store) + f"/resumes/{doc['id']}/extract", {"actor_name": "Reviewer"}
        )
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTION_FAILED"
    assert not r.json()["proposed_fields"]


def test_structured_employment_education_and_projects_are_validated_reviewed_and_searchable(
    complete, store
):
    doc, _ = source(complete, store)
    data = {
        "work_experience": [
            {
                "employer": "Verified Employment",
                "job_title": "HistorySearchSkill",
                "start_date": "2021-03",
                "end_date": "2023-06",
                "experience_months": 27,
                "responsibilities": "Reviewed responsibility",
                "achievements": "Reviewed achievement",
            }
        ],
        "education_history": [
            {"qualification": "M.Tech", "institution": "Fictional University", "end_year": 2020}
        ],
        "certifications": [{"name": "Verified Certificate"}],
        "projects": [{"name": "Reviewed Project", "description": "Explicit project fact"}],
    }
    d = draft(complete, store, doc["id"], json.dumps(data))
    selected = list(d["proposed_fields"])
    r = post(
        complete,
        base(store) + f"/parsed-drafts/{d['id']}/approve",
        {
            "actor_name": "Reviewer",
            "expected_revision": d["profile_revision"],
            "approved_fields": selected,
        },
    )
    assert r.status_code == 200, r.text
    result = complete.get(base(store) + "/profile").json()
    assert result["extra"]["employment_history"][0]["experience_months"] == 27
    assert (
        candidates.search_candidates(store[0], SearchParams(keywords="HistorySearchSkill"))["total"]
        == 1
    )


def test_stale_approval_and_transaction_failure_preserve_draft_and_master(complete, store):
    doc, _ = source(complete, store)
    d = draft(complete, store, doc["id"], '{"skills":["PendingSkill"]}')
    before = complete.get(base(store) + "/profile").json()
    review = {
        "actor_name": "Reviewer",
        "expected_revision": d["profile_revision"],
        "approved_fields": ["skills"],
    }
    # Failure after profile save, before reviewed JSON insertion must roll everything back.
    with patch.object(
        resumes, "_version", side_effect=RuntimeError("Forced parsed version rollback")
    ):
        with pytest.raises(RuntimeError):
            post(complete, base(store) + f"/parsed-drafts/{d['id']}/approve", review)
    assert complete.get(base(store) + "/profile").json() == before
    assert (
        complete.get(base(store) + f"/parsed-drafts/{d['id']}").json()["status"]
        == "STRUCTURED_DRAFT"
    )
    profiles = complete.get(base(store) + "/profile").json()
    body = {
        "idempotency_key": str(uuid4()),
        "actor_name": "Reviewer",
        "expected_revision": profiles["revision"],
        "changes": {"job_title": "Newer edit"},
        "extra": {},
        "approved_fields": ["job_title"],
    }
    assert (
        complete.patch(
            base(store) + "/profile",
            json=body,
            headers={"Idempotency-Key": body["idempotency_key"]},
        ).status_code
        == 200
    )
    assert (
        post(complete, base(store) + f"/parsed-drafts/{d['id']}/approve", review).status_code == 409
    )


def test_ownership_authorization_identity_and_invalid_json(complete, store):
    doc, _ = source(complete, store)
    d = draft(
        complete, store, doc["id"], '{"full_name":"Different Person","skills":["ReviewedSkill"]}'
    )
    body = {
        "actor_name": "Reviewer",
        "expected_revision": d["profile_revision"],
        "approved_fields": ["skills"],
    }
    assert (
        post(complete, base(store) + f"/parsed-drafts/{d['id']}/approve", body).status_code == 422
    )
    assert (
        post(
            complete,
            base(store) + f"/parsed-drafts/{d['id']}/approve",
            {**body, "identity_confirmed": True},
        ).status_code
        == 200
    )
    assert (
        post(
            complete,
            base(store) + "/parsed-drafts",
            {"source_resume_id": doc["id"], "raw_json": "[1,2]", "actor_name": "Reviewer"},
        ).status_code
        == 422
    )
    assert (
        complete.get(
            f"/api/v12/approved/candidates/{store[3] + 1}/parsed-drafts/{d['id']}"
        ).status_code
        == 404
    )
    assert (
        post(
            complete,
            f"/api/v12/approved/candidates/{store[3] + 1}/resumes/{doc['id']}/extract",
            {"actor_name": "Reviewer"},
        ).status_code
        == 404
    )
    complete.cookies.clear()
    assert complete.get(base(store) + f"/parsed-drafts/{d['id']}/download").status_code == 403
    assert complete.get(base(store) + f"/resumes/{doc['id']}/preview").status_code == 403
    assert (
        post(
            complete, base(store) + f"/resumes/{doc['id']}/extract", {"actor_name": "Reviewer"}
        ).status_code
        == 403
    )


def test_parsed_upload_reuses_standard_version_or_immutable_bytes_without_duplicate_copies(
    complete, store
):
    doc, blob = source(complete, store)
    root = store[-1] / "resumes"
    original_files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    headers = {
        "Idempotency-Key": str(uuid4()),
        "X-Resume-Filename": "same-altered.pdf",
        "X-Resume-Kind": "JOBMITRA_STANDARD",
        "X-Resume-Reuse-Existing": "1",
        "Content-Type": "application/octet-stream",
    }
    path = f"/api/ats-v2/candidates/{store[3]}/resumes"
    response = complete.post(path, content=blob, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == doc["id"] and response.json()["reused_existing"]
    assert len(complete.get(path).json()) == 1
    # A distinct preparation note needs a metadata version, but reuses immutable bytes.
    headers.update(
        {
            "Idempotency-Key": str(uuid4()),
            "X-Resume-Metadata": "%7B%22upload_notes%22%3A%22Reviewed%20again%22%7D",
        }
    )
    response = complete.post(path, content=blob, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["id"] != doc["id"]
    assert len(complete.get(path).json()) == 2
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == original_files
