# Jobmitra — Company Management and JD Tracking

Lightweight modular monolith for Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2,
psycopg 3, Alembic and Pydantic Settings. Jinja2 and locally bundled HTMX provide
the lightweight UI. Phase 1A provides two Company
Management models/tables and a separate cleaned workbook. Phase 1B adds the lightweight
Company Directory and basic CRUD UI at `/companies`. Phase 1C imports the validated
subset of the cleaned workbook: 131 companies and 108 contacts; unresolved records
remain withheld for review. AI providers are not installed or called.

Stage 2 adds dynamic staff, JDs, multiple recruiters, target milestones, automatic
history and employee tasks, with separate ATS JSON enrichment and the red Jobmitra
theme. **Revision `0002_jd_tracking` was approved and applied to Windows on
2026-10-20.** All 131 companies and 108 contacts were preserved. The live
[Company Directory](http://127.0.0.1:8000/companies) displays the Windows records.
See the [deployment and backup record](docs/stage-2-windows-deployment.md).
See the [review and commands](docs/stage-2-review.md),
[full five-table schema](docs/stage-2-schema.md) and
[implementation map](docs/stage-2-implementation-map.md).

**Deployment verified (2026-10-21):** Windows now reports revision
`0004_candidate_desk`, including `0003_jd_work_focus`. The JD Process Tracker and
Candidate Desk can use the deployed schema. Private persistent resume storage has
been configured on this Mac. See the [post-migration verification record](docs/windows-stage3-postdeployment.md).

For review without touching Windows, run `.venv/bin/python scripts/test_stage2_isolated.py`
or use `.venv/bin/python scripts/test_stage2_isolated.py --serve` for a disposable
preview at <http://127.0.0.1:8765/requirements>. Requires PostgreSQL 18 server tools;
the runner uses a private Unix socket with TCP disabled. Stopping the preview
discards its data. Any subsequent Windows migration requires separate approval.

## Stage 3 Candidate Desk — deployed schema and private storage

Paperless candidate registration/editing, office visits, candidate-led job searches,
domain catalog, private versioned PDF/DOCX files and manual ChatGPT/Claude JSON
history are implemented. See the [implementation and acceptance review](docs/stage-3-implementation-review.md)
and [exact seven-table schema](docs/stage-3-schema.md).

Revision `0004_candidate_desk` and its `0003_jd_work_focus` dependency are verified
on Windows. Subsequent migrations still require separate approval. For an isolated
review instead of the regular Windows-backed server, run
`.venv/bin/python scripts/test_stage3_isolated.py --serve` at
<http://127.0.0.1:8000/>. This serves every module together; its database and private
file root are disposable. Use `--port 8766` only if port 8000 is already occupied.
Real documents require an explicitly configured, existing absolute
`JOBMITRA_DOCUMENT_STORAGE_ROOT`; there is no default or automatic fallback.
Back up both database and files. Candidate profile edit history beyond timestamp/version
requires separate approval of the proposed eighth table.

## macOS setup

From this project directory, use Python 3.12 or newer. With `uv`:

```sh
uv sync --extra dev
cp .env.example .env  # First setup only; do not overwrite an existing .env.
chmod 600 .env
```

Edit `.env` locally to supply the password. The current example targets Windows
PostgreSQL at `192.168.1.51:5432`, database `jobmitra_dev`, user `jobmitra_app`.
Environment variables override `.env`; `.env` is resolved from the project root relative
to the configuration module, independently of the process working directory.
Use the editable checkout installation described below, including on Windows/NSSM.
Credentials must never be committed, pasted into URLs or printed in logs.
`uv.lock` pins the tested dependency set.

If `uv` is unavailable:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run from the project root:

```sh
source .venv/bin/activate
uvicorn jobmitra.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: <http://127.0.0.1:8000/docs>. `GET /health/live` checks the running
process. `GET /health/ready` executes `SELECT 1`, returning HTTP 200 on success
and HTTP 503 with a generic response on failure. A database outage does not prevent
startup or liveness; synchronous database operations run in FastAPI's worker threads.

Company Directory: <http://127.0.0.1:8000/companies>. The page loads company names
once, searches in browser memory and loads contacts only on selection. Add/edit/delete
forms use PostgreSQL directly, with duplicate-name and stale-edit protection. Manual
Refresh and throttled refresh on return to the tab keep the list reasonably fresh
without polling. See [Phase 1B requirements and implementation](docs/phase-1b-company-directory.md).

## Database checks and latency

```sh
jobmitra-db health
jobmitra-db benchmark --iterations 100
pytest -q
JOBMITRA_RUN_DB_TESTS=1 pytest -q
ruff check .
```

Diagnostics exit 0 on success, 1 on database failure, and do not expose driver errors.
Failures include an allow-listed `error_code` and a static troubleshooting hint.
For `network_permission_denied`, the local process is blocked from opening the
connection. Run diagnostics in macOS Terminal from this project directory, or grant
the Codex command LAN access. Changing the password or PostgreSQL configuration
will not fix a client sandbox restriction. In Codex, live tests also need permission
to open TCP connections; skipped integration tests do not verify database connectivity.
To inspect shell overrides without revealing their values, use
`env | cut -d= -f1 | sort` and look for `JOBMITRA_` names. Unset any unintended
override in that shell, then rerun the command. Never print the raw exception,
connection URL or `.env` contents for diagnostics.
The health timing includes establishing/checking out a connection, pre-ping and
`SELECT 1`. The benchmark reports min, mean, median, nearest-rank p95 and max
milliseconds for repeated `SELECT 1` queries on one connection after warm-up.
It measures client-observed LAN query round trips, not business workload throughput.
Foundation live tests and diagnostics issue SELECT queries only and release connections.
Default tests use controlled doubles and a refused local TCP connection;
live Windows connectivity tests require explicit opt-in.

The pool defaults to 3 connections, no overflow, pre-ping enabled, and a 5-second
pool wait. Connection establishment and SQL statements also have 5-second limits.
Each worker process owns its own pool; use one worker initially. Request sessions
close at dependency exit, diagnostics dispose their engine in `finally`, and the
application disposes its pool at shutdown. Future writes must use explicit service
transaction boundaries; the session dependency never automatically commits.

## Windows PostgreSQL host

The existing tested `psql` connection should already satisfy these prerequisites:

- macOS and Windows are on a reachable LAN; Windows keeps the address `192.168.1.51`.
- PostgreSQL listens on the LAN interface and port 5432.
- Windows Firewall permits inbound TCP 5432 from the development machine.
- `pg_hba.conf` permits `jobmitra_app` to access `jobmitra_dev` from the macOS IP,
  preferably with `scram-sha-256` authentication.
- The database/user already exist and PostgreSQL is running.

If a check fails, verify those settings and test with `psql -h 192.168.1.51 -p 5432
-U jobmitra_app -d jobmitra_dev -W -c 'SELECT 1'` (enter the password at its prompt).
Do not place the password in command-line arguments. This project does not change
Windows settings or create databases/users. The Phase 1C importer below targets only
local `jobmitra_dev` and must be invoked explicitly.
`sslmode=prefer` uses TLS when available; configure verified TLS before deployment
over an untrusted network. See [moving the database to Windows](docs/windows-database-migration.md)
for the verified backup, restore guards and administrator extension prerequisite.

## Structure and module boundaries

```text
src/jobmitra/
  main.py                 Application factory, lifespan and health routes
  cli.py                  Read-only diagnostics
  core/config.py          Environment configuration and masked password
  core/database.py        Engine, sessions, shared ORM metadata and SELECT checks
  modules/
    companies/
    jobs/
    staff/
    worklog/
    candidates/
    applications/
    activities/
    ai_parsing/
  templates/stage2/       Jinja pages and HTMX fragments
  static/stage2/          Local CSS/JS, brand assets and bundled HTMX
migrations/               Company revision plus additive Stage 2 revision
tests/                    Focused tests and opt-in isolated/live checks
```

Each business module will own its routes, Pydantic schemas, services, repositories
and models when approved. Modules may depend on `core`; composition belongs in the
application and cross-module behavior should use explicit service contracts.
`Base.metadata` is shared
for migrations, and future model registration must explicitly import approved
module models in Alembic. Company, staff, jobs and worklog are implemented;
candidates, applications, the old activities package and AI parsing remain placeholders.

`JOBMITRA_AI_ENABLED` defaults to false and is reserved for future optional AI
registration. Changing it does not activate a provider in Phase 0. Future AI
integrations must be loaded only when enabled, handle their own failures, and
never be required by core startup, CRUD, database readiness or migrations.

## Alembic

Alembic gets its connection from the same Settings/engine factory; no credentials
are stored in `alembic.ini`. Revision `0001_company_management` creates the two Company
Management business tables and has been applied to local `jobmitra_dev`. Alembic
maintains its own version table. Phase 1C inserts data without running migrations.
Check the configuration without changing the database:

```sh
alembic heads
alembic history
```

After approval of a future schema, register the module models, then review generated
migrations before running `alembic upgrade head`. Do not run autogenerate against an
existing populated schema before registering all managed models: it could propose
dropping existing tables. Even an empty upgrade can create Alembic's tracking table;
Phase 0 did not execute it or `Base.metadata.create_all()`.

Phase 1A created the schema in local `jobmitra_dev`. The runtime target is now the
Windows server above. Alembic blocks remote changes by default. Stage 2 adds an
explicit `-x allow_remote=true` opt-in. The approved Stage 2 migration was applied
on 2026-10-20 after backup and SQL review. The earlier database transfer restored revision
0001 without executing Alembic. See the [two-table schema](docs/phase-1a-company-schema-proposal.md) and
[Phase 1A results](docs/phase-1a-validation.md). Phase 1B adds the UI without schema
changes. Phase 1C adds an insert-only importer without schema changes.

## Company data import — Phase 1C

From the project root, install the optional Excel reader and run validation first:

```sh
uv sync --extra dev --extra import
.venv/bin/python scripts/import_companies.py --dry-run
.venv/bin/python scripts/import_companies.py --apply
```

The equivalent installed command is `jobmitra-import-companies`. This Phase 1C
importer intentionally remains restricted to the original local database; do not
use it for a new Windows import without a separate change. Both modes require
the existing local PostgreSQL 18 `jobmitra_dev` database at revision
`0001_company_management`. Defaults read `outputs/phase-1a/company-dataset-cleaned.xlsx`
and reconcile it with the unchanged `company-dataset.xlsx`. Reports receive unique
names under `outputs/phase-1c`; `--report PATH` must name a new file.

Dry-run uses a read-only database transaction. Apply inserts only unambiguous new
companies and contacts in one transaction; existing companies are skipped by source
IDs or normalized name, including manually renamed companies. It never overwrites,
deletes or truncates records. Missing addresses remain NULL and general phones remain
company-level. Repeating apply does not recreate contacts removed manually.

Focused importer checks (live cases use rollback-isolated synthetic records):

```sh
JOBMITRA_RUN_IMPORT_TESTS=1 .venv/bin/pytest -q tests/test_company_import.py
```

See [Phase 1C results, usage and review queue](docs/phase-1c-company-import.md).
The Phase 1C import remains closed; unresolved records require manual review before
a future import. Stage 2 does not rerun it.

Observed test outcomes and LAN latency are recorded in
[Phase 0 validation](docs/phase-0-validation.md).

## Unified office portal

Run one backend for Overview, Companies, JD Tracking, Candidate Desk, Staff and Tasks:

```sh
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open <http://127.0.0.1:8000/> (redirects to `/overview`). Restart an existing backend
with this command to load code changes; do not start separate module servers.
The shared top navigation and self-selected Working as selector are available in
all modules. The Windows database is verified at Stage 3 revision 0004.
Unavailable sections retain a navigable setup-pending page; startup never applies
migrations. See [routes, changed files and verification](docs/unified-portal-review.md).
