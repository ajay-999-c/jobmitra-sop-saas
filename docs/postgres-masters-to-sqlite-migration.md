# Experimental PostgreSQL master copy into SQLite ATS

This is an explicit, append-only, one-way copy. The new ATS reads its Company
Master, candidates, JDs, pipeline, rounds, activities and audit history from one
SQLite database. Legacy Companies, Candidate Desk and JD Tracking continue using
the existing PostgreSQL models and connection. There are no dual writes or
automatic synchronization jobs. PostgreSQL schema and rows are never modified.

## Source discovery and migration

All settings come from the existing application `Settings`, including the pinned
project-root `.env`; the scripts never rewrite `.env`, embed credentials, or
accept passwords on the command line. Use the same Python environment and
network-authorized launch context as the working legacy app. On this Mac,
standalone macOS Terminal can reach the LAN PostgreSQL server while IDE-launched
processes may not; a successful `nc` probe alone does not prove Python access.

Read-only discovery uses SQLAlchemy catalog inspection before selecting the
actual mapped tables. It performs authenticated `SELECT 1`, discovers the default
schema, column types, primary keys and foreign keys, then captures a single
`REPEATABLE READ`, `READ ONLY` snapshot. The selected models identify companies,
company contacts, candidates, domains/subdomains, candidate documents, optional
resumes and parse results. No employee, login or proposal records are imported.

From the project root on Mac/Linux:

```bash
.venv/bin/python scripts/inspect_postgres_ats_migration.py
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --dry-run
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --execute
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --verify
```

On Windows, substitute `.\.venv\Scripts\python.exe` for `.venv/bin/python`.
Configured database/storage roots must be absolute paths appropriate to that
machine. The scripts do not assume drive letters or translate inaccessible
Windows paths into Mac paths.

The importer defaults to dry run. Supported mutually exclusive modes are
`--dry-run`, `--execute` and `--verify`; scope flags are `--companies-only` and
`--candidates-only`. `--source-snapshot PATH` permits offline planning/verification
of a fingerprint-checked private snapshot; execution always re-reads live
PostgreSQL. `--report PATH` must remain outside Git tracking or under ignored
runtime storage. `--backup-directory PATH` defaults to the ignored backups tree.

Dry runs report aggregate counts, ready/already-imported counts, conflict codes,
missing required fields, normalized identity collisions and resume-copy status.
Console output omits candidate names, phone numbers, email addresses, resume
bodies and credentials. Detailed source snapshots and verification reports are
private files under `runtime/ats-master-migration/`, created without overwriting
existing files and with restrictive permissions. These must remain ignored.

Execution takes a short SQLite `BEGIN IMMEDIATE` write transaction, rebuilds the
plan under the lock, creates and verifies a timestamped SQLite backup using the
online backup API, applies the versioned schema upgrade, and appends records.
The backup includes committed WAL transactions and is closed as a self-contained
database. Existing SQLite rows are compared field-for-field before commit.
PostgreSQL is read again before commit; source counts and full selected-table
fingerprints must remain unchanged. Failed imports roll back SQLite and remove
only files newly copied by that failed attempt. The backup remains available.

## Schema version 2

`schema_v1.sql` preserves the exact previous seven-table schema. The reviewed
`upgrade_v1_to_v2.sql` adds the local UUID-keyed `companies` table and nullable
source-provenance columns. No existing business table or data row is dropped or
replaced. Fresh initialization and explicit upgrades produce the same validated
schema. The application never upgrades an existing database automatically.

Companies use their actual PostgreSQL UUID as their SQLite ID, with a unique
`legacy_postgres_id`. Existing JD company UUIDs remain stable. Company reference
triggers enforce eligible local company IDs for JD creation/reassignment and
prevent removal of referenced companies. An explicit orphan-reference check
supplements SQLite's foreign-key check, avoiding a destructive JD-table rebuild.

Candidates retain their existing SQLite integer IDs if already present. Imported
candidate IDs are deterministic 48-bit hashes of source table and UUID, safe in
both SQLite integers and JavaScript numbers. A unique `legacy_postgres_id` and
stable `PG-<UUID>` public code maintain source mapping. Hash/primary-key conflicts
stop the import; existing rows are never overwritten or silently reassigned.

Imported resumes use a unique `(legacy_source_table, legacy_postgres_id)` pair,
so the two legacy original-resume systems remain distinguishable. Source JSON and
timestamps preserve their original relationships and version facts. Imported
candidate/resume audit events are `CANDIDATE_IMPORTED` and `RESUME_IMPORTED`, with
migration time and source creation time recorded separately. They do not pretend
to be historical registrations or approvals. Existing audit events remain intact.

## Field mapping

| PostgreSQL source | SQLite representation |
| --- | --- |
| Company UUID/name/name key | Same UUID, source ID, name and normalized key |
| General phones/register IDs | JSON arrays, preserving original values |
| Company contacts | Ordered JSON contact records with available name/designation/phones/timestamps |
| Address/city/state/postal code | Corresponding local company fields |
| Candidate UUID | Unique source UUID, deterministic local ID and public code |
| Full name/mobile/email | Original values plus normalized identity fields |
| Role title/current location | `job_title` / `current_city` |
| Preferred locations/skills | Searchable normalized arrays; original arrays retained in source JSON |
| Experience months | Years for search; original month value retained |
| Domain/subdomain references | Resolved primary-domain name and preserved original/catalog evidence |
| Qualification | Original qualification |
| Current/expected amount | Numeric search field with cents retained; exact decimal source text archived |
| Monthly/annual/unknown period | MONTHLY / ANNUAL / NULL |
| CTC/gross/take-home/unknown | CTC / GROSS / IN_HAND / UNKNOWN |
| Explicit immediate or N days | 0 or N days; other notice text remains unknown and is displayed verbatim |
| Candidate source | Supported local enum plus original source text |
| Hometown/state/relocation/raw salary | Preserved source evidence and selected profile details |
| Creation/update timestamps | Original UTC timestamps, without refreshing them during import |

The actual PostgreSQL Company model has no industry, email, notes or active-state
column, and the Candidate model has no employer, summary, links or confirmed
availability field. Those facts are not fabricated. Availability remains
`TO_CONFIRM`; extant source companies are initially eligible. Source fields not
represented by first-class ATS columns remain in private provenance JSON.
Staff/actor metadata is excluded from imported provenance.

Name-only matches do not merge candidates. A collision with a native SQLite
candidate's normalized contact identity blocks import for review. Distinct source
UUIDs that share a normalized contact remain separate source records and are
explicitly flagged. Repeated source IDs cannot create duplicate imports.
Changed source records already imported are reported as conflicts rather than
overwriting local profiles or company snapshots.

## Resume copying and review

The importer reads the existing configured document root and safe generated
storage keys. It checks containment, file size and SHA-256 before copying bytes
unchanged to the ATS private storage root. Destination paths are generated,
relative and version-specific. Files are created exclusively, never overwritten.
The copied bytes are checked again before the transaction commits.

An inaccessible or mismatched file does not prevent preserving its metadata.
Its status remains `missing`, `hash_mismatch`, or another explicit review code;
the UI does not offer a false download. Original, modified and historical parsed
records remain distinct. Existing native current versions are preserved. A copied
legacy active original or latest versioned-document original can become current;
historical parse JSON remains inactive and requires a new factual review.

Historical parsed JSON can be inspected as imported evidence, but it is never
silently converted into an approved professional profile or fed into generation.
No extraction, AI, resume generation, or modification runs during migration.
Missing source files remain a documented incomplete file-copy result. Later file
recovery requires an explicit reviewed repair/version operation; reruns do not
mutate immutable imported resume rows in place.

## Runtime APIs and incremental company imports

The following new-workspace APIs now use SQLite without PostgreSQL connections:

- `GET /api/ats-v2/companies`: active imported company options.
- `GET /api/ats-v2/companies/{id}`: local company details, contacts and provenance
  identifiers, without exposing private source snapshots.
- Existing `/api/ats-v2/candidates`, profile, resume, JD, workflow, pipeline,
  history and activity endpoints remain on SQLite.

The legacy `/companies` page and `/api/companies` still use PostgreSQL. Add a
company there as before, then run an explicit incremental import:

```bash
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --dry-run --companies-only
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --execute --companies-only
.venv/bin/python scripts/migrate_postgres_masters_to_sqlite.py --verify --companies-only
```

Then choose **Refresh company list** in the new JD form. No dual writes or dummy
fallbacks occur. These commands append new source companies; changed existing
source snapshots stop for review. Candidate-only imports use the corresponding
`--candidates-only` flag. Do not resolve a conflict by deleting or resetting data.

## Verification and isolated workflow tests

The importer verifies source-ID reconciliation, existing-row preservation,
company/candidate/resume relationships, `integrity_check`, and
`foreign_key_check`. A repeated import with the same source adds no rows, files
or audit events. The verification report records original/final counts, warnings,
backup path, source fingerprints and copy results.

Run the imported-data workflow checker **after** migration:

```bash
.venv/bin/python scripts/verify_ats_imported_workflow.py
```

It safely clones the actual SQLite store and copied files into private temporary
storage. It tests imported company options, JD creation/edits/audit, actual
skills/experience/salary/notice filters, candidate profiles, associations,
duplicate rejection, progression, feedback, custom rounds, rename/reorder history,
and dashboard dates. PostgreSQL connections are forbidden in this new-workspace
test. All writes remain in the disposable clone, which is cleaned up afterward.
The live migrated candidate journeys are never used as write-test fixtures.

Synthetic tests cover non-empty native SQLite record preservation, WAL backups,
source and destination conflicts, no-clobber files, rollback, altered source
refusal, partial scopes, schema upgrade preservation, mapping boundaries and
idempotency. Existing legacy PostgreSQL regressions use disposable clusters.
See the private final verification report for this migration's executed results.

## Recovery from the pre-import backup

Only do this if intentionally rolling back the experimental SQLite state:

1. Stop all Jobmitra/Uvicorn processes that open this SQLite database.
2. Preserve another online backup of the current SQLite state before recovery.
3. Verify the selected pre-import backup with `PRAGMA integrity_check` and
   `PRAGMA foreign_key_check`. Use the exact path recorded in the execute report.
4. Restore with SQLite's backup API, not by copying a main database file over
   an active database with WAL/SHM sidecars. The following conceptual Python
   operation uses existing files; replace `backup_path` deliberately:

   ```python
   import sqlite3
   from contextlib import closing
   from pathlib import Path
   from jobmitra.core.config import Settings
   from jobmitra.modules.ats_v2.master_import import backup_database

   settings = Settings()
   backup_path = Path("/absolute/path/from/the/execute-report.sqlite3")
   backup_database(settings.ats_v2_database, Path("backups/ats-master-migration"))
   with closing(sqlite3.connect(backup_path.as_uri() + "?mode=ro", uri=True)) as source:
       assert source.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
       assert source.execute("PRAGMA foreign_key_check").fetchall() == []
       with closing(sqlite3.connect(settings.ats_v2_database.as_uri() + "?mode=rw", uri=True)) as target:
           source.backup(target)
   ```

5. Keep the private resume tree and reports. Import copies never changed old
   resume bytes. After a database rollback, new copied files may be unreferenced;
   quarantine/reconcile those files before a later import rather than deleting
   them or bypassing the no-clobber check.
6. A version-1 backup needs an explicit migration before the schema-2 ATS can
   reopen it. The legacy PostgreSQL workflows still work independently; the ATS
   feature can be disabled while reviewing/reapplying the migration.

No recovery step connects to or changes PostgreSQL.

## Implementation files

New migration code: `master_source.py`, `master_mapping.py`, `master_import.py`
under `src/jobmitra/modules/ats_v2/`; frozen `schema_v1.sql` and versioned
`upgrade_v1_to_v2.sql`; the three scripts shown above; mapping/import/upgrade tests;
and this guide. Updated ATS files: `database.py`, `schema.sql`, `companies.py`,
`router.py`, candidate/resume projections, scoped frontend modules/templates and
their tests. README and the ATS workspace guide describe the local architecture.
Legacy PostgreSQL engines/models/services, Alembic revisions and old JD templates
are unchanged. No local credentials or database files belong in Git.
