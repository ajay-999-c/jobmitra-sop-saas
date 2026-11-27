"""Explicit synthetic PostgreSQL preview; never uses office recruitment rows for writes.

Run with --create-isolated once, then --serve. Private namespace identifiers live
under ignored runtime/. No credentials or office data are copied there.
"""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from jobmitra.core.config import PROJECT_ENV_FILE, Settings
from jobmitra.modules.ats_v2 import candidates, jobs, workspace_store
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.ats_v2.companies import CompanyGateway
from jobmitra.modules.ats_v2.database import transaction
from jobmitra.modules.ats_v2.postgres import build_postgres_engine, checked_schema
from jobmitra.modules.ats_v2.schemas import JobCreate, WorkflowInput
from jobmitra.modules.staff.employees import EmployeeInput, StaffChangeEvent, save
from jobmitra.modules.staff.models import StaffMember

ROOT = PROJECT_ENV_FILE.parent / "runtime" / "jd-workspace-preview"
STATE = ROOT / "preview.json"


def settings():
    return Settings(
        _env_file=[PROJECT_ENV_FILE, PROJECT_ENV_FILE.with_name(".env.v12.mac.postgres")]
    )


def provision_preview(config, *, candidate_count=24, fork=False):
    if STATE.exists() and not fork:
        raise RuntimeError("Preview already exists; reuse --serve. No overwrite permitted.")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from prepare_postgres_v12_dev import provision

    suffix = uuid4().hex[:12]
    schema = "jobmitra_v12_dev_ws_preview_" + suffix
    staff_schema = "jobmitra_v12_dev_ws_staff_" + suffix
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if STATE.exists():
        archive = ROOT / ("previous-preview-" + suffix + ".json")
        archive.write_text(STATE.read_text())
        archive.chmod(0o600)
    private = ROOT / suffix
    private.mkdir(mode=0o700)
    staff_engine = create_engine(config.database_url, hide_parameters=True).execution_options(
        schema_translate_map={None: staff_schema}
    )
    with psycopg.connect(
        host=config.db_host,
        port=config.db_port,
        dbname=config.db_name,
        user=config.db_user,
        password=config.db_password.get_secret_value(),
        sslmode=config.db_sslmode,
        connect_timeout=5,
    ) as conn:
        provision(conn, schema)
        conn.execute(f'CREATE SCHEMA "{staff_schema}"')
    StaffMember.__table__.create(staff_engine)
    StaffChangeEvent.__table__.create(staff_engine)
    with psycopg.connect(
        host=config.db_host,
        port=config.db_port,
        dbname=config.db_name,
        user=config.db_user,
        password=config.db_password.get_secret_value(),
        sslmode=config.db_sslmode,
        connect_timeout=5,
    ) as conn:
        workspace_store.apply_postgres(conn, schema, staff_schema)
    preview = config.model_copy(update={"v12_postgres_schema": schema})
    engine = build_postgres_engine(preview)
    try:
        employees = []
        for name in ("Asha Test Recruiter", "Nikhil Test Recruiter", "Sana Test Recruiter"):
            with Session(staff_engine) as session:
                employees.append(
                    save(
                        session,
                        EmployeeInput(
                            display_name=name,
                            designation="Recruiter",
                            email=name.split()[0].lower() + "@example.test",
                        ),
                        "LOCAL_DEVELOPMENT",
                        uuid4(),
                    )
                )
        company_ids = [str(uuid4()), str(uuid4())]
        with transaction(engine) as conn:
            for i, identifier in enumerate(company_ids):
                conn.execute(
                    text(
                        "INSERT INTO companies(id,company_name,company_name_key,city) "
                        "VALUES(:id,:name,:key,'Indore')"
                    ),
                    {
                        "id": identifier,
                        "name": "Workspace Test Company " + str(i + 1),
                        "key": "workspace test company " + str(i + 1),
                    },
                )
        people = []
        for i in range(candidate_count):
            people.append(
                candidates.create_candidate(
                    engine,
                    CandidateCreate(
                        full_name=f"Workspace Candidate {i + 1:03}",
                        email=f"workspace.candidate.{i + 1}@example.test",
                        skills=["Sales", "Python"],
                        current_city="Indore",
                    ),
                )
            )
            if i % 40 == 0:
                print(f"Synthetic candidates prepared: {i + 1}/{candidate_count}", flush=True)
        gateway = CompanyGateway(engine)
        job_ids = []
        for i in range(14):
            job = jobs.create_job(
                engine,
                JobCreate(
                    company_id=company_ids[i % 2],
                    title=f"Workspace Requirement {i + 1:02}",
                    target_date="2099-01-01",
                    status="ACTIVE",
                    assigned_recruiter_id=employees[i % 3]["id"] if i % 4 else None,
                    vacancies=2,
                ),
                gateway,
            )
            jobs.save_workflow(
                engine,
                job["id"],
                WorkflowInput(
                    workflow_mode="CONFIGURED",
                    workflow_version=0,
                    rounds=[
                        {"round_name": "Portfolio Assessment"},
                        {"round_name": "Manager Discussion"},
                        {"round_name": "Owner Discussion"},
                    ],
                ),
            )
            job_ids.append(job["id"])
        for i, person in enumerate(people[: min(53, len(people))]):
            jobs.attach_contact(engine, job_ids[i % 14], person["id"])
        state = {
            "schema": schema,
            "staff_schema": staff_schema,
            "storage": str(private),
            "candidate_count": candidate_count,
            "fixture": "SYNTHETIC ONLY; no office records copied",
        }
        STATE.write_text(json.dumps(state, indent=2) + "\n")
        STATE.chmod(0o600)
        print("Isolated preview created:", schema, flush=True)
    finally:
        engine.dispose()
        staff_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-isolated", action="store_true")
    parser.add_argument(
        "--fork-isolated",
        action="store_true",
        help=(
            "Create a new synthetic namespace; retain the prior namespace and private state archive"
        ),
    )
    parser.add_argument("--candidate-count", type=int, default=24, choices=range(1, 1001))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    config = settings()
    if args.create_isolated or args.fork_isolated:
        provision_preview(config, candidate_count=args.candidate_count, fork=args.fork_isolated)
    if args.serve:
        import uvicorn

        from jobmitra.main import create_app

        state = json.loads(STATE.read_text())
        schema, staff_schema = (
            checked_schema(state["schema"]),
            checked_schema(state["staff_schema"]),
        )
        if not schema.startswith("jobmitra_v12_dev_ws_preview_") or not staff_schema.startswith(
            "jobmitra_v12_dev_ws_staff_"
        ):
            raise RuntimeError("Refusing non-preview namespaces")
        storage = Path(state["storage"]).resolve()
        if not storage.is_relative_to(ROOT.resolve()):
            raise RuntimeError("Preview document storage must be isolated")
        config = config.model_copy(
            update={
                "v12_postgres_schema": schema,
                "gmail_enabled": False,
                "office_lan_enabled": False,
                "unified_v12_local_direct_editing": True,
                "ats_v2_resume_storage_root": storage / "resumes",
                "unified_v12_proposal_storage_root": storage / "proposals",
                "document_storage_root": storage / "legacy-documents",
            }
        )
        app = create_app(config)
        app.state.staff_schema = staff_schema
        uvicorn.run(
            app, host="127.0.0.1", port=args.port, workers=1, access_log=False, proxy_headers=False
        )


if __name__ == "__main__":
    main()
