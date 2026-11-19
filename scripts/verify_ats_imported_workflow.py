"""Exercise imported real data in a disposable SQLite clone, never live journeys."""

import json
import math
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from jobmitra.core.config import Settings  # noqa: E402
from jobmitra.main import create_app  # noqa: E402
from jobmitra.modules.ats_v2.database import build_ats_engine, validate  # noqa: E402
from jobmitra.modules.ats_v2.master_source import write_private_json  # noqa: E402
from jobmitra.modules.ats_v2.resumes import safe_resume_path  # noqa: E402

API = "/api/ats-v2"
HEADERS = {"X-Jobmitra-UI": "1", "Origin": "http://testserver"}


def exercise(database, storage_root, settings):
    engine = build_ats_engine(database)
    validate(engine)
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with engine.connect() as conn:
        source_companies = (
            conn.execute(text("SELECT * FROM companies WHERE legacy_postgres_id IS NOT NULL"))
            .mappings()
            .all()
        )
        source_candidates = (
            conn.execute(text("SELECT * FROM candidates WHERE legacy_postgres_id IS NOT NULL"))
            .mappings()
            .all()
        )
    check("imported companies and candidates present", bool(source_companies and source_candidates))
    pg = Mock()
    pg.connect.side_effect = AssertionError("New ATS workflow must not query PostgreSQL")
    config = settings.model_copy(
        update={
            "ats_v2_database": database,
            "ats_v2_resume_storage_root": storage_root,
            "ats_v2_enabled": True,
        }
    )
    with (
        patch("jobmitra.main.build_engine", return_value=pg),
        TestClient(create_app(config)) as client,
    ):

        def get(path, **kwargs):
            response = client.get(API + path, **kwargs)
            check("GET " + path.split("?")[0], response.status_code == 200)
            return response.json()

        def mutate(method, path, values, expected=200):
            response = getattr(client, method)(API + path, headers=HEADERS, json=values)
            check(method.upper() + " " + path, response.status_code == expected)
            return response.json()

        check("new JD workspace opens", client.get("/jd-workspace-v2").status_code == 200)
        check("new candidate search opens", client.get("/candidate-search-v2").status_code == 200)
        companies = get("/companies")
        imported_ids = {row["id"] for row in source_companies}
        check(
            "company dropdown contains all active imported companies",
            imported_ids <= {row["id"] for row in companies},
        )
        target = (datetime.now(UTC) + timedelta(days=7)).date().isoformat()
        job = mutate(
            "post",
            "/jobs",
            {
                "company_id": companies[0]["id"],
                "title": "Isolated migration verification JD",
                "status": "ACTIVE",
                "target_date": target,
                "vacancies": 2,
            },
            expected=201,
        )
        jid = job["id"]
        later = (datetime.now(UTC) + timedelta(days=9)).date().isoformat()
        edited = mutate(
            "patch",
            f"/jobs/{jid}",
            {
                "title": "Isolated edited verification JD",
                "salary_min_inr": 25000,
                "salary_max_inr": 40000,
                "salary_period": "MONTHLY",
                "salary_basis": "CTC",
                "target_date": later,
            },
        )
        check(
            "JD title salary and target edits persisted",
            edited["target_date"] == later and edited["salary_max_inr"] == 40000,
        )
        history = get(f"/history?job_id={jid}")
        check(
            "JD update audit includes target salary and title",
            any(
                row["event_type"] == "JD_UPDATED"
                and {"title", "salary_max_inr", "target_date"} <= set(row["after_json"])
                for row in history["items"]
            ),
        )
        all_results = get("/candidates?page_size=100")
        check(
            "imported candidate count is searchable", all_results["total"] >= len(source_candidates)
        )
        selected = next(
            row
            for row in source_candidates
            if json.loads(row["skills_json"]) and row["experience_years"] is not None
        )
        cid = selected["id"]
        skill = next(
            skill
            for skill in json.loads(selected["skills_json"])
            if '"' not in skill and len(skill) <= 100
        )
        result = get(
            "/candidates",
            params={
                "keywords": '"' + skill + '"',
                "match": "ALL",
                "experience_min": selected["experience_years"],
                "experience_max": selected["experience_years"],
                "include_unknown_experience": False,
                "page_size": 100,
            },
        )
        check(
            "actual imported skill and experience search matches",
            any(row["id"] == cid for row in result["items"]),
        )
        comparable = [
            row
            for row in source_candidates
            if row["expected_salary_inr"] is not None
            and row["expected_salary_period"] in {"MONTHLY", "ANNUAL"}
            and row["expected_salary_basis"] in {"CTC", "GROSS", "IN_HAND"}
        ]
        if comparable:
            salary = comparable[0]
            budget = math.ceil(
                salary["expected_salary_inr"]
                / (12 if salary["expected_salary_period"] == "ANNUAL" else 1)
            )
            result = get(
                "/candidates",
                params={
                    "budget": budget,
                    "salary_period": "MONTHLY",
                    "salary_basis": salary["expected_salary_basis"],
                    "include_unknown_salary": False,
                    "page_size": 100,
                },
            )
            check(
                "actual imported salary period/basis filter matches",
                any(row["id"] == salary["id"] for row in result["items"]),
            )
        else:
            check(
                "unknown salary stays unknown under strict budget",
                get(
                    "/candidates",
                    params={"budget": 1, "salary_basis": "CTC", "include_unknown_salary": False},
                )["total"]
                == 0,
            )
        notices = [row for row in source_candidates if row["notice_days"] is not None]
        check(
            "notice-period inclusion/exclusion uses actual source facts",
            get("/candidates", params={"include_unknown_notice": False})["total"] == len(notices),
        )
        if notices:
            limit = notices[0]["notice_days"]
            check(
                "maximum notice filter reconciles",
                get(
                    "/candidates",
                    params={"max_notice_days": limit, "include_unknown_notice": False},
                )["total"]
                == sum(row["notice_days"] <= limit for row in notices),
            )
        profile = get(f"/candidates/{cid}")
        check(
            "selected profile retains source identity",
            profile["legacy_postgres_id"] == selected["legacy_postgres_id"],
        )
        link = mutate("post", f"/jobs/{jid}/candidates", {"candidate_id": cid}, expected=201)
        lid = link["id"]
        check("association begins at pool", link["stage_code"] == "POOL")
        mutate("post", f"/jobs/{jid}/candidates", {"candidate_id": cid}, expected=409)
        for stage in ["CONTACT", "SCREENING", "COMPANY_SUBMISSION"]:
            values = {"stage_code": stage}
            if stage == "CONTACT":
                values.update(
                    feedback="Isolated migration verification feedback", feedback_source="JOBMITRA"
                )
            mutate("post", f"/jobs/{jid}/candidates/{lid}/move", values)
        flow = mutate(
            "put",
            f"/jobs/{jid}/workflow",
            {
                "workflow_version": 0,
                "workflow_mode": "CONFIGURED",
                "rounds": [
                    {"round_name": "Verification technical", "mode": "VIDEO"},
                    {"round_name": "Verification management", "mode": "PHONE"},
                ],
            },
        )
        first, second = flow["rounds"]
        mutate(
            "post",
            f"/jobs/{jid}/candidates/{lid}/move",
            {"stage_code": "ROUND", "round_id": first["id"]},
        )
        renamed = [
            {"id": second["id"], "round_name": second["round_name"], "mode": second["mode"]},
            {"id": first["id"], "round_name": "Verification technical renamed", "mode": "VIDEO"},
        ]
        mutate(
            "put",
            f"/jobs/{jid}/workflow",
            {"workflow_version": 1, "workflow_mode": "CONFIGURED", "rounds": renamed},
        )
        pipeline = get(f"/jobs/{jid}/pipeline")
        check(
            "round edits preserve current candidate round ID",
            pipeline["items"][0]["round_id"] == first["id"],
        )
        mutate(
            "post",
            f"/jobs/{jid}/candidates/{lid}/feedback",
            {"feedback": "Isolated standalone feedback"},
        )
        mutate("post", f"/jobs/{jid}/candidates/{lid}/move", {"stage_code": "NOT_SELECTED"})
        timeline = get(f"/history?job_id={jid}&candidate_id={cid}&jd_candidate_id={lid}")
        check(
            "historical round labels survive rename/reorder",
            any(
                row["event_type"] == "MOVED"
                and row["to_label_snapshot"] == "Verification technical"
                for row in timeline["items"]
            ),
        )
        check(
            "candidate-in-JD history contains feedback and rejection",
            {"FEEDBACK", "REJECTED", "ADDED", "MOVED"}
            <= {row["event_type"] for row in timeline["items"]},
        )
        result = get(f"/jobs/{jid}")
        check(
            "dashboard target and creation date correct",
            bool(result["created_at"])
            and result["target_date"] == later
            and result["target_state"] == "TRACK"
            and result["joined_count"] == 0,
        )
        with engine.connect() as conn:
            check(
                "SQLite integrity",
                conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok",
            )
            check("SQLite foreign keys", not conn.exec_driver_sql("PRAGMA foreign_key_check").all())
    pg.connect.assert_not_called()
    engine.dispose()
    return {
        "status": "passed",
        "checks": checks,
        "check_count": len(checks),
        "imported_company_count": len(source_companies),
        "imported_candidate_count": len(source_candidates),
        "postgresql_connections": 0,
        "writes_confined_to_disposable_clone": True,
    }


def main():
    settings = Settings()
    with TemporaryDirectory(prefix="jobmitra-imported-e2e-", dir="/private/tmp") as temporary:
        root = Path(temporary)
        database, files = root / "ats.sqlite3", root / "resumes"
        with closing(
            sqlite3.connect(settings.ats_v2_database.as_uri() + "?mode=ro", uri=True)
        ) as source:
            with closing(sqlite3.connect(database)) as destination:
                source.backup(destination)
        engine = build_ats_engine(database)
        with engine.connect() as conn:
            paths = (
                conn.execute(
                    text(
                        "SELECT storage_path FROM candidate_resumes WHERE storage_path IS NOT NULL"
                    )
                )
                .scalars()
                .all()
            )
        engine.dispose()
        for relative in paths:
            source_file = safe_resume_path(settings.ats_v2_resume_storage_root, relative)
            destination = safe_resume_path(files, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file, destination)
        report = exercise(database, files, settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    written = write_private_json(
        PROJECT / "runtime/ats-master-migration" / f"workflow-{stamp}.json", report
    )
    print(
        f"Imported-data workflow: {report['check_count']} checks passed using a disposable clone."
    )
    print("No live candidate journey or PostgreSQL record was modified.")
    print("Private verification report:", written)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            "Isolated workflow verification failed ("
            + type(error).__name__
            + "). No live records were changed."
        )
        raise SystemExit(1) from None
