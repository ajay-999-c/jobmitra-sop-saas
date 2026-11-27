"""Read-only timings/query counts against the explicitly marked synthetic preview.

Never provisions, migrates or writes database records. Output contains counts,
latencies, sizes and query-plan summaries, not credentials or recruitment details.
"""

import argparse
import json
import statistics
import time
from urllib.request import urlopen

from sqlalchemy import event, text

from jobmitra.core.config import PROJECT_ENV_FILE, Settings
from jobmitra.modules.ats_v2 import approved, candidates, jd_dashboard
from jobmitra.modules.ats_v2.candidate_schemas import SearchParams
from jobmitra.modules.ats_v2.postgres import (
    build_postgres_engine,
    checked_schema,
    validate_postgres,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8902")
    parser.add_argument("--runs", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    if args.url != "http://127.0.0.1:8902":
        raise RuntimeError("Only the owned isolated loopback preview is supported")
    state = json.loads(
        (PROJECT_ENV_FILE.parent / "runtime/jd-workspace-preview/preview.json").read_text()
    )
    schema = checked_schema(state["schema"])
    if not schema.startswith("jobmitra_v12_dev_ws_preview_"):
        raise RuntimeError("Refusing an office namespace")
    config = Settings(
        _env_file=[PROJECT_ENV_FILE, PROJECT_ENV_FILE.with_name(".env.v12.mac.postgres")]
    )
    engine = build_postgres_engine(config.model_copy(update={"v12_postgres_schema": schema}))
    validate_postgres(engine)
    with engine.connect() as conn:
        counts = {
            table: conn.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in (
                "candidates",
                "companies",
                "job_descriptions",
                "jd_candidates",
                "recruitment_events",
            )
        }
        job = conn.scalar(text("SELECT min(id) FROM job_descriptions"))
    queries = []

    def record(*unused):
        queries.append(1)

    event.listen(engine, "before_cursor_execute", record)
    report = {"fixture_counts": counts, "runs": args.runs, "service": {}}
    operations = {
        "full_state": lambda: approved.state(engine),
        "selected_jd": lambda: approved.state(engine, job),
        "dashboard": lambda: jd_dashboard.browse(engine, jd_dashboard.Filters()),
        "candidate_search": lambda: candidates.search_candidates(
            engine, SearchParams(page_size=10, keywords="Python"), include_names=True
        ),
    }
    try:
        for name, operation in operations.items():
            samples = []
            for _ in range(args.runs):
                queries.clear()
                start = time.perf_counter()
                result = operation()
                samples.append(
                    {
                        "ms": round((time.perf_counter() - start) * 1000, 2),
                        "sql": len(queries),
                        "json_bytes": len(json.dumps(result, default=str).encode()),
                    }
                )
            report["service"][name] = {
                "samples": samples,
                "median_ms": statistics.median(s["ms"] for s in samples),
            }
        report["http"] = {}
        for name, path in {
            "employee_search": "/api/v12/employees?q=asha&page_size=20",
            "dashboard": "/api/v12/approved/jd-dashboard",
        }.items():
            samples = []
            for _ in range(args.runs):
                start = time.perf_counter()
                with urlopen(args.url + path, timeout=30) as response:
                    body = response.read()
                samples.append(
                    {"ms": round((time.perf_counter() - start) * 1000, 2), "bytes": len(body)}
                )
            report["http"][name] = samples
        with engine.connect() as conn:
            plan = conn.scalar(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT j.id FROM "
                    "job_descriptions j JOIN companies c ON c.id=j.company_id "
                    "ORDER BY j.created_at DESC,j.id DESC LIMIT 20"
                )
            )
            report["plan"] = {k: plan[0][k] for k in ("Planning Time", "Execution Time")}
        print(json.dumps(report, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
