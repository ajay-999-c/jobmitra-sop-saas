# Phase 0 validation — 14 October 2026

Executed on macOS with Python 3.12.11 against the configured Windows PostgreSQL
server at `192.168.1.50:5432`, database `jobmitra`.

## Results

- `JOBMITRA_RUN_DB_TESTS=1 .venv/bin/pytest -q`: **23 passed** in 3.30 seconds.
- Covered live database connection, repeated SELECT queries, connection return to
  the pool, live API readiness, refused TCP connections, simulated outages,
  credential redaction, session/engine cleanup, benchmark summary calculations,
  environment precedence and core health with either value of the reserved AI flag.
- Actual Uvicorn HTTP smoke test passed for liveness, database readiness and OpenAPI;
  the temporary server was shut down after verification.
- Ruff lint and formatting checks passed.
- `alembic heads` and `alembic history` succeeded with no revisions.
- One upstream Starlette warning advises migrating its test client from `httpx`
  to `httpx2`. The tested client currently works; it does not affect backend runtime.

## Observed latency

Separate `jobmitra-db health`: **496.396 ms**, including connection establishment
and `SELECT 1`. The benchmark's initial connection check took **413.634 ms**.

100 repeated `SELECT 1` queries on one warmed connection:

| Statistic | Milliseconds |
| --- | ---: |
| Minimum | 5.115 |
| Mean | 23.180 |
| Median | 18.372 |
| p95 (nearest rank) | 50.850 |
| Maximum | 67.046 |

These are observations from one LAN run, not a throughput or performance guarantee.
Connection setup is measured separately from warmed query latency.

## Scope preserved

No migrations were applied, no business tables were created, no data was imported,
and existing database records were not changed. Live diagnostics and tests used
SELECT queries only. Company Management remains unimplemented pending approval.
The existing `company-dataset.xlsx` was not edited.

Spreadsheet SHA-256 recorded during validation:
`97936c31d1bc52ccad2f78a347c741118e1557204066ec63b56e0102aee342c0`.

The local `.env` is ignored and has filesystem mode 600. The project directory is
not currently a Git repository; ignore rules are ready for when Git is initialized.

## Connectivity investigation — 14 October 2026

The reported failure was reproduced inside the Codex network sandbox. Both
SQLAlchemy and direct psycopg raised `OperationalError`; the driver identified
`Operation not permitted`, with no server SQLSTATE. Repeating both read-only tests
outside the sandbox with identical Settings succeeded. This isolates the root cause
to client network permissions, not credentials, URL escaping or server configuration.

Configuration verification confirmed that the project-root `.env` exists and loads
from `/Users/mac/Documents/jobmitra/sop-pipeline`. Host, port, database and username
matched the intended Windows server; the password was nonempty, was not the example
placeholder, and matched the dotenv value. No `JOBMITRA_` overrides or libpq `PG*`
environment variables were present in the diagnostic process. Other terminal shells
may have their own overrides. No password, URL, dotenv contents or raw exception
message was printed; only recognized error categories were reported.

The CLI now returns a safe error category and static hint, including
`network_permission_denied`, instead of only a generic failure. Eleven regression
cases verify error categorization, secret redaction and cleanup. Existing Settings
and engine configuration required no changes. Run commands in macOS Terminal from
the project root, or allow the Codex process LAN access; application code cannot
bypass an OS sandbox.

Final checks with authorized LAN access:

- Direct psycopg: `SELECT 1` succeeded using the same application settings.
- Health: succeeded; **213.854 ms** including connection establishment.
- 100-query benchmark: initial connection check **285.902 ms**; minimum **4.135 ms**,
  mean **6.251 ms**, median **5.992 ms**, p95 **9.036 ms**, maximum **10.779 ms**.
- Full suite including live tests: **34 passed**, **0 skipped**, in **3.30 seconds**;
  the same upstream test-client deprecation warning remains.
- Ruff lint and formatting checks passed.

No server configuration, migrations, tables or existing data were changed.
