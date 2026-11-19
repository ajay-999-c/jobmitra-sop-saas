"""SQLite candidate/search/resume contracts with synthetic data and private files."""

import json
import zipfile
from io import BytesIO
from pathlib import PureWindowsPath
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from jobmitra.modules.ats_v2.candidate_schemas import (
    CandidateCreate,
    CandidatePatch,
    GenerateResumeInput,
    ParsedResumeInput,
    SearchParams,
)
from jobmitra.modules.ats_v2.candidates import (
    create_candidate,
    get_candidate,
    search_candidates,
    update_candidate,
)
from jobmitra.modules.ats_v2.common import AtsError
from jobmitra.modules.ats_v2.database import build_ats_engine, initialize
from jobmitra.modules.ats_v2.resumes import (
    download_resume,
    generate_resume,
    list_resumes,
    safe_resume_path,
    save_parsed_resume,
    upload_resume,
)


@pytest.fixture
def ats(tmp_path):
    engine = build_ats_engine(tmp_path / "ats.sqlite3")
    initialize(engine)
    yield engine
    engine.dispose()


def candidate(engine, **values):
    return create_candidate(engine, CandidateCreate(full_name="Synthetic Candidate", **values))


def pdf(content=b"synthetic"):
    return b"%PDF-1.4\n" + content + b"\n%%EOF"


def test_expected_salary_bounds_and_legacy_budget(ats):
    def expected(amount, basis, period="MONTHLY"):
        return candidate(
            ats, expected_salary_inr=amount,
            expected_salary_basis=basis, expected_salary_period=period,
        )["id"]

    low = expected(25000, "CTC")
    boundary = expected(600000, "CTC", "ANNUAL")
    high = expected(65000, "CTC")
    gross = expected(50000, "GROSS")
    unknown = candidate(ats, current_salary_inr=50000)["id"]

    def matches(**filters):
        result = search_candidates(ats, SearchParams(**filters))
        return {entry["id"] for entry in result["items"]}

    assert matches(salary_min=50000, salary_basis="CTC") == {boundary, high, gross, unknown}
    assert matches(salary_max=30000, salary_basis="CTC", include_unknown_salary=False) == {low}
    assert matches(
        salary_min=300000, salary_max=780000, budget=600000, salary_period="ANNUAL",
        salary_basis="CTC", include_unknown_salary=False,
    ) == {low, boundary}
    assert matches(
        salary_min=50000, salary_max=50000, salary_basis="INDICATIVE",
        include_unknown_salary=False,
    ) == {boundary, gross}
    assert matches(salary_min=50000, salary_max=50000, salary_basis="INDICATIVE") == {
        boundary, gross, unknown,
    }
    assert matches(budget=50000) == {low, boundary, high, gross, unknown}
    with pytest.raises(ValidationError):
        SearchParams(salary_min=-1)
    with pytest.raises(ValidationError):
        SearchParams(salary_min=50000, salary_max=49000)


def test_registration_is_stable_and_duplicate_identity_requires_review(ats):
    a = candidate(ats, phone="9876543210", email="candidate@example.test")
    assert a["candidate_code"].startswith("ATS-")
    assert a["skills"] == [] and a["links"] == {}
    assert get_candidate(ats, a["id"])["candidate_code"] == a["candidate_code"]
    with pytest.raises(AtsError, match="Potential duplicate") as duplicate:
        candidate(ats, phone="+91 98765 43210")
    assert duplicate.value.status == 409
    with pytest.raises(AtsError):
        candidate(ats, email="CANDIDATE@example.test")
    b = candidate(ats)
    assert b["id"] != a["id"]  # Name-only identity does not merge.
    with pytest.raises(AtsError):
        update_candidate(ats, b["id"], CandidatePatch(phone="9876543210"))
    assert get_candidate(ats, b["id"])["phone"] is None


def test_profile_changes_have_minimal_before_after_audit(ats):
    a = candidate(
        ats,
        skills=["Python"],
        expected_salary_inr=40000,
        expected_salary_period="MONTHLY",
        expected_salary_basis="CTC",
    )
    update_candidate(ats, a["id"], CandidatePatch(skills=["SQL"], expected_salary_inr=50000))
    with ats.connect() as conn:
        events = list(
            conn.execute(
                text("SELECT * FROM recruitment_events WHERE candidate_id=:id ORDER BY id"),
                {"id": a["id"]},
            ).mappings()
        )
    assert [e["event_type"] for e in events] == ["CANDIDATE_CREATED", "CANDIDATE_UPDATED"]
    assert json.loads(events[1]["before_json"]) == {
        "skills_json": ["Python"],
        "expected_salary_inr": 40000,
    }
    assert json.loads(events[1]["after_json"]) == {
        "skills_json": ["SQL"],
        "expected_salary_inr": 50000,
    }
    assert get_candidate(ats, a["id"])["full_name"] == "Synthetic Candidate"


def test_evidence_any_all_relevance_location_and_pagination(ats):
    a = candidate(ats, skills=["Python", "SQL"], current_city="Pune", experience_years=4)
    b = candidate(
        ats,
        skills=["Python"],
        current_employer="Example Labs",
        preferred_cities=["Pune"],
        experience_years=8,
    )
    candidate(ats, qualification="Biology", experience_years=1)
    found = search_candidates(ats, SearchParams(keywords="Python SQL", match="ANY"))
    assert found["total"] == 2
    assert found["items"][0]["id"] == a["id"]
    all_matches = search_candidates(ats, SearchParams(keywords="Python SQL", match="ALL"))
    assert [row["id"] for row in all_matches["items"]] == [a["id"]]
    location = search_candidates(ats, SearchParams(location="pune", sort="experience", page_size=1))
    assert location["total"] == 2 and location["items"][0]["id"] == b["id"]
    assert search_candidates(ats, SearchParams(keywords="Synthetic"))["total"] == 0
    assert search_candidates(ats, SearchParams(keywords="%"))["total"] == 0
    assert search_candidates(ats, SearchParams(page=2, page_size=2))["total"] == 3


def test_experience_notice_availability_unknown_filters(ats):
    a = candidate(ats, experience_years=4, notice_days=15, availability="AVAILABLE")
    b = candidate(ats)
    candidate(ats, experience_years=8, notice_days=90, availability="UNAVAILABLE")
    found = search_candidates(
        ats, SearchParams(experience_min=3, experience_max=5, max_notice_days=30)
    )
    assert {r["id"] for r in found["items"]} == {a["id"], b["id"]}
    strict = search_candidates(
        ats,
        SearchParams(
            experience_min=3,
            experience_max=5,
            max_notice_days=30,
            include_unknown_experience=False,
            include_unknown_notice=False,
        ),
    )
    assert [r["id"] for r in strict["items"]] == [a["id"]]
    assert search_candidates(ats, SearchParams(availability="AVAILABLE"))["total"] == 1


def test_salary_period_conversion_never_equates_basis(ats):
    a = candidate(
        ats,
        expected_salary_inr=600000,
        expected_salary_period="ANNUAL",
        expected_salary_basis="CTC",
    )
    b = candidate(
        ats,
        expected_salary_inr=50000,
        expected_salary_period="MONTHLY",
        expected_salary_basis="GROSS",
    )
    unknown = candidate(ats)
    candidate(
        ats,
        expected_salary_inr=80000,
        expected_salary_period="MONTHLY",
        expected_salary_basis="CTC",
    )
    strict = search_candidates(
        ats,
        SearchParams(
            budget=50000, salary_period="MONTHLY", salary_basis="CTC", include_unknown_salary=False
        ),
    )
    assert [r["id"] for r in strict["items"]] == [a["id"]]
    permissive = search_candidates(
        ats,
        SearchParams(
            budget=600000, salary_period="ANNUAL", salary_basis="CTC", include_unknown_salary=True
        ),
    )
    assert {r["id"] for r in permissive["items"]} == {a["id"], b["id"], unknown["id"]}


def test_resume_versions_paths_and_audit_exclude_content(ats, tmp_path):
    a = candidate(ats)
    root = tmp_path / "private-files"
    first = upload_resume(ats, a["id"], root, pdf(b"private-secret"), "original.pdf", 10000)
    second = upload_resume(ats, a["id"], root, pdf(b"new bytes"), "new.pdf", 10000)
    assert first["id"] != second["id"]
    history = list_resumes(ats, a["id"])
    assert [r["is_current"] for r in history] == [True, False]
    assert all(r["downloadable"] and "storage_path" not in r for r in history)
    first_path, media, _ = download_resume(ats, a["id"], first["id"], root)
    assert first_path.read_bytes() == pdf(b"private-secret") and media == "application/pdf"
    with ats.connect() as conn:
        stored = conn.scalar(
            text("SELECT storage_path FROM candidate_resumes WHERE id=:id"), {"id": first["id"]}
        )
        audit = " ".join(str(row) for row in conn.execute(text("SELECT * FROM recruitment_events")))
    assert not PureWindowsPath(stored).is_absolute() and "\\" not in stored
    assert safe_resume_path(root, stored) == first_path
    assert "private-secret" not in audit and "parsed_json" not in audit
    for invalid in ("../outside.pdf", "C:\\private\\candidate.pdf", "/outside.pdf", "a\\b.pdf"):
        with pytest.raises(AtsError):
            safe_resume_path(root, invalid)
        with pytest.raises(AtsError):
            upload_resume(ats, a["id"], root, pdf(), invalid, 10000)


def test_upload_rejects_spoofed_types_zip_bombs_and_symlink_escape(ats, tmp_path):
    a = candidate(ats)
    root = tmp_path / "private"
    for data, filename in ((b"not pdf", "test.pdf"), (pdf(), "test.exe"), (b"bad zip", "a.docx")):
        with pytest.raises(AtsError):
            upload_resume(ats, a["id"], root, data, filename, 10000)
    with pytest.raises(AtsError) as oversized:
        upload_resume(ats, a["id"], root, pdf(), "a.pdf", 1)
    assert oversized.value.status == 413
    malicious = BytesIO()
    with zipfile.ZipFile(malicious, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("../outside", "bad")
    with pytest.raises(AtsError):
        upload_resume(ats, a["id"], root, malicious.getvalue(), "a.docx", 10000)
    bomb = BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document>" + " " * 21000 + "</document>")
    with pytest.raises(AtsError):
        upload_resume(ats, a["id"], root, bomb.getvalue(), "a.docx", 10000)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(exist_ok=True)
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AtsError):
        safe_resume_path(root, "link/private.pdf")
    assert list_resumes(ats, a["id"]) == []


def test_supported_docx_upload_has_private_windows_safe_storage(ats, tmp_path):
    a = candidate(ats)
    document = BytesIO()
    with zipfile.ZipFile(document, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types><Override ContentType="application/vnd.openxmlformats-officedocument.'
                'wordprocessingml.document.main+xml" PartName="/word/document.xml"/></Types>'
            ),
        )
        archive.writestr("word/document.xml", "<document><body>Resume evidence</body></document>")
    row = upload_resume(
        ats, a["id"], tmp_path / "private", document.getvalue(), "resume.docx", 10000
    )
    path, media, filename = download_resume(ats, a["id"], row["id"], tmp_path / "private")
    assert path.read_bytes() == document.getvalue()
    assert filename == "resume.docx" and media.endswith("wordprocessingml.document")


def test_reviewed_parsed_evidence_standard_generation_and_stale_identity(ats, tmp_path):
    a = candidate(ats)
    root = tmp_path / "private"
    original = upload_resume(ats, a["id"], root, pdf(), "original.pdf", 10000)
    parsed = save_parsed_resume(
        ats,
        a["id"],
        ParsedResumeInput(
            source_resume_id=original["id"],
            facts_reviewed=True,
            profile={
                "work_experience": [{"company": "Example", "responsibilities": ["Kubernetes"]}],
                "professional_summary": "<script>alert(1)</script>",
            },
        ),
    )
    assert parsed["downloadable"] is False
    assert search_candidates(ats, SearchParams(keywords="Kubernetes"))["total"] == 1
    generated = generate_resume(
        ats, a["id"], root, GenerateResumeInput(parsed_resume_id=parsed["id"], facts_reviewed=True)
    )
    path, media, _ = download_resume(ats, a["id"], generated["id"], root)
    assert media == "text/html" and "Synthetic Candidate" in path.read_text()
    assert "<script>" not in path.read_text() and "&lt;script&gt;" in path.read_text()
    update_candidate(ats, a["id"], CandidatePatch(full_name="Corrected Original Name"))
    with pytest.raises(AtsError, match="Identity or original resume changed"):
        generate_resume(
            ats,
            a["id"],
            root,
            GenerateResumeInput(parsed_resume_id=parsed["id"], facts_reviewed=True),
        )
    upload_resume(ats, a["id"], root, pdf(b"replacement"), "replacement.pdf", 10000)
    assert search_candidates(ats, SearchParams(keywords="Kubernetes"))["total"] == 0
    assert len(list_resumes(ats, a["id"])) == 4
    with pytest.raises(ValueError):
        ParsedResumeInput(
            source_resume_id=original["id"],
            facts_reviewed=True,
            profile={"full_name": "LLM replacement identity"},
        )


def test_cross_candidate_resume_access_and_null_validation(ats, tmp_path):
    a, b = candidate(ats), candidate(ats)
    original = upload_resume(ats, a["id"], tmp_path / "private", pdf(), "a.pdf", 10000)
    with pytest.raises(AtsError) as forbidden:
        download_resume(ats, b["id"], original["id"], tmp_path / "private")
    assert forbidden.value.status == 404
    with pytest.raises(AtsError):
        save_parsed_resume(
            ats,
            b["id"],
            ParsedResumeInput(source_resume_id=original["id"], facts_reviewed=True, profile={}),
        )
    for payload in ({"full_name": None}, {"skills": None}, {"availability": None}):
        with pytest.raises(ValueError):
            CandidatePatch(**payload)


def test_imported_candidate_exposes_selected_original_facts_without_raw_source(ats):
    source = {
        "notice_period_text": "Serving one month",
        "source": "Referral",
        "hometown": "Pune",
        "home_state": "Maharashtra",
        "ready_to_relocate": True,
        "experience_months": 49,
        "recorded_by_staff_id": "private-actor",
        "storage_key": "private/source/path.pdf",
        "raw_resume": "private resume body",
    }
    with ats.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO candidates(full_name,legacy_postgres_id,"
                "source_json,source_fingerprint) "
                "VALUES('Synthetic imported candidate',:source_id,:source,:fingerprint)"
            ),
            {
                "source_id": str(uuid4()),
                "source": json.dumps(source),
                "fingerprint": "private-hash",
            },
        )
        cid = result.lastrowid
    for profile in (get_candidate(ats, cid), search_candidates(ats, SearchParams())["items"][0]):
        assert profile["source_legacy"] == "postgresql"
        assert profile["notice_period_text"] == "Serving one month"
        assert profile["source_original"] == "Referral"
        assert profile["ready_to_relocate"] is True and profile["experience_months"] == 49
        assert profile["hometown"] == "Pune" and profile["home_state"] == "Maharashtra"
        assert profile["notice_days"] is None
        assert "source_json" not in profile and "source_fingerprint" not in profile
        serialized = json.dumps(profile)
        for private in ("private-actor", "private/source", "private resume body", "private-hash"):
            assert private not in serialized


def test_imported_resume_status_and_historical_parse_are_explicit_without_raw_source(ats):
    candidate_id = candidate(ats)["id"]
    historical = {
        "full_name": "Original Historical Candidate",
        "skills": ["SQL"],
        "work_experience": [{"company": "Synthetic Employer"}],
    }
    private_source = json.dumps(
        {"storage_key": "private/source/path.pdf", "uploaded_by_staff_id": "private-actor"}
    )
    with ats.begin() as conn:
        for status in ("copied", "missing", "hash_mismatch"):
            conn.execute(
                text(
                    "INSERT INTO candidate_resumes(candidate_id,resume_kind,source_type,is_current,"
                    "storage_path,parsed_json,source_json,legacy_source_table,legacy_postgres_id) "
                    "VALUES(:cid,'ORIGINAL','UPLOADED',0,:path,:metadata,:source,"
                    "'candidate_documents',:legacy)"
                ),
                {
                    "cid": candidate_id,
                    "path": "1/original/copied.pdf" if status == "copied" else None,
                    "metadata": json.dumps(
                        {"sha256": "a" * 64, "size": 20, "migration_file_status": status}
                    ),
                    "source": private_source,
                    "legacy": str(uuid4()),
                },
            )
        conn.execute(
            text(
                "INSERT INTO candidate_resumes(candidate_id,resume_kind,source_type,is_current,"
                "raw_text,parsed_json,source_json,legacy_source_table,legacy_postgres_id) "
                "VALUES(:cid,'PARSED_TEXT','UPLOADED',0,'private extracted text',:parsed,:source,"
                "'resume_parse_results',:legacy)"
            ),
            {
                "cid": candidate_id,
                "parsed": json.dumps(historical),
                "source": private_source,
                "legacy": str(uuid4()),
            },
        )
    rows = list_resumes(ats, candidate_id)
    parsed = next(row for row in rows if row["resume_kind"] == "PARSED_TEXT")
    assert parsed["historical_parsed_json"] == historical and parsed["requires_review"] is True
    assert "profile" not in parsed and parsed["is_current"] is False
    assert parsed["legacy_source_table"] == "resume_parse_results"
    files = {row["file_status"]: row for row in rows if row["resume_kind"] == "ORIGINAL"}
    assert files["copied"]["downloadable"] is True
    assert files["missing"]["downloadable"] is False
    assert files["hash_mismatch"]["downloadable"] is False
    for row in rows:
        assert row["source_legacy"] == "postgresql"
        assert "source_json" not in row and "storage_path" not in row and "raw_text" not in row
        serialized = json.dumps(row)
        assert "private/source" not in serialized and "private-actor" not in serialized
        assert "private extracted text" not in serialized
