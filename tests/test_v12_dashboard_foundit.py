"""JD browsing and reviewed Foundit registration use disposable fixtures only."""

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from jobmitra.modules.ats_v2 import (
    candidate_profiles,
    jd_dashboard,
    jobs,
)
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.ats_v2.schemas import JobPatch

pytest_plugins = ["test_v12_creation_failures", "test_v12_candidate_complete"]
RAW = """Full Name: Synthetic Foundit Applicant
Mobile: 9876500044
Email: foundit-fixture@example.test
Current Designation: Accounts Executive
Current Company: Synthetic Finance Works
Experience: 4y 1m
Current CTC: 45000.1250 monthly
Expected CTC: 6.25 LPA
Location: Indore
Preferred Locations: Pune, Indore
Skills: Python, SyntheticParsedSkill
Qualification: B.Com
Industry: Finance
Functional area: Accounts
Notice Period: 30 days
Professional Summary: Evidence-backed professional summary
Relevant experience: 2 years
"""


@pytest.fixture(params=["postgresql", "sqlite"])
def dashboard_db(request):
    store = (
        request.getfixturevalue("pg_store")[0]
        if request.param == "postgresql"
        else request.getfixturevalue("store")
    )
    engine, company = store[:2]
    now = datetime.now(UTC)
    second = str(uuid4())
    with transaction(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO companies(id,company_name,company_name_key,contacts_json) "
                "VALUES(:id,'Acme Regional','acme regional','[]')"
            ),
            {"id": second},
        )
        for i in range(35):
            conn.execute(
                text(
                    "INSERT INTO job_descriptions(company_id,jd_code,title,location,status,"
                    "created_at,target_date,is_legacy_import) "
                    "VALUES(:c,:code,:title,:location,:status,:created,:target,1)"
                ),
                {
                    "c": company if i % 2 else second,
                    "code": f"JD-FILTER-{i:03}",
                    "title": f"Analyst {i:02}",
                    "location": "Indore" if i % 2 else "Pune",
                    "status": ["ACTIVE", "DRAFT", "ON_HOLD", "CLOSED"][i % 4],
                    "created": (now - timedelta(days=i)).isoformat(),
                    "target": None
                    if i % 7 == 0
                    else (now.date() + timedelta(days=5 if i % 3 else -1)).isoformat(),
                },
            )
    return engine, company, second, now


def ids(result):
    return [r["id"] for r in result["items"]]


def test_jd_sort_pagination_and_edits_use_creation_timestamp(dashboard_db):
    engine, _, _, _ = dashboard_db
    newest = jd_dashboard.browse(engine, jd_dashboard.Filters(page_size=100))
    assert len(ids(newest)) == len(set(ids(newest))) == 35
    oldest = jd_dashboard.browse(engine, jd_dashboard.Filters(sort="OLDEST", page_size=100))
    assert ids(newest) == list(reversed(ids(oldest)))
    before = ids(newest)
    # Use the existing service and canonical company gateway; edits must not reorder creation dates.
    from jobmitra.modules.ats_v2.companies import CompanyGateway

    jobs.update_job(
        engine, oldest["items"][0]["id"], JobPatch(title="Edited older JD"), CompanyGateway(engine)
    )
    assert ids(jd_dashboard.browse(engine, jd_dashboard.Filters(page_size=100))) == before
    pages = [
        jd_dashboard.browse(engine, jd_dashboard.Filters(page=p, page_size=7)) for p in range(1, 6)
    ]
    assert [i for p in pages for i in ids(p)] == before
    assert all(p["total"] == 35 and p["pages"] == 5 for p in pages)
    target = jd_dashboard.browse(engine, jd_dashboard.Filters(sort="TARGET", page_size=100))[
        "items"
    ]
    dates = [r["target_date"] for r in target if r["target_date"]]
    assert dates == sorted(dates)
    assert target[-1]["target_date"] is None
    for sort, field in [("COMPANY", "company_name"), ("TITLE", "title")]:
        rows = jd_dashboard.browse(engine, jd_dashboard.Filters(sort=sort, page_size=100))["items"]
        assert [r[field].casefold() for r in rows] == sorted(r[field].casefold() for r in rows)


def test_jd_search_filters_target_and_global_summary(dashboard_db):
    engine, company, second, _ = dashboard_db
    all_rows = jd_dashboard.browse(engine, jd_dashboard.Filters(page_size=100))
    for term, key in [
        ("aCmE", "company_name"),
        ("lyst 1", "title"),
        ("TER-02", "jd_code"),
        ("ndo", "location"),
    ]:
        result = jd_dashboard.browse(engine, jd_dashboard.Filters(q=term, page_size=100))
        assert result["total"] > 0 and all(
            term.casefold() in str(r[key]).casefold() for r in result["items"]
        )
        assert result["summary"] == all_rows["summary"]
    assert (
        jd_dashboard.browse(engine, jd_dashboard.Filters(q=str(all_rows["items"][0]["id"])))[
            "total"
        ]
        >= 1
    )
    for target in ["TRACK", "DUE", "OVERDUE"]:
        result = jd_dashboard.browse(engine, jd_dashboard.Filters(target=target))
        assert all(r["target_state"] == target for r in result["items"])
    for status in ["DRAFT", "ACTIVE", "ON_HOLD", "CLOSED"]:
        result = jd_dashboard.browse(engine, jd_dashboard.Filters(status=status))
        assert result["total"] > 0 and all(r["status"] == status for r in result["items"])
    combined = jd_dashboard.browse(
        engine,
        jd_dashboard.Filters(q="Analyst", company_id=second, status="ACTIVE", target="TRACK"),
    )
    assert combined["total"] > 0 and all(
        r["company_id"] == second and r["status"] == "ACTIVE" and r["target_state"] == "TRACK"
        for r in combined["items"]
    )
    assert jd_dashboard.browse(engine, jd_dashboard.Filters(q="no-such-jd"))["total"] == 0
    assert jd_dashboard.browse(engine, jd_dashboard.Filters(q="%"))["total"] == 0
    assert jd_dashboard.browse(engine, jd_dashboard.Filters(q="' OR 1=1 --"))["total"] == 0
    assert {r["id"] for r in all_rows["companies"]} >= {company, second}


def test_jd_created_calendar_boundaries(dashboard_db):
    engine, _, _, now = dashboard_db
    # Use the same India/Monday/inclusive date utility as Candidate Dashboard.
    for period in ["TODAY", "WEEK", "MONTH", "YEAR"]:
        result = jd_dashboard.browse(
            engine, jd_dashboard.Filters(period=period, page_size=100), now
        )
        start = datetime.fromisoformat(result["calendar"]["start_utc"])
        end = datetime.fromisoformat(result["calendar"]["end_utc_exclusive"])
        assert all(
            start <= datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < end
            for r in result["items"]
        )
        if period == "WEEK":
            from zoneinfo import ZoneInfo

            assert start.astimezone(ZoneInfo("Asia/Kolkata")).weekday() == 0
    day = now.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date()
    result = jd_dashboard.browse(
        engine,
        jd_dashboard.Filters(period="CUSTOM", date_from=day, date_to=day, page_size=100),
        now,
    )
    assert (
        result["total"]
        == jd_dashboard.browse(engine, jd_dashboard.Filters(period="TODAY"), now)["total"]
    )
    assert result["calendar"]["end_date"] == day.isoformat()


def test_jd_api_reads_no_candidate_or_history_payloads(office, pg_store):
    statements = []
    engine = pg_store[0][0]

    def record(_c, _cursor, query, _params, _ctx, _many):
        statements.append(query)

    event.listen(engine, "before_cursor_execute", record)
    try:
        r = office.get("/api/v12/approved/jd-dashboard?q=missing&sort=NEWEST")
        assert r.status_code == 200, r.text
        assert r.json()["items"] == [] and r.json()["summary_scope"] == "ALL_JDS"
        assert not any(
            "recruitment_events" in s
            or "candidate_resumes" in s
            or 'FROM "' + engine._v12_schema + '"."candidates"' in s
            for s in statements
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert (
        office.get(
            "/api/v12/approved/jd-dashboard?period=CUSTOM&date_from=2030-02-02&date_to=2030-01-01"
        ).status_code
        == 422
    )


def preview(office, raw=RAW):
    r = office.post(
        "/api/v12/approved/foundit/preview",
        json={"raw": raw},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert r.status_code == 200, r.text
    return r.json()


def save(office, p, key=None):
    data = {k: copy.deepcopy(p[k]) for k in ["candidate", "extra", "source_digest"]}
    data.update(
        confirmed=True,
        actor_name="Synthetic reviewed office actor",
        idempotency_key=key or str(uuid4()),
    )
    return office.post(
        "/api/v12/approved/foundit/candidates",
        json=data,
        headers={"Idempotency-Key": data["idempotency_key"]},
    ), data


def test_foundit_review_edits_precision_search_and_registration_reporting(office, pg_store):
    engine = pg_store[0][0]
    before = office.get("/api/v12/approved/candidate-directory").json()["total"]
    p = preview(office)
    assert office.get("/api/v12/approved/candidate-directory").json()["total"] == before
    c = p["candidate"]
    assert c["full_name"] == "Synthetic Foundit Applicant" and c["phone"] == "9876500044"
    assert c["current_salary_inr"] == "45000.1250" and c["current_salary_period"] == "MONTHLY"
    assert c["expected_salary_inr"] == "625000.00" and c["expected_salary_period"] == "ANNUAL"
    assert p["extra"]["experience_months"] == 49 and c["primary_domain"] == "Finance"
    assert (
        p["extra"]["subdomain"] == "Accounts" and p["unmapped"][0]["field"] == "Relevant experience"
    )
    c.update(
        full_name="Employee Corrected Applicant",
        phone="9876500055",
        skills=["EditedSearchableSkill"],
        experience_years=5,
    )
    p["extra"]["experience_months"] = 60
    p["extra"]["registration_purpose"] = None
    r, data = save(office, p)
    assert r.status_code == 201, r.text
    cid = r.json()["candidate"]["id"]
    assert r.json()["candidate"]["full_name"] == "Employee Corrected Applicant"
    assert (
        r.json()["extra"]["subdomain"] == "Accounts"
        and r.json()["extra"]["experience_months"] == 60
    )
    retry = office.post(
        "/api/v12/approved/foundit/candidates",
        json=data,
        headers={"Idempotency-Key": data["idempotency_key"]},
    )
    assert retry.status_code == 201 and retry.json()["candidate"]["id"] == cid
    for url in [
        "/api/v12/approved/candidate-directory?q=Employee&source=FOUNDIT_PASTE&period=TODAY",
        "/api/v12/approved/search?keywords=EditedSearchableSkill",
    ]:
        assert cid in [r["id"] for r in office.get(url).json()["items"]]
    assert (
        office.get(
            "/api/v12/approved/candidate-dashboard?source=FOUNDIT_PASTE&period=TODAY"
        ).json()["new_candidates_selected_period"]
        == 1
    )
    with engine.connect() as conn:
        row = (
            conn.execute(text("SELECT * FROM candidates WHERE id=:id"), {"id": cid})
            .mappings()
            .one()
        )
        assert row["full_name"] == "Employee Corrected Applicant" and row["phone"] == "9876500055"
        assert (
            row["current_salary_inr"] == Decimal("45000.1250") and row["source"] == "FOUNDIT_PASTE"
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM candidate_profile_versions WHERE candidate_id=:id"),
                {"id": cid},
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM jd_candidates WHERE candidate_id=:id"), {"id": cid}
            )
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM candidate_activities WHERE candidate_id=:id"),
                {"id": cid},
            )
            == 0
        )
        provenance = conn.scalar(
            text("SELECT provenance_json FROM candidate_profile_versions WHERE candidate_id=:id"),
            {"id": cid},
        )
        assert json.loads(provenance)["method"] == "FOUNDIT_REVIEWED" and RAW not in provenance


def test_foundit_missing_period_duplicate_fields_and_rollback(office, pg_store, monkeypatch):
    p = preview(office, RAW.replace("45000.1250 monthly", "45000.1250"))
    assert p["candidate"].get("current_salary_period") is None
    r, _ = save(office, p)
    assert r.status_code == 422 and r.json()["code"] == "CURRENT_SALARY_PERIOD_REQUIRED"
    p["candidate"]["current_salary_period"] = "MONTHLY"
    engine = pg_store[0][0]
    with engine.connect() as conn:
        before = conn.scalar(text("SELECT count(*) FROM candidates"))
    original = candidate_profiles._record

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Synthetic profile failure")

    with monkeypatch.context() as m:
        m.setattr(candidate_profiles, "_record", fail)
        r, _ = save(office, p)
        assert r.status_code == 503
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidates")) == before
    r, _ = save(office, p)
    assert r.status_code == 201
    p["candidate"]["phone"] = "+91 9876500044"
    r, _ = save(office, p)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_PHONE"
    assert r.json()["matches"][0]["matched_fields"] == ["phone", "email"]
    p["candidate"]["phone"] = "9876500066"
    r, _ = save(office, p)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_EMAIL"
    p["candidate"]["email"] = "corrected-fixture@example.test"
    assert save(office, p)[0].status_code == 201


def test_foundit_optional_fields_expected_period_and_concurrent_idempotency(office, pg_store):
    from concurrent.futures import ThreadPoolExecutor

    # Missing mobile is allowed when a valid reviewed email provides the contact identity.
    p = preview(
        office, "Name: Minimal Synthetic\nEmail: minimal-fixture@example.test\nExpected CTC: 50000"
    )
    assert not p["candidate"].get("phone") and p["candidate"].get("expected_salary_period") is None
    r, data = save(office, p)
    assert r.status_code == 422 and r.json()["code"] == "EXPECTED_SALARY_PERIOD_REQUIRED"
    data["candidate"]["expected_salary_period"] = "MONTHLY"
    engine = pg_store[0][0]
    with engine.connect() as conn:
        before = conn.scalar(text("SELECT count(*) FROM candidates"))

    def send(_):
        return office.post(
            "/api/v12/approved/foundit/candidates",
            json=data,
            headers={"Idempotency-Key": data["idempotency_key"]},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert responses[0].json()["candidate"]["id"] == responses[1].json()["candidate"]["id"]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM candidates")) == before + 1
    p = preview(office, "Name: Different Synthetic\nEmail: different-fixture@example.test")
    r, _ = save(office, p)
    assert r.status_code == 201 and r.json()["candidate"]["phone"] is None
    assert r.json()["extra"].get("registration_purpose") is None
    p["candidate"]["email"] = None
    r, _ = save(office, p)
    assert r.status_code == 422 and r.json()["code"] == "CONTACT_REQUIRED"


def test_foundit_supported_structure_and_no_ambiguous_inference(office):
    p = preview(
        office,
        "Name: Synthetic Structure\nEmail: structure-fixture@example.test\n"
        "Current: Analyst at Synthetic Works Jan 2020 to Present\n"
        "Past Employment: Assistant at Earlier Works Jan 2018 to Dec 2019\n"
        "Current CTC: 4.25 lakh\nEducation: B.Com, Synthetic College, 2017\n"
        "Certifications: Synthetic Certificate, Another Certificate",
    )
    assert p["candidate"]["current_salary_inr"] == "425000.00"
    assert not p["candidate"].get("current_salary_period")
    assert p["extra"]["employment_history"][0]["start_date"] == "2020-01"
    assert p["extra"]["employment_history"][1]["end_date"] == "2019-12"
    assert p["extra"]["education_history"][0]["end_year"] == 2017
    assert p["extra"]["certifications"][0]["name"] == "Synthetic Certificate"
    p["candidate"]["current_salary_period"] = "ANNUAL"
    r, _ = save(office, p)
    assert r.status_code == 201
    assert len(r.json()["extra"]["employment_history"]) == 2
    assert len(r.json()["extra"]["certifications"]) == 2


def test_india_inclusive_day_boundaries_and_stable_timestamp_ties(dashboard_db):
    from zoneinfo import ZoneInfo

    engine, company, _, _ = dashboard_db
    india = ZoneInfo("Asia/Kolkata")
    day = datetime(2025, 1, 6, tzinfo=india)
    # Midnight and the last microsecond belong to the inclusive selected India day.
    with transaction(engine) as conn:
        for i, instant in enumerate(
            [
                day - timedelta(microseconds=1),
                day,
                day + timedelta(days=1) - timedelta(microseconds=1),
                day + timedelta(days=1),
                day,
            ]
        ):
            conn.execute(
                text(
                    "INSERT INTO job_descriptions(company_id,jd_code,title,status,"
                    "created_at,target_date,is_legacy_import) "
                    "VALUES(:c,:code,:title,'DRAFT',:created,NULL,1)"
                ),
                {
                    "c": company,
                    "code": f"BOUND-{i}",
                    "title": f"Boundary {i}",
                    "created": instant.astimezone(UTC).isoformat(),
                },
            )
    result = jd_dashboard.browse(
        engine,
        jd_dashboard.Filters(
            period="CUSTOM", date_from=day.date(), date_to=day.date(), page_size=100
        ),
    )
    assert {r["jd_code"] for r in result["items"]} == {"BOUND-1", "BOUND-2", "BOUND-4"}
    ties = [r["id"] for r in result["items"] if r["jd_code"] in ["BOUND-1", "BOUND-4"]]
    assert ties == sorted(ties, reverse=True)
    week = jd_dashboard.browse(
        engine, jd_dashboard.Filters(period="WEEK", page_size=100), day.astimezone(UTC)
    )
    assert "BOUND-0" not in [r["jd_code"] for r in week["items"]]
