# V12 PostgreSQL staging snapshot

This migration creates `jobmitra_v12_stage` only. It does not switch FastAPI to
PostgreSQL or modify legacy `public` objects. The schema contains a complete
non-production snapshot, including explicitly classified development fixtures.

## Files and execution gates

- `001_stage.sql`: fixed versioned DDL for all 13 audited application tables,
  30 source-derived indexes, five translated views, three bookkeeping tables,
  ownership foreign keys and an immutable-snapshot guard function.
- `001_source_contract.json`: original SQLite DDL fingerprints, columns and
  relationships. No candidate/company row data is included.
- `scripts/stage_v12_postgres.py`: backup gate, strict source contract,
  classification, legacy identity checks, transaction import and reconciliation.
- `tests/test_v12_postgres_staging.py`: explicit opt-in tests on a disposable
  Unix-socket-only PostgreSQL restore. It cannot select the live PostgreSQL server.

Do not apply the SQL file independently. Before opting into the importer, obtain
a fresh custom-format PostgreSQL archive, full archive read validation, a
successful isolated restore with complete public-table row fingerprints, a
consistent SQLite backup, and a verified private document manifest. Store these
outside the repository and application runtime, with private filesystem access.
The importer requires `backup-verification.json` and its exact referenced files;
hashes, restore results and backup freshness are verified before connecting for
staging writes. Review target identity and confirm the schema is absent. Prefer
a DBA-provisioned separate staging database when one is available.

Example invocation with operator-supplied, verified paths:

```text
uv run --no-sync python scripts/stage_v12_postgres.py --verified-backup <protected-backup-directory> --baseline-v2 <original-v2-sqlite-path> --apply-staging
```

Use certificate-verified TLS (`verify-full`). The narrowly scoped
`--trusted-office-lan` option is only for an explicitly confirmed trusted LAN;
it uses a non-TLS connection. It is not appropriate on an untrusted network.
The completed office-LAN run used PostgreSQL 18 and a separately verified backup.

## Preservation and reconciliation

| SQLite source | PostgreSQL staging representation |
| --- | --- |
| Integer IDs, including candidate IDs above INT32 | BIGINT; original values retained |
| UUID mappings and opaque round IDs | Original TEXT plus source-qualified identity metadata |
| Salary fields, including SQLite REAL values | Unbounded NUMERIC; Decimal checked against original source JSON |
| Other REAL fields | DOUBLE PRECISION |
| Boolean flags | Original BIGINT 0/1 with source CHECK constraints |
| JSON | TEXT, validated with IS JSON; original whitespace/order retained |
| Dates and timestamps | Original TEXT, validated with explicit ISO parsing; no representation rewrite |
| Analytical date expressions | Explicit date casts and Asia/Kolkata office-day calculations |
| Document references | Unchanged source keys, raw metadata, SHA/size and source-root manifests |

Mac source roots remain provenance. They are not operational Windows paths.
Unresolved historical file references remain unresolved metadata; no bytes are
fabricated and no approved documents are regenerated.

Table import order is candidates, companies, JDs, rounds, JD memberships,
resumes, activities, recruitment events, company audit events, profile versions,
proposals, signed documents and proposal status events. Relationships include
the composite JD/round relationship and added parent-ownership foreign keys.
There is no `candidate_registration_extension` table in this actual source.

Source identity is the assigned store UUID plus table and original primary key,
independent of execution ID, filename and backup hash. Resume UUID provenance is
qualified by its original PostgreSQL source table. Embedded contacts receive
their own identity entries while remaining in the original company JSON.

All 13 tables are reconciled field by field, including exact JSON/text and
normalized exact numeric values. All five views are reconciled. PostgreSQL
validates foreign keys and uniqueness. Legacy public tables receive complete
row fingerprints before and after import, without writes to them. The actual
run additionally compared a full schema-only public dump, including ownership,
permissions, constraints and indexes, byte for byte before and after.

## Transactions, retry and rollback

The initial import uses one explicit transaction and an advisory transaction
lock. Any DDL, FK or reconciliation failure rolls back the uncommitted schema
and imported rows. No existing schema is replaced or adopted. An unknown or
conflicting schema fails without overwrite or automatic recovery.

After verification, statement-level guards reject INSERT, UPDATE, DELETE and
TRUNCATE on all 13 application tables and all three bookkeeping tables. This
is an immutable staging snapshot, not a writable application database.

A retry against the known version verifies every row, identity and document
manifest. Identical rows are skipped; changed values, added/missing rows or
different contracts are conflicts. Fresh backup hashes do not change source
identity. There is no ON CONFLICT UPDATE, destructive reset or automatic schema
deletion. On an uncertain COMMIT outcome, inspect read-only and validate before
retrying. Keep a completed schema as evidence; any later retirement requires
separate approval. The application continues to use its original SQLite source.

## Development classification

Original V2 rows must all be present with unchanged source fields. The three
reviewed preview/test candidates and three companies are identified explicitly;
their JDs, memberships, activities, additional history and proposal evidence are
classified by verified parent relationships. Unreviewed unmapped identities
fail closed. `source_identity_map.classification` records imported versus
development/test scope. No record is silently promoted into production.

## Backend work required before integration

1. Add an explicit PostgreSQL store adapter and startup/schema validation;
   retain SQLite support. `database.py` currently depends on PRAGMAs,
   sqlite_master, BEGIN IMMEDIATE, WAL and SQLite schema fingerprints.
2. Port parameterized queries in candidates, companies, jobs, unified/profile,
   resume and proposal stores: JSON1 functions, date/strftime functions,
   COLLATE NOCASE, SQLite conflict syntax, placeholder conventions and lastrowid.
   Use explicit schema qualification and INSERT RETURNING.
3. Translate and test all 58 SQLite business/audit triggers. The staging freeze
   guards intentionally do not claim live workflow parity. Preserve append-only
   history, request idempotency, actor provenance and stale-update checks.
4. Replace whole-writer serialization with candidate/JD row locks and proven
   allocation constraints. Exercise eligibility, stage transitions and joining
   races on PostgreSQL before allowing concurrent application writes.
5. Select a production dataset explicitly. Review the 120 test application rows
   and five test embedded contacts separately; staging is not production data.
6. Recover the seven missing legacy files from Windows/private backups where
   available. Map verified storage keys to separate protected Windows roots;
   verify authorization, traversal/reparse protections, upload/download hashes
   and historical document retention. Do not rewrite source path provenance.
7. Provision production roles/least privilege, trusted TLS or an encrypted
   tunnel, monitoring, backups and a separately approved cutover/rollback plan.
   Do not repoint the app to this frozen staging schema.

No deployment, service change, live adapter switch or production promotion is
part of this staging migration.
