# Windows Stage 2 / Stage 3 deployment readiness — 2026-10-21

Status: schema preparation is ready for approval; migration and backup execution
have **not** been performed. Resume upload/download needs private storage setup.
This report does not authorize deployment.

## Verified live, read-only

Connected using database-enforced read-only transactions to
`192.168.1.51:5432 / jobmitra_dev` as `jobmitra_app`.

| Check | Observed result |
| --- | --- |
| PostgreSQL | 18.6 |
| Applied Alembic revision | `0002_jd_tracking` (one revision row) |
| Current public tables | `alembic_version`, `companies`, `company_contacts`, `staff_members`, `job_requirements`, `job_recruiters`, `activities`, `tasks` |
| Existing records | 131 companies, 108 contacts, 1 JD, 2 staff |
| Current schema | `public`; search path `"$user", public` |
| Table ownership | All eight tables owned by `jobmitra_app` |
| Required privileges | CONNECT; public USAGE/CREATE; existing-table owner rights; SELECT/UPDATE/REFERENCES verified |
| Conflicts | No pending table, index, unique-index or table-type name collisions in public |
| JD focus | Neither `current_work_focus` nor `ck_job_work_focus` exists yet |
| Row-level security / event triggers | None found |
| Extensions | `plpgsql` 1.0 only; pgvector is not enabled here |
| Connection security | Configured `sslmode=prefer`; this connection negotiated **no TLS** |

Company full-row fingerprints, including IDs, timestamps, arrays and every field:

- `companies`: `d499a2676b1df064b09a9f252af27d80139a953e3b6737d5f8b0d382de1c91af`
- `company_contacts`: `fc649530ce3f2fdb6599f769aa76e9835ef463e8abf45b36e9dd38643206d001`

No row values or credentials are included. These are a point-in-time baseline;
recapture immediately before deployment with employee writes paused.

## Revision chain and reviewed operations

`0001_company_management → 0002_jd_tracking → 0003_jd_work_focus → 0004_candidate_desk`

There is one head, `0004_candidate_desk`. The reviewed pending range is **0002→0004**;
0001 and 0002 must not be reapplied or stamped.

`0003_jd_work_focus` adds nullable TEXT `job_requirements.current_work_focus` and
CHECK `ck_job_work_focus` allowing the seven approved focus codes. No default,
backfill, UPDATE of JDs, fake candidate progress, or timestamp/version change.
The existing JD receives NULL for the new field; all previous field values remain.

`0004_candidate_desk` creates these seven tables:

| Table | Purpose and relationships |
| --- | --- |
| `work_domains` | Work-domain catalog with stable unique keys and normalized names |
| `work_subdomains` | Child catalog; FK to work_domains |
| `candidates` | Profile, contact, qualifications, skills, location/salary fields; optional domain and parent-consistent subdomain FKs |
| `candidate_documents` | Private file metadata and versions; candidate FK, optional uploader staff FK, same-candidate source-document FK |
| `candidate_visits` | Repeat visits; candidate and optional recording-staff FKs |
| `job_search_requests` | Candidate-led requests; candidate and assigned-staff FKs; independent of JDs |
| `resume_parse_results` | ChatGPT/Claude JSON history linked to an original resume version, with optional staff attribution/review |

Stage 3 adds 13 foreign keys, all `ON DELETE RESTRICT`, nine explicit indexes,
seven primary keys, nine unique constraints and 29 CHECK constraints. The existing
`staff_members.id` UUID primary key is present and compatible. All other references
are within the new tables. UUIDs are supplied by application code; no UUID or
vector extension is needed. Full definitions: [Stage 3 schema](stage-3-schema.md).

[Combined reviewed SQL](../outputs/windows-migration/0002-to-0004-reviewed.sql)
was freshly generated offline from current migration source. It has one BEGIN/
COMMIT, two ALTER TABLE statements for job_requirements, seven CREATE TABLEs,
nine CREATE INDEX statements and two Alembic revision updates. **No DROP, DELETE,
TRUNCATE, INSERT, company-table ALTER, extension/role/grant change or business-data
UPDATE appears in the upgrade.** Both downgrade functions are destructive and
must not be used as an automatic rollback once candidate data exists.

Source / SQL SHA-256:

```text
0003_jd_work_focus.py:
55eafd17b3799a279b4b384536c17156e650eddd615cd02419ef4e08beb9ee73
0004_candidate_desk_add_paperless_candidate_desk.py:
180d713e50295877d52be31283e480f79d3cbe3a650c3569e618e2a99783d753
0002-to-0004-reviewed.sql:
1cfa58fab07740c8e5520a9064b96f49381a93d4aa88262ad961890f7a688e1d
```

The reviewed migration cannot alter company/contact rows through its SQL; there
are also no database event triggers to introduce DDL side effects. Verify complete
row hashes and column definitions before/after, with other writers stopped.

The ALTER TABLE/check validation can acquire an exclusive lock, even though the
new column is nullable. Use a brief maintenance window. Current migration engine
uses a 5-second statement timeout; the command below temporarily allows 60 seconds
per statement, including lock waits. Do not keep retrying a blocked migration
without investigating the lock. See [PostgreSQL ALTER TABLE](https://www.postgresql.org/docs/18/sql-altertable.html).

## FastAPI and private files

- Current settings load the project-root `.env` independently of the process working
  directory. Shell `JOBMITRA_*` settings take precedence; none were present
  in the inspection process. No inherited PG overrides were present either.
- Target is correct; password is nonempty and wrapped in SecretStr. URL.create
  handles password punctuation. No password or connection URL was printed.
- Pool size 3, max overflow 0, pre-ping enabled; sessions/connections are closed.
  SQL logging is disabled and SQLAlchemy hides parameters.
- `sslmode=prefer` does not require encryption. TLS was absent in this inspection;
  changing TLS policy requires separate configuration work, not this migration.
- `JOBMITRA_DOCUMENT_STORAGE_ROOT` is **unset**. Upload/download therefore remains
  unavailable until an explicit existing private directory is configured.
- File limit is 12 MiB (`12582912`). Files are PDF/DOCX with opaque keys, hashes and
  metadata in PostgreSQL; resume bytes are not stored in the database.
- FastAPI runs on Mac: a Windows `C:\...` path is not a usable local path. A Mac
  private directory is the simplest current option. If using a mounted Windows
  share, verify permissions and atomic hard-link support: storage uses `os.link`
  for publication, and not every SMB mount supports that operation. No mount or
  Windows permission changes were made.
- Suggested future local value: an existing private directory outside static assets,
  e.g. `/Users/mac/Documents/jobmitra/private-documents`, owned by the backend user
  with restrictive permissions. This directory has **not** been created here.
- Keep the database and file directory in coordinated backups. `pg_dump` does not
  back up resume files. No auth system is added: Working as is unverified attribution.

## Mac Terminal procedure — execute only after separate approval

The existing `scripts/backup_database.py` is unsuitable: it deliberately accepts
only localhost and revision 0001. Do not repurpose it against Windows. PostgreSQL
18.6 `pg_dump` and `pg_restore` are installed on this Mac.

Pause employee writes and stop the regular FastAPI server before the baseline and
backup; keep it stopped until verification finishes. Run the following in one Mac
Terminal tab. Passwords go only into tool prompts or the existing local `.env`.
No password belongs in a command, URL, shell history or report.

### 1. Target and baseline

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
umask 077
unset PGHOSTADDR PGSERVICE PGSERVICEFILE PGOPTIONS
export JOBMITRA_DB_HOST=192.168.1.51
export JOBMITRA_DB_PORT=5432
export JOBMITRA_DB_NAME=jobmitra_dev
export JOBMITRA_DB_USER=jobmitra_app

mkdir -p backups
jobmitra_backup_dir="$(mktemp -d "$PWD/backups/pre-stage3-XXXXXX")"
chmod 700 "$jobmitra_backup_dir"
.venv/bin/python scripts/stage2_preflight.py --output "$jobmitra_backup_dir/before.json"
```

Stop on any failure. Check the following assertion before proceeding (the report
contains safe counts/hashes, not row values):

```sh
.venv/bin/python - "$jobmitra_backup_dir/before.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
assert r['status'] == 'captured'
assert r['target'] == dict(host='192.168.1.51', port=5432,
                          database='jobmitra_dev', user='jobmitra_app')
assert r['revision'] == ['0002_jd_tracking'], 'STOP: re-review actual pending range'
new = {'work_domains','work_subdomains','candidates','candidate_documents',
       'candidate_visits','job_search_requests','resume_parse_results'}
assert not new.intersection(r['tables']), 'STOP: existing Stage 3 objects'
print('Baseline target/revision/table scope verified')
PY
```

### 2. Full database backup

```sh
PGOPTIONS='-c default_transaction_read_only=on' PGSSLMODE=prefer \
pg_dump -h 192.168.1.51 -p 5432 -U jobmitra_app -d jobmitra_dev -W \
  --format=custom --file="$jobmitra_backup_dir/jobmitra_dev-before-0003-0004.dump"
```

Proceed only if pg_dump exits successfully. The full archive includes all current
schemas/data, ownership and ACL definitions; it does not create roles or back up
server configuration. This is a consistent logical snapshot. With writes paused,
it also matches the separately captured baseline.

```sh
pg_restore --list "$jobmitra_backup_dir/jobmitra_dev-before-0003-0004.dump" \
  > "$jobmitra_backup_dir/archive-catalog.txt"
pg_restore --file=/dev/null "$jobmitra_backup_dir/jobmitra_dev-before-0003-0004.dump"
shasum -a 256 "$jobmitra_backup_dir/jobmitra_dev-before-0003-0004.dump" \
  > "$jobmitra_backup_dir/archive.sha256"
```

Require both pg_restore commands to succeed. Listing and full archive decoding
verify readability, **not a successful restore**. Ideally rehearse restoration to
an isolated local database before Windows deployment. Preserve the archive privately;
`backups/` is ignored by Git. [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/18/app-pgdump.html).

### 3. Recheck reviewed source and generate SQL without connecting

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from hashlib import sha256
for name, expected in {
 '0003_jd_work_focus.py': '55eafd17b3799a279b4b384536c17156e650eddd615cd02419ef4e08beb9ee73',
 '0004_candidate_desk_add_paperless_candidate_desk.py': '180d713e50295877d52be31283e480f79d3cbe3a650c3569e618e2a99783d753',
}.items():
 assert sha256((Path('migrations/versions') / name).read_bytes()).hexdigest() == expected
print('Reviewed migration source hashes match')
PY
.venv/bin/alembic upgrade 0002_jd_tracking:0004_candidate_desk --sql \
  > "$jobmitra_backup_dir/reviewed-upgrade.sql"
shasum -a 256 "$jobmitra_backup_dir/reviewed-upgrade.sql"
```

Require SQL hash `1cfa58fab07740c8e5520a9064b96f49381a93d4aa88262ad961890f7a688e1d`.
Stop if anything differs. The pinned range above is offline SQL generation only.

### 4. Apply only the reviewed pending revisions — APPROVAL REQUIRED

Immediately before applying, re-read the revision, without network diagnostics:

```sh
.venv/bin/python scripts/stage2_preflight.py --output "$jobmitra_backup_dir/pre-apply.json"
.venv/bin/python - "$jobmitra_backup_dir/before.json" "$jobmitra_backup_dir/pre-apply.json" <<'PY'
import json, sys
before, now = (json.load(open(p)) for p in sys.argv[1:])
assert now['status'] == 'captured' and now['revision'] == ['0002_jd_tracking']
for key in ('target', 'tables', 'columns', 'company_tables', 'extensions'):
 assert now[key] == before[key], f'STOP: baseline changed: {key}'
print('Fresh baseline matches; keep all other migration processes stopped')
PY
```

**Only after approval and all preceding checks pass:**

```sh
JOBMITRA_DB_STATEMENT_TIMEOUT_MS=60000 \
.venv/bin/alembic -x allow_remote=true upgrade 0004_candidate_desk
```

The explicit endpoint applies 0003 then 0004 from confirmed revision 0002. Do not
use `upgrade head`, `stamp`, autogenerate, or execute the SQL file in addition to
Alembic. No superuser or new role is required. The existing Alembic remote guard
requires the explicit `-x allow_remote=true` opt-in. PostgreSQL transactional DDL
and the current migration environment place this upgrade in one transaction.
If it fails, stop and re-read the actual revision; do not assume success, manually
stamp it, or run a downgrade. This report has not executed that command.

### 5. Read-only verification before restarting employees

```sh
.venv/bin/python scripts/stage2_preflight.py --output "$jobmitra_backup_dir/after.json"
.venv/bin/python - "$jobmitra_backup_dir/before.json" "$jobmitra_backup_dir/after.json" <<'PY'
import json, sys
before, after = (json.load(open(p)) for p in sys.argv[1:])
assert after['status'] == 'captured' and after['revision'] == ['0004_candidate_desk']
for key in ('target','company_tables','columns','extensions'):
 assert after[key] == before[key], f'STOP: preservation check failed: {key}'
new = {'work_domains','work_subdomains','candidates','candidate_documents',
       'candidate_visits','job_search_requests','resume_parse_results'}
assert set(after['tables']) == set(before['tables']) | new
print('Revision, exact table scope, complete company/contact rows, columns and extensions verified')
PY
```

Inspect new-table constraints, empty row counts and the new nullable column using
read-only psql. The password is entered only at the prompt:

```sh
PGOPTIONS='-c default_transaction_read_only=on' \
psql -X -h 192.168.1.51 -p 5432 -U jobmitra_app -d jobmitra_dev -W -v ON_ERROR_STOP=1
```

Then run:

```sql
BEGIN READ ONLY;
SELECT version_num FROM public.alembic_version;
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema='public' AND table_name='job_requirements'
  AND column_name='current_work_focus';
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid='public.job_requirements'::regclass AND conname='ck_job_work_focus';
SELECT count(*) AS existing_jds,
       count(current_work_focus) AS nonnull_focus
FROM public.job_requirements;
SELECT 'work_domains' AS table_name, count(*) FROM public.work_domains
UNION ALL SELECT 'work_subdomains', count(*) FROM public.work_subdomains
UNION ALL SELECT 'candidates', count(*) FROM public.candidates
UNION ALL SELECT 'candidate_documents', count(*) FROM public.candidate_documents
UNION ALL SELECT 'candidate_visits', count(*) FROM public.candidate_visits
UNION ALL SELECT 'job_search_requests', count(*) FROM public.job_search_requests
UNION ALL SELECT 'resume_parse_results', count(*) FROM public.resume_parse_results;
SELECT conrelid::regclass, conname, pg_get_constraintdef(oid), convalidated
FROM pg_constraint
WHERE contype='f' AND conrelid IN (
 'public.work_subdomains'::regclass, 'public.candidates'::regclass,
 'public.candidate_documents'::regclass, 'public.candidate_visits'::regclass,
 'public.job_search_requests'::regclass, 'public.resume_parse_results'::regclass
) ORDER BY 1,2;
ROLLBACK;
\q
```

Expect revision 0004, nullable TEXT with no default, the seven-value focus CHECK,
all previous JDs with NULL focus, seven empty tables, and 13 validated RESTRICT FKs.
Counts of existing company/contact rows must equal the fresh baseline (currently
131/108). No seed data or candidate inserts are part of verification.

Restart the one FastAPI server from the repo root only after verification succeeds:

```sh
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Read-only smoke checks: `/health/ready`, `/overview`, `/companies`, `/requirements`,
`/staff`, `/tasks`, `/candidates`, `/office-visits`, `/job-search-requests`, `/domains`.
Do not test writes on Windows as part of this approval. Resume upload remains
unavailable until storage is explicitly configured and verified separately.

If a committed deployment needs recovery, keep the app stopped, retain the current
DB/files, restore the backup to a separate recovery database first and verify it.
A production overwrite or downgrade requires separate approval. No automatic
DROP/clean/restore-over-live command is included.

## Outcome of this readiness task

Read-only Windows checks and offline SQL review completed. No backup, migration,
new table, seed, candidate/file write, role/grant/extension change or commit/push
was performed. Existing uncommitted portal changes were preserved. Only this
report and the combined reviewed SQL artifact were added to the project.
