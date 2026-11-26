"""Direct sourcing through unchanged services on disposable SQLite/PostgreSQL."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_unified_v12 import store, v2  # noqa: F401
from test_v12_postgres_backend import pg_store  # noqa: F401

from jobmitra.modules.ats_v2 import candidates, jobs, request_receipts
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate, SearchParams
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.schemas import JobCreate


@pytest.fixture(params=["sqlite", "postgresql"])
def sourcing_store(request):
    return (
        request.getfixturevalue("store")
        if request.param == "sqlite"
        else request.getfixturevalue("pg_store")[0]
    )


def test_identity_search_is_opt_in_paginated_and_read_only(sourcing_store):
    engine, *_ = sourcing_store
    person = candidates.create_candidate(
        engine,
        CandidateCreate(
            full_name="Identity Search Person",
            phone="+91 98765 43210",
            email="identity.person@example.test",
            current_city="Indore",
            preferred_cities=["Bhopal"],
            job_title="Accounts Executive",
            skills=["Tally"],
            professional_summary="Previously a warehouse coordinator",
        ),
    )
    for term in [
        "Identity Search",
        "+91 (98765) 43210",
        "9876543210",
        "Indore",
        "Bhopal",
        "warehouse coordinator",
        "Tally",
        "  PERSON@EXAMPLE  ",
        "identity.person@",
    ]:
        result = candidates.search_candidates(
            engine,
            SearchParams(keywords=term, identity_lookup=True, match="ALL", page_size=1),
            include_names=True,
        )
        assert result["total"] == 1
        assert result["items"][0]["id"] == person["id"]
    assert not candidates.search_candidates(
        engine, SearchParams(keywords="identity.person@"), include_names=True
    )["items"]
    assert not candidates.search_candidates(
        engine, SearchParams(keywords="9876543210"), include_names=True
    )["items"]
    assert not candidates.search_candidates(
        engine, SearchParams(keywords="Identity Search", identity_lookup=True)
    )["items"]
    assert not candidates.search_candidates(
        engine,
        SearchParams(keywords="%' OR 1=1 --", identity_lookup=True, match="ALL"),
        include_names=True,
    )["items"]
    result = candidates.search_candidates(
        engine, SearchParams(identity_lookup=True, page_size=1), include_names=True
    )
    second = candidates.search_candidates(
        engine, SearchParams(identity_lookup=True, page_size=1, page=2), include_names=True
    )
    assert result["total"] == second["total"] == 2
    assert result["items"][0]["id"] != second["items"][0]["id"]


def test_attachment_receipt_preserves_pool_and_canonical_next_stage(sourcing_store):
    engine, company, _, candidate, _ = sourcing_store
    job = jobs.create_job(
        engine,
        JobCreate(
            company_id=company,
            title="Direct sourcing test",
            status="ACTIVE",
            target_date=date.today() + timedelta(days=5),
        ),
        CompanyGateway(engine),
    )
    key = str(uuid4())
    token = request_receipts.request_key.set(key)
    try:
        first = jobs.associate(engine, job["id"], candidate)
        second = jobs.associate(engine, job["id"], candidate)
    finally:
        request_receipts.request_key.reset(token)
    assert first["id"] == second["id"]
    pipeline = jobs.pipeline(engine, job["id"])["items"]
    assert len(pipeline) == 1
    assert pipeline[0]["stage_code"] == "POOL"
    assert pipeline[0]["next_stage"] == "CONTACT"
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM jd_candidates WHERE job_id=:j"), {"j": job["id"]}
            ).scalar_one()
            == 1
        )


def test_identity_search_covers_candidates_beyond_first_page(sourcing_store):
    engine, *_ = sourcing_store
    target = candidates.create_candidate(
        engine,
        CandidateCreate(
            full_name="Older Search Target",
            phone="9876500099",
            email="older.target@example.test",
            job_title="Accountant",
        ),
    )
    for index in range(12):
        candidates.create_candidate(
            engine,
            CandidateCreate(full_name=f"Newer Person {index}", phone=f"987651{index:04d}"),
        )
    first = candidates.search_candidates(
        engine, SearchParams(identity_lookup=True, sort="recent", page_size=10), include_names=True
    )
    assert target["id"] not in [row["id"] for row in first["items"]]
    for query in [" older search ", "500099", "TARGET@EXAMPLE"]:
        found = candidates.search_candidates(
            engine,
            SearchParams(keywords=query, identity_lookup=True, match="ALL", page_size=10),
            include_names=True,
        )
        assert found["total"] == 1
        assert found["items"][0]["id"] == target["id"]
