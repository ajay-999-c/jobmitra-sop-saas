# V12 PostgreSQL development integration

This is development integration, not a production cutover. SQLite support and
its default selection remain intact. No startup path creates or migrates a store.

The approved remote development schema is
`jobmitra_dev.jobmitra_v12_dev_20261123_integration` on `192.168.1.51:5432`.
It was created only after explicit approval, a fresh PostgreSQL backup and an
isolated restore rehearsal. A PostgreSQL `INSERT SELECT` copied the sealed
snapshot; no SQLite data import was repeated. All 664 application rows and 779
identity/classification entries reconciled before commit. Subsequent verification
fixtures and edits are confined to development.

`public` and `jobmitra_v12_stage` remain protected. The sealed snapshot still has
its 16 immutability guards. The development counterpart contains 13 application
tables plus a version manifest and preserved source identity/classification
metadata. All records in this environment are non-production; original test labels
are retained rather than inferred from missing UUIDs.

## Architecture and compatibility

- Explicit `JOBMITRA_V12_BACKEND=postgresql` selects the new engine. An invalid
  backend, missing development opt-in, unknown schema or manifest mismatch fails
  startup. PostgreSQL failure never falls back to SQLite or the legacy shell.
- Only `jobmitra_v12_dev_*` namespaces are accepted. Runtime SQL qualifies known
  tables and JSON/date helpers; its search path is `pg_catalog`. Protected-schema
  access, SQLite PRAGMAs, DDL and multiple runtime statements are refused.
- BIGINT IDs and raw UUID provenance are preserved. Interview-round IDs are opaque
  text keys, including imported keys that are not UUIDs. Money uses unbounded
  NUMERIC/Decimal. Original JSON and date/timestamp representations stay TEXT.
- Text identity and ordering use deterministic `C` collation to retain SQLite's
  binary behavior across Windows/macOS. Compatibility helpers cover only the
  existing parameterized query dialect; this is not arbitrary SQLite SQL emulation.
- Inserts use PostgreSQL RETURNING explicitly. Short writes serialize within the
  development schema, preserving existing receipt/stale-check ordering. Candidate
  and JD row locks plus a partial unique allocation index protect global eligibility.
- [All 58 trigger responsibilities](v12-postgres-trigger-parity.md) are accounted for
  in consolidated PostgreSQL guards, audits, constraints and existing services.
- PostgreSQL bootstrap batches eligibility/profile reads. The complete API payload
  matched its pre-change response; observed LAN bootstrap latency fell from about
  21 seconds to about four seconds. Tests verify query count does not grow per
  candidate. SQLite retains its existing read path.
- The original approved HTML, workspace layouts/CSS and Email Studio are unchanged.
  The final approved header adjustment left-aligns the existing tabs after the logo,
  preserving heights, tab styling and responsive wrapping. Eight
  implementation status/footer strings now say workspace instead of incorrectly
  claiming SQLite after PostgreSQL writes. The approved generator reproduces them.

## Windows requirements

Use the reviewed source revision containing the adapter and both SQL resources.
Follow [the final Windows CMD runbook](v12-windows-postgresql-validation.md) to
inspect a clean checkout, fetch and fast-forward to the reviewed feature release.

Python 3.12+ and the existing locked dependencies are sufficient: SQLAlchemy,
psycopg binary, FastAPI/Uvicorn, pydantic-settings, ReportLab and pypdf. Windows
private storage uses built-in ctypes/Win32 APIs; pywin32 is not required.

```powershell
uv sync --locked
```

Keep the existing PostgreSQL password in private configuration. Do not put it in
commands, screenshots, Git or reports. The following process-only settings select
the approved development copy without changing `.env` or a Windows service:

```powershell
$env:JOBMITRA_LOCAL_V12 = '0'
$env:JOBMITRA_V12_BACKEND = 'postgresql'
$env:JOBMITRA_V12_POSTGRES_DEVELOPMENT = 'true'
$env:JOBMITRA_V12_POSTGRES_SCHEMA = 'jobmitra_v12_dev_20261123_integration'
$env:JOBMITRA_DB_HOST = '192.168.1.51'
$env:JOBMITRA_DB_PORT = '5432'
$env:JOBMITRA_DB_NAME = 'jobmitra_dev'
$env:JOBMITRA_ATS_V2_ENABLED = 'true'
$env:JOBMITRA_UNIFIED_V12_ENABLED = 'true'
$env:JOBMITRA_UNIFIED_V12_PROPOSALS_ENABLED = 'true'

# This server currently has no TLS. Allowed only on the confirmed trusted office LAN.
$env:JOBMITRA_V12_POSTGRES_TRUSTED_LAN = 'true'
$env:JOBMITRA_DB_SSLMODE = 'disable'

$devRoot = Join-Path (Get-Location) 'runtime\v12-pg-dev'
New-Item -ItemType Directory -Force -Path $devRoot | Out-Null
$env:JOBMITRA_ATS_V2_RESUME_STORAGE_ROOT = Join-Path $devRoot 'resumes'
$env:JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT = Join-Path $devRoot 'proposals'
$env:JOBMITRA_DOCUMENT_STORAGE_ROOT = Join-Path $devRoot 'legacy-documents'

# Optional ordinary editing without a capability prompt, restricted to direct loopback.
$env:JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING = 'true'

uv run --no-sync python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8002 --workers 1
```

Reuse the existing configured database username/password. The server identity and
schema must match the approved copy. Outside the confirmed LAN, use certificate-
verified TLS (`JOBMITRA_DB_SSLMODE=verify-full`, appropriate `PGSSLROOTCERT`) or an
approved encrypted tunnel. Never enable direct editing for a non-loopback bind;
startup and request guards reject it. Protected deployments retain capability
authentication, same-origin checks and business authorization. A local actor is
explicitly unverified and receives no fabricated staff identity or supervisor role.

Browser URLs:

- `http://127.0.0.1:8002/` — approved V12 default navigation.
- `http://127.0.0.1:8002/workspace-v12/companies`
- `http://127.0.0.1:8002/workspace-v12/candidates`
- `http://127.0.0.1:8002/workspace-v12/jobs`
- `http://127.0.0.1:8002/email` — existing Email Studio, unchanged.
- `http://127.0.0.1:8002/api/ats-v2/health` — confirms `storage=postgresql`.
- `http://127.0.0.1:8002/health/ready` — validates the selected development store.

## Document preparation on Windows

All new native uploads share the configured resume parent:
`original/candidate_<ID>/`, `altered/candidate_<ID>/`, and `parsed/candidate_<ID>/`.
Parsed drafts preserve exact JSON in PostgreSQL and a checksum-verified private
JSON file; approvals reference that draft. Parsed PDFs retain their source in
`altered/` and extraction JSON in `parsed/`. Historical storage keys and metadata-only
JSON remain supported without automatic relocation or backfill.

Database access no longer needs a Mac SQLite file. Physical documents must still
exist under the explicitly configured Windows roots. Mac absolute paths are
provenance and are never converted into operational Windows paths.

Fifteen available original files were copied into separate Mac development storage
and verified byte for byte: ten file-backed resumes, four proposal PDFs and one
received signed-copy fixture. No Windows filesystem transfer is performed by this
task. Seven unresolved historical references remain unchanged, with truthful
unavailable-file responses; three other resume records are JSON/text-only.

To prepare Windows, securely transfer the verified source bytes and private
verification/document manifests outside Git. Supply real Windows source roots;
never assume the Mac paths in the manifest exist there. The copy tool uses live
development metadata and the manifest checksum, rejects source/target overlap,
creates private new files exclusively, verifies SHA/size and skips only existing
identical bytes. It does not update database rows or fabricate missing files.

```powershell
uv run --no-sync python scripts/copy_v12_dev_documents.py `
  --source-proof '<private final-staging-verification.json>' `
  --document-manifest '<private private-document-manifest.json>' `
  --source-resume-root '<verified Windows source resume root>' `
  --source-proposal-root '<verified Windows source proposal root>' `
  --report '<private output report path>'
```

Use local NTFS storage. UNC/device paths, reparse points/junctions, hard links,
untrusted ACLs and unsupported native APIs fail closed. Existing permissions are
never silently repaired. New private leaves receive protected ACLs for the process
actor, SYSTEM and administrators. Downloads return the bytes read through verified
handles, avoiding a second path open after checksum validation. Failed uploads
delete only proven unreferenced new files; uncertain commits retain bytes.

## Native Windows validation gate

1. Confirm backend health and all three approved workspace URLs before editing.
2. Run the focused native storage tests; Mac API simulations are not native results:
   `uv run --no-sync pytest tests/test_v12_proposal_storage.py tests/test_v12_resume_storage.py -q`.
3. Verify original/altered resume and proposal downloads against recorded SHA/size,
   including signed-copy exact bytes. Exercise JSON/PDF approval and a real DOCX
   upload. Keep the seven missing references unavailable until separately recovered.
4. Use clearly labelled development records for registration/editing, company/contact
   updates, JD creation/workflow/rounds, feedback, selection/joining and stale retries.
5. Verify non-loopback direct editing refuses startup, unauthenticated mutations are
   rejected in protected mode, and same-origin checks still apply.
6. Reconcile public/sealed fingerprints and document hashes. Verify production data
   and original SQLite files remain unchanged. Do not send test emails.

The actual PostgreSQL server is Windows; application/filesystem execution in this
task is macOS. Native Windows Python, NTFS ACL/junction behavior and the final
Windows storage paths remain a separate validation gate.

## Provisioning and rollback

The approved remote development schema already exists. Do not rerun provisioning
over it. The explicit setup command refuses existing schemas and never resets or
overwrites them. A future fresh namespace requires the verified source proof and
reviewed permissions/isolation before creation. `--clone-verified-stage` uses only
PostgreSQL server-side copying, with exact row reconciliation and no synthesized
historical audit events. Source labels and UUID provenance remain separately stored.

Stop only the development process and clear its process-only PostgreSQL selectors
to return to a previous profile. Start SQLite only if that machine already has its
verified isolated V3 database. Never create/migrate a database during rollback.
Retain the development schema and private files as evidence; do not delete them
automatically. No production configuration, NSSM service, firewall rule, default
production backend, Git commit or GitHub push is changed by this task.
