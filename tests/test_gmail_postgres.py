"""Gmail claim/history interoperability on a Unix-socket-only disposable schema."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import text
from test_gmail_phase1 import draft
from test_gmail_phase1 import settings as settings_fixture

from jobmitra.modules.ats_v2 import candidates
from jobmitra.modules.ats_v2.candidate_schemas import CandidateCreate
from jobmitra.modules.email_studio import gmail_history as audit
from jobmitra.modules.email_studio import gmail_service as gmail

pytest_plugins = ["test_v12_postgres_backend"]
settings = settings_fixture


def test_postgres_durable_claim_reconciliation_without_master_changes(pg_store, settings):
    engine = pg_store[0][0]
    person = candidates.create_candidate(
        engine,
        CandidateCreate(
            full_name="Pooja Jobmitra",
            email="pooja.jobmitra@gmail.com",
        ),
    )

    def state():
        with engine.connect() as conn:
            return {
                table: conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
                for table in ("candidates", "companies", "job_descriptions", "jd_candidates")
            }

    before = state()
    data = draft(person["id"])
    with patch.object(
        gmail, "send", return_value={"message_id": "mock-pg", "thread_id": "mock-thread"}
    ) as sending:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: audit.dispatch(engine, settings, data), range(3)))
        assert sending.call_count == 1
        assert len({e["email_reference"] for e in results}) == 1
    assert state() == before
    with engine.connect() as conn:
        entries = audit.history(conn, person["id"])
        assert len(entries) == 1 and entries[0]["gmail_message_id"] == "mock-pg"
