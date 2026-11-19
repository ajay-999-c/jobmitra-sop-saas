"""Deterministic source mappings; all identities and content are synthetic."""

import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from jobmitra.modules.ats_v2.master_mapping import (
    canonical_json,
    map_candidate,
    map_company,
    map_resume_metadata,
    source_fingerprint,
)

COMPANY = UUID("10000000-0000-0000-0000-000000000001")
CANDIDATE = UUID("20000000-0000-0000-0000-000000000001")
DOMAIN = UUID("30000000-0000-0000-0000-000000000001")
SUBDOMAIN = UUID("30000000-0000-0000-0000-000000000002")
DOCUMENT = UUID("40000000-0000-0000-0000-000000000001")
PARSE = UUID("50000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 11, 17, 10, 30, 0, 123456, tzinfo=UTC)


def company_row(**changes):
    return {
        "id": COMPANY,
        "company_name": "Existing Test Company",
        "company_name_key": "existing test company",
        "general_phone_numbers": ["000123", "+91 0000000000"],
        "address_line": "Synthetic address",
        "city": "Pune",
        "state": "Maharashtra",
        "postal_code": "000000",
        "source_register_ids": ["Register-01"],
        "created_at": NOW,
        "updated_at": NOW,
        **changes,
    }


def candidate_row(**changes):
    return {
        "id": CANDIDATE,
        "full_name": "  Original Synthetic Name  ",
        "mobile": "9876543210",
        "mobile_normalized": "9876543210",
        "email": "Candidate@Example.test",
        "source": "Foundit",
        "role_title": "Software Engineer",
        "domain_id": DOMAIN,
        "subdomain_id": SUBDOMAIN,
        "qualification": "B.Tech",
        "experience_months": 49,
        "skills": [" Python ", "SQL", "python", ""],
        "current_location": "Pune",
        "preferred_locations": ["Mumbai", " Pune ", "pune"],
        "hometown": "Synthetic hometown",
        "home_state": "Maharashtra",
        "ready_to_relocate": True,
        "current_salary_amount": Decimal("0.00"),
        "current_salary_period": "Monthly",
        "current_salary_basis": "Gross",
        "expected_salary_amount": Decimal("50000.25"),
        "expected_salary_period": "Annual",
        "expected_salary_basis": "Take-home",
        "last_salary_raw": "Original salary annotation",
        "notice_period_text": "30 days",
        "version": 3,
        "created_at": NOW - timedelta(days=10),
        "updated_at": NOW,
        **changes,
    }


def catalogs():
    return (
        [{"id": DOMAIN, "name": "Engineering", "key": "engineering"}],
        [{"id": SUBDOMAIN, "domain_id": DOMAIN, "name": "Software", "key": "software"}],
    )


def document_row(**changes):
    return {
        "id": DOCUMENT,
        "candidate_id": CANDIDATE,
        "kind": "ORIGINAL_RESUME",
        "original_filename": "synthetic-resume.pdf",
        "storage_key": "a" * 32 + ".pdf",
        "content_type": "application/pdf",
        "size_bytes": 125,
        "sha256": "b" * 64,
        "uploaded_by_staff_id": UUID("60000000-0000-0000-0000-000000000001"),
        "version": 2,
        "source_document_id": None,
        "approval_status": None,
        "created_at": NOW,
        **changes,
    }


def test_company_identity_and_business_data_preserved_with_deterministic_contacts():
    row = company_row()
    contacts = [
        {
            "id": "contact-b",
            "company_id": COMPANY,
            "contact_name": "Second contact",
            "designation": "HR",
            "phone_numbers": ["000222"],
            "created_at": NOW,
            "updated_at": NOW,
        },
        {
            "id": "contact-a",
            "company_id": COMPANY,
            "contact_name": "First contact",
            "designation": None,
            "phone_numbers": ["000111"],
            "created_at": NOW,
            "updated_at": NOW,
        },
    ]
    # Use actual UUID-shaped source identities.
    contacts[0]["id"] = UUID("70000000-0000-0000-0000-000000000002")
    contacts[1]["id"] = UUID("70000000-0000-0000-0000-000000000001")
    original = copy.deepcopy((row, contacts))
    mapped = map_company(row, contacts)
    reordered = map_company(dict(reversed(list(row.items()))), list(reversed(contacts)))
    assert mapped.valid and mapped.issues == ()
    assert mapped.values == reordered.values
    assert mapped.values["id"] == mapped.values["legacy_postgres_id"] == str(COMPANY)
    assert mapped.values["company_name"] == row["company_name"]
    assert json.loads(mapped.values["general_phone_numbers_json"]) == row["general_phone_numbers"]
    assert json.loads(mapped.values["contacts_json"])[0]["contact_name"] == "First contact"
    assert json.loads(mapped.values["source_json"])["address_line"] == row["address_line"]
    assert (row, contacts) == original


def test_candidate_preserves_original_name_fields_timestamps_and_source_decimal_precision():
    row = candidate_row()
    original = copy.deepcopy(row)
    domains, subdomains = catalogs()
    mapped = map_candidate(row, domains, subdomains)
    assert mapped.valid and mapped.issues == ()
    values, raw = mapped.values, json.loads(mapped.values["source_json"])
    assert values["full_name"] == "  Original Synthetic Name  "
    assert values["legacy_postgres_id"] == str(CANDIDATE)
    assert values["candidate_code"] == "PG-" + CANDIDATE.hex.upper()
    assert values["job_title"] == row["role_title"] and values["current_city"] == "Pune"
    assert values["experience_years"] == 49 / 12
    assert values["current_salary_inr"] == "0.00" and values["expected_salary_inr"] == "50000.25"
    assert (
        values["current_salary_period"] == "MONTHLY"
        and values["expected_salary_period"] == "ANNUAL"
    )
    assert (
        values["current_salary_basis"] == "GROSS" and values["expected_salary_basis"] == "IN_HAND"
    )
    assert json.loads(values["skills_json"]) == ["Python", "SQL"]
    assert json.loads(values["preferred_cities_json"]) == ["Mumbai", "Pune"]
    assert values["phone_normalized"] == "919876543210"
    assert values["email_normalized"] == "candidate@example.test"
    assert values["notice_days"] == 30 and values["availability"] == "TO_CONFIRM"
    assert values["primary_domain"] == "Engineering" and values["source"] == "FOUNDIT_PASTE"
    assert values["current_employer"] is None and values["professional_summary"] is None
    assert raw["skills"] == original["skills"] and raw["hometown"] == original["hometown"]
    assert raw["last_salary_raw"] == original["last_salary_raw"]
    assert raw["expected_salary_amount"] == "50000.25"
    assert raw["_resolved_catalog"]["subdomain"]["name"] == "Software"
    assert values["created_at"] == "2026-11-07T10:30:00.123456Z"
    assert values["updated_at"] == "2026-11-17T10:30:00.123456Z"
    assert row == original


def test_money_null_and_zero_are_distinct_and_unknowns_are_not_invented():
    mapped = map_candidate(
        candidate_row(
            current_salary_amount=None,
            expected_salary_amount=Decimal("0.00"),
            current_salary_period="Unknown",
            expected_salary_period="Unknown",
            current_salary_basis="Unknown",
            expected_salary_basis="Unknown",
            experience_months=None,
            notice_period_text=None,
            domain_id=None,
            subdomain_id=None,
            skills=[],
            preferred_locations=[],
        )
    )
    assert mapped.valid
    assert (
        mapped.values["current_salary_inr"] is None
        and mapped.values["expected_salary_inr"] == "0.00"
    )
    assert mapped.values["current_salary_period"] is None
    assert mapped.values["current_salary_basis"] == "UNKNOWN"
    assert mapped.values["experience_years"] is None and mapped.values["notice_days"] is None


@pytest.mark.parametrize(
    "raw,expected,warning",
    [
        ("Immediate", 0, False),
        ("0", 0, False),
        ("15 days", 15, False),
        ("1 day", 1, False),
        ("1 month", None, True),
        ("Serving 30 days", None, True),
        ("15-30 days", None, True),
    ],
)
def test_notice_is_parsed_only_when_explicit(raw, expected, warning):
    mapped = map_candidate(candidate_row(notice_period_text=raw), *catalogs())
    assert mapped.values["notice_days"] == expected
    assert ("notice_unparsed" in mapped.issues) == warning
    assert json.loads(mapped.values["source_json"])["notice_period_text"] == raw


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("id", "bad", "invalid_candidate_id"),
        ("full_name", "  ", "invalid_candidate_name"),
        ("mobile", None, "invalid_candidate_phone"),
        ("mobile_normalized", "not-normalized", "invalid_candidate_phone_normalized"),
        ("created_at", datetime(2026, 1, 1), "invalid_candidate_created_at"),
        ("updated_at", None, "invalid_candidate_updated_at"),
        ("expected_salary_amount", Decimal("NaN"), "invalid_expected_salary_amount"),
        ("current_salary_amount", Decimal("-1.00"), "invalid_current_salary_amount"),
        ("experience_months", -1, "invalid_experience_months"),
    ],
)
def test_invalid_required_source_values_are_blocking_codes_only(field, value, code):
    mapped = map_candidate(candidate_row(**{field: value}), *catalogs())
    assert not mapped.valid and code in mapped.blocking_issues and code in mapped.issues
    assert all("Synthetic" not in issue and "@" not in issue for issue in mapped.issues)


def test_missing_catalog_and_unknown_classifications_are_visible_without_guessing():
    mapped = map_candidate(
        candidate_row(current_salary_period="Weekly", current_salary_basis="Net")
    )
    assert mapped.valid
    assert {
        "domain_not_found",
        "subdomain_not_found",
        "unknown_current_salary_period",
        "unknown_current_salary_basis",
    } <= set(mapped.issues)
    assert mapped.values["primary_domain"] is None
    domains, subdomains = catalogs()
    subdomains[0]["domain_id"] = UUID("30000000-0000-0000-0000-000000000099")
    assert (
        "subdomain_parent_mismatch"
        in map_candidate(candidate_row(), domains, subdomains).blocking_issues
    )


def test_resume_document_metadata_preserves_lineage_but_does_not_read_files_or_copy_actor_ids():
    row = document_row()
    mapped = map_resume_metadata(row, "candidate_documents")
    assert mapped.valid
    assert mapped.values["legacy_source_table"] == "candidate_documents"
    assert mapped.values["legacy_postgres_id"] == str(DOCUMENT)
    assert mapped.references["candidate_id"] == str(CANDIDATE)
    assert mapped.references["storage_key"] == row["storage_key"]
    assert mapped.values["resume_kind"] == "ORIGINAL" and mapped.values["is_current"] == 0
    assert mapped.values["storage_path"] is None
    assert json.loads(mapped.values["parsed_json"])["sha256"] == row["sha256"]
    source = json.loads(mapped.values["source_json"])
    assert "uploaded_by_staff_id" not in source and source["version"] == 2


def test_independent_candidate_resume_and_parsed_evidence_remain_distinguished():
    original = document_row()
    independent = {
        "id": DOCUMENT,
        "candidate_id": CANDIDATE,
        "original_filename": "other.pdf",
        "storage_key": "c" * 32 + ".pdf",
        "mime_type": "application/pdf",
        "file_size": 150,
        "file_hash": "d" * 64,
        "uploaded_at": NOW,
        "updated_at": NOW,
        "is_active": True,
        "extracted_text": "Synthetic private extracted text",
        "parsed_json": {"skills": ["SQL"]},
        "parsing_status": "parsed",
        "parsing_error": None,
    }
    mapped = map_resume_metadata(independent, "candidate_resumes")
    assert mapped.valid and mapped.values["legacy_source_table"] == "candidate_resumes"
    assert (
        json.loads(mapped.values["source_json"])["extracted_text"] == independent["extracted_text"]
    )
    parse = {
        "id": PARSE,
        "document_id": DOCUMENT,
        "document_kind": "ORIGINAL_RESUME",
        "parsed_json": {"skills": ["SQL"], "full_name": "Original source identity"},
        "created_at": NOW,
        "review_status": "Unreviewed",
        "validation_status": "Structurally checked",
        "pasted_by_staff_id": COMPANY,
        "reviewed_by_staff_id": None,
    }
    parsed = map_resume_metadata(parse, "resume_parse_results", [original])
    assert parsed.valid and parsed.values["resume_kind"] == "PARSED_TEXT"
    assert parsed.references["document_id"] == str(DOCUMENT)
    assert parsed.references["candidate_id"] == str(CANDIDATE)
    assert "parsed_resume_requires_review" in parsed.issues
    assert "full_name" in json.loads(parsed.values["parsed_json"])
    assert "pasted_by_staff_id" not in json.loads(parsed.values["source_json"])
    assert parsed.values["is_current"] == 0


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"sha256": "invalid"}, "invalid_resume_sha256"),
        ({"size_bytes": 0}, "invalid_resume_size"),
        ({"kind": "AUTHORITY"}, "unsupported_resume_kind"),
        ({"storage_key": None}, "invalid_resume_storage_key"),
        ({"original_filename": "../escape.pdf"}, "unsafe_resume_filename"),
        ({"content_type": "text/html"}, "unsupported_resume_content_type"),
        (
            {"kind": "MODIFIED_RESUME", "source_document_id": DOCUMENT, "approval_status": None},
            "standard_resume_requires_review",
        ),
    ],
)
def test_invalid_resume_metadata_blocks_migration(changes, code):
    mapped = map_resume_metadata(document_row(**changes), "candidate_documents")
    assert code in mapped.blocking_issues and not mapped.valid


def test_missing_parse_document_and_invalid_json_are_reported():
    result = map_resume_metadata(
        {
            "id": PARSE,
            "document_id": DOCUMENT,
            "created_at": NOW,
            "parsed_json": [],
            "review_status": "Reviewed",
        },
        "resume_parse_results",
    )
    assert {
        "source_document_not_found",
        "invalid_resume_candidate_id",
        "invalid_parsed_resume_json",
    } <= set(result.blocking_issues)


def test_canonical_fingerprints_preserve_timestamps_precision_and_exclude_attribution():
    source = {
        "b": Decimal("10.50"),
        "a": COMPANY,
        "created_at": NOW.astimezone(timezone(timedelta(hours=5, minutes=30))),
        "actor_staff_id": str(CANDIDATE),
        "nested": {"reviewed_by_staff_id": str(CANDIDATE), "safe": "retained"},
    }
    document = canonical_json(source)
    restored = json.loads(document)
    assert restored == {
        "a": str(COMPANY),
        "b": "10.50",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "nested": {"safe": "retained"},
    }
    assert source_fingerprint(source) == source_fingerprint(dict(reversed(list(source.items()))))
    assert source_fingerprint(source) == source_fingerprint(document)
    changed = {**source, "b": Decimal("10.51")}
    assert source_fingerprint(changed) != source_fingerprint(source)
