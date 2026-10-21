import argparse
import json
import math
from statistics import mean, median

from sqlalchemy.exc import SQLAlchemyError

from jobmitra.core.config import get_settings
from jobmitra.core.database import benchmark_database, build_engine, check_database


def database_failure_details(error: Exception) -> dict[str, str]:
    """Classify driver errors without returning raw messages, URLs or credentials."""
    original = getattr(error, "orig", error)
    message = str(original).lower()
    categories = (
        (
            ("operation not permitted", "permission denied"),
            "network_permission_denied",
            "Allow this process LAN access or run from the macOS Terminal outside the sandbox.",
        ),
        (
            ("password authentication failed", "no password supplied"),
            "authentication_failed",
            "Verify the local password and any JOBMITRA_DB_PASSWORD environment override.",
        ),
        (
            ("no pg_hba.conf entry",),
            "server_access_denied",
            "Verify that the server permits this client, database and user.",
        ),
        (
            ("connection refused",),
            "connection_refused",
            "Verify the configured host and port and that PostgreSQL is listening.",
        ),
        (
            ("no route to host",),
            "host_unreachable",
            "Check this process's LAN access and the route to the configured PostgreSQL host.",
        ),
        (
            ("timeout expired", "connection timeout", "network is unreachable"),
            "network_unreachable_or_timeout",
            "Verify LAN reachability and firewall access to PostgreSQL.",
        ),
        (
            ("could not translate host name", "name or service not known"),
            "host_resolution_failed",
            "Verify the configured database host.",
        ),
    )
    for tokens, code, hint in categories:
        if any(token in message for token in tokens):
            return {"error_code": code, "hint": hint}
    return {
        "error_code": "database_unavailable",
        "hint": "Verify application environment settings and database availability.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Jobmitra database diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.command == "benchmark" and not 1 <= args.iterations <= 10000:
        parser.error("--iterations must be between 1 and 10000")

    engine = build_engine(get_settings())
    try:
        connection_ms = check_database(engine)
        result = {"status": "ok", "connection_check_ms": round(connection_ms, 3)}
        if args.command == "benchmark":
            samples = benchmark_database(engine, args.iterations)
            result.update(
                iterations=len(samples),
                min_ms=round(min(samples), 3),
                mean_ms=round(mean(samples), 3),
                median_ms=round(median(samples), 3),
                p95_ms=round(sorted(samples)[math.ceil(len(samples) * 0.95) - 1], 3),
                max_ms=round(max(samples), 3),
            )
        print(json.dumps(result))
        return 0
    except (SQLAlchemyError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "message": "Database check failed",
                    **database_failure_details(error),
                }
            )
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
