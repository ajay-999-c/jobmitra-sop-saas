# Moving Jobmitra PostgreSQL from macOS to Windows

This document records the original database transfer. The later approved
[Stage 2 deployment](stage-2-windows-deployment.md) added five tables on 2026-10-20
and advanced Windows to revision `0002_jd_tracking`, preserving the transferred data.

Requested on 2026-10-19. The FastAPI backend remains on macOS. PostgreSQL moves
from `127.0.0.1:5432/jobmitra_dev` to `192.168.1.51:5432/jobmitra_dev`; the
application user remains `jobmitra_app`. The existing `.env` already targets the
Windows address. No password or connection URL is included in these instructions,
backup manifests or tool output.

## Current status

The source has 131 companies, 108 contacts and revision `0001_company_management`.
The Windows server is PostgreSQL 18.6 and its target database was inspected as
empty. Connectivity now succeeds from this session as well as from macOS Terminal.
No server configuration changes were needed.

The company schema and all data have been restored and verified on Windows:
131 companies, 108 contacts and the original Alembic revision. Every stored field,
UUID and timestamp matches the source. Column definitions, defaults, constraints
and indexes also match. The local source remains unchanged.

pgvector 0.8.7 is available on Windows but is not enabled in the target database.
None of the source's table or view columns uses a non-builtin type, and the decoded
archive contains only the two business tables, revision ledger and extension
metadata. The unused extension was explicitly deferred so it does not block core
Company Management. Its activation requires a PostgreSQL administrator; the app
account is not a superuser and has no administrator role available.

The working login is `jobmitra_app`. Creation of a separate runtime login named
`jobmitra_dev` was requested and authorized, but that login does not yet exist on
Windows. The app account cannot create roles. Its administrator-assisted setup
command is prepared below; configuration is not changed to a nonexistent user.

## Verified source backup

The private backup directory is `backups/20261019T090641630542Z/`:

- `jobmitra_dev.dump`: custom-format PostgreSQL 18.6 dump, 19,122 bytes.
- `manifest.json`: source version, extension versions, revision, row counts,
  archive checksum and hashes of every field in all three tables.
- `reviewed-restore-schema.sql`: decoded and inspected table, index and constraint SQL.
- `reviewed-restore.list`: the selected archive entries, preserving the separately
  enabled Windows pgvector extension and its ownership/comments.

The dump and manifest use owner-only permissions. `backups/` is ignored by version
control. The dump was made with an exported repeatable-read snapshot shared with
the row-hash checks. The archive catalog was checked and the entire archive was
successfully decoded without executing its SQL. All 131 company rows, 108 contact
rows and one Alembic version row are present. The source database was not modified.
Original IDs, timestamps, source Register IDs, text arrays and NULL fields are
included. The original and cleaned Excel workbooks are not involved in this transfer.

To create a fresh backup if source records change:

```sh
.venv/bin/python scripts/backup_database.py --host 127.0.0.1
```

Keep employees from writing to the old database during cutover. After verification,
use Windows as the sole runtime source of truth; retain the local database and
backup as a fallback rather than continuing to edit both copies.

## Optional pgvector administrator step

Before future vector matching is implemented, run the following in macOS Terminal,
entering the PostgreSQL administrator password only at the local prompt:

```sh
psql -h 192.168.1.51 -p 5432 -U postgres -d jobmitra_dev -W \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Alternatively, connect to the same Windows database as an administrator in pgAdmin
or SQL Shell and execute `CREATE EXTENSION IF NOT EXISTS vector;`. No installation
download is required: Windows already reports pgvector 0.8.7 as available. This
preserves the source's optional extension without adding vector columns or AI
dependencies to Company Management. Do not grant superuser privileges to the app.

## Requested `jobmitra_dev` runtime login

Run this single command in an interactive macOS Terminal from the project root:

```sh
.venv/bin/python scripts/create_windows_login.py
```

The script prompts privately for the Windows PostgreSQL `postgres` administrator
password. `--admin-user NAME` can select a different administrator. It reuses the
existing app password from `.env` for the new runtime login, without printing it
or changing the old `jobmitra_app` account. The administrator password stays in
process memory and is not saved. The server receives a SCRAM verifier for the new
login's password rather than a plaintext password in CREATE ROLE SQL.

An administrator transaction creates `jobmitra_dev` with no superuser, database
creation, role creation, replication or RLS-bypass privileges. It grants database
CONNECT, schema USAGE, company/contact SELECT/INSERT/UPDATE/DELETE and read-only
access to the Alembic ledger. It also enables the already available pgvector
extension. No business rows or table ownership are changed. An existing role of
the same name is refused rather than resetting its credentials or permissions.

The script then verifies the new login and schema, and updates only
`JOBMITRA_DB_USER` in `.env`, preserving its password and owner-only permissions.
A private timestamped login-setup JSON report is written to
`outputs/windows-migration`. Any backend process must be restarted afterward.
If login verification fails after administrator work commits (for example, because
an existing access rule permits only `jobmitra_app`), the `.env` username is left
unchanged; the result explicitly reports that the administrator transaction
committed. Review that state before rerunning; do not reset a password blindly.

This is a required manual administrator-authentication step, not a request to send
credentials in chat. Until it is completed, the already verified backend remains
configured with `jobmitra_app`. The source-backup helper independently defaults to
the original local `jobmitra_app` account, even after changing the Windows login.

## Guarded restore and verification

Run from the project root with the Windows settings in `.env`:

```sh
.venv/bin/python scripts/migrate_to_windows.py \
  --backup backups/20261019T090641630542Z --check --defer-unused-vector
.venv/bin/python scripts/migrate_to_windows.py \
  --backup backups/20261019T090641630542Z --apply --defer-unused-vector
jobmitra-db health
jobmitra-db benchmark --iterations 100
```

The helper checks the archive checksum and confirms that local source rows have
not changed since backup. It requires PostgreSQL 18, the exact Windows target and
the expected schema. Extension versions must match; `--defer-unused-vector` permits
only pgvector to be missing after confirming that source columns use builtin types.
Omit that flag to require pgvector to be enabled before restore. The helper refuses existing application
objects or records that differ from the backup. A matching completed restore is a
verified no-op. No `--clean`, `--create`, deletion, truncation or record update is
used. Restore inserts schema and data into the empty target in one transaction,
with errors stopping the batch. The application user owns the restored tables.

The source pgvector extension entries are omitted from restore because enabling
it belongs to an administrator. Any existing Windows ownership and comments are preserved.
All table columns/defaults, primary/unique/check/foreign-key constraints and indexes
are compared after restore, alongside hashes of all data and extension versions.
The local source is checked again for changes. Private timestamped JSON reports
record preflight and apply results without row values or credentials.

Applied evidence:

- [Verified backup manifest](../backups/20261019T090641630542Z/manifest.json)
- [Successful preflight](../backups/20261019T090641630542Z/20261019T092053835535Z-check.json)
- [Verified restore](../backups/20261019T090641630542Z/20261019T092106482972Z-apply.json)
- [Backend and migration validation](../outputs/windows-migration/validation.json)

## Backend checks after transfer

- `jobmitra-db health`: passed; connection check 342.690 ms.
- 100 repeated `SELECT 1` queries: mean 11.508 ms, median 8.827 ms,
  p95 24.370 ms, min 5.076 ms, max 65.546 ms.
- FastAPI readiness, Company Directory and company-detail read requests: HTTP 200.
  The directory contains 131 companies from Windows. No smoke-check writes were made.
- Repeating the restore returned `already_migrated`, without record changes.

These are client-observed LAN timings, not a business-workload throughput benchmark.

Restart any running backend process after switching settings, because settings and
connection pools are cached per process. No restart is necessary for new CLI
processes. Existing Alembic and Excel importer guards still allow only the original
local database; this transfer does not loosen those guards or rerun migrations.

## Focused checks

```sh
.venv/bin/pytest -q tests/test_database_transfer.py
.venv/bin/ruff check scripts/backup_database.py scripts/migrate_to_windows.py scripts/create_windows_login.py tests/test_database_transfer.py
```

Nine safety tests passed: unexpected archive extension metadata, preservation of
selected data entries, rejection of the wrong target and a modified archive before
opening database connections, refusal to overwrite private reports, and login
setup safeguards for administrator privileges, existing roles, SCRAM password SQL
and the correct target before prompting. Administrator login setup is unit-tested
and awaits the local password prompt; the database restore and backend checks were
verified live. Ruff passed. No unrelated full regression suite was run.
