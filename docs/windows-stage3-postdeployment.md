# Stage 3 post-migration setup — 2026-10-21

The user reported executing upgrades 0003/0004. A new database-enforced read-only
inspection confirmed Windows `192.168.1.51:5432`, `jobmitra_dev`, is at
`0004_candidate_desk`. No migration or table creation was executed in this task.

## Verified records and preservation

| Existing records | Before checks | After rollback |
| --- | ---: | ---: |
| Companies | 131 | 131 |
| Company contacts | 108 | 108 |
| JDs | 1 | 1 |
| Staff | 2 | 2 |
| JD activities | 1 | 1 |
| JD recruiters / tasks | 0 / 0 | 0 / 0 |

All 15 public table row fingerprints matched before and after the synthetic test.
Company/contact fingerprints also matched the pre-migration readiness baseline.
No historical Company/JD/Staff record was edited. Stage 3 tables remain empty
following verification; temporary records were rolled back.

## Persistent private storage configuration

The local, Git-ignored `.env` now contains these actual application setting names:

```dotenv
JOBMITRA_DOCUMENT_STORAGE_ROOT=/Users/mac/Documents/jobmitra/private-documents
JOBMITRA_DOCUMENT_MAX_BYTES=12582912
```

Only those settings were changed; connection settings and credentials were retained.
The `.env` file is mode 0600. No credentials or connection URLs were printed.

- Directory exists outside the Git repository and public static/template directories.
- Owner: the Mac user running FastAPI; directory mode **0700**.
- Uploaded files use opaque UUID keys, mode **0600**, with no public static mount.
- Upload limit: **12 MiB per file**. Accepted formats: PDF and DOCX.
- The existing storage implementation validates content and publishes through an
  atomic hard link. Actual write, publication and read operations passed on this
  directory; no Windows share is involved.
- The directory persists independently of application and test processes. No
  automatic fallback or temporary-root configuration was introduced.
- No genuine resumes were used or moved. All four synthetic files were removed
  after verification, leaving the directory empty and ready for actual uploads.

## Link integrity

The existing services, schema and APIs were reused unchanged:

- `CandidateDocumentService.upload_document` creates immutable per-kind versions,
  preserves the candidate UUID and stores metadata/hash/opaque key in PostgreSQL.
- Modified resumes require explicit review and an original document belonging to
  that candidate. Source-document IDs remain attached to each modified version.
- `download_document` checks candidate/document association before resolving the
  private key. The public response does not contain the private storage key/path.
- `ResumeParseService` retains pasted ChatGPT/Claude JSON against the exact original
  document ID/version. It does not replace candidate-confirmed fields or silently
  move old JSON results to a newer resume. JSON remains in PostgreSQL; file bytes
  remain in the private Mac directory.

## Focused Windows workflow checks

**11 scenario checks passed**, using the existing FastAPI app and SQLAlchemy
services against the deployed Windows database:

1. Synthetic registration and readback with a stable candidate UUID.
2. Editing, explicit NULL handling, stable identity and stale-version rejection.
3. Duplicate warning without a second unintended insertion.
4. Automatic walk-in visit and a repeat office visit linked to the same candidate.
5. Job-search request creation, synthetic staff assignment and closure.
6. Original PDF v1 / DOCX v2 uploads and byte-for-byte/hash-exact downloads;
   the original v1 remained downloadable after v2.
7. Modified resume v1/v2 linked to their respective original versions.
8. Persistent configured storage, atomic hard-link publication and 0600 file modes;
   a newly constructed storage instance could read each file.
9. ChatGPT/Claude JSON linked to original v1, review status update, unchanged manual
   skills, and rejection of a parse attached to a modified resume.
10. A download using the wrong candidate ID returned 404.
11. Candidate, profile, office-visit, job-search and domain pages rendered with the
    unified navigation against the deployed schema.

The TestClient dependency used SQLAlchemy sessions with savepoints inside an outer
Windows transaction. Service transaction boundaries were exercised, but the outer
transaction was always rolled back. This tests actual Windows schema/constraints
and API workflows without retaining synthetic data; it is not a durable-commit or
backup-restore test. A synthetic staff member was used for attribution and rolled
back as well. Only the four file keys created by the test were removed—no broad
file deletion or historical-row cleanup was performed.

The run emitted one existing Starlette/httpx deprecation warning. No full test suite,
external AI call, unrelated network diagnostic or repeated migration test was run.
Safe machine-readable results are in the Git-ignored local file
`outputs/windows-migration/stage3-postdeployment-checks.json`.

## Running backend

The unified backend was started at <http://127.0.0.1:8000/> with the new settings:

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

It uses Windows PostgreSQL and the persistent Mac directory above. Settings load
`.env` from the current working directory and are cached per process; restart the
backend after future changes. Shell environment values override `.env`.

One read-only startup smoke pass returned HTTP 200 for all nine checked routes:
`/health/ready`, `/overview`, `/companies`, `/requirements`, `/staff`, `/candidates`,
`/office-visits`, `/job-search-requests` and `/domains`.

## Remaining deployment limits

- Database backups and the private directory must be backed up together. Automated
  backup/restore and disaster-recovery rehearsal are not configured by this task.
- Resume bytes reside on this Mac. Other backend machines need an explicitly
  arranged compatible shared/private storage solution; a Windows drive path alone
  does not work from the Mac backend.
- The app remains bound to localhost, with the existing self-selected staff
  attribution rather than verified login. File permissions do not provide web-user
  authorization. Multi-device exposure/access control is separate deployment work.
- Existing `sslmode=prefer` negotiated no TLS in the read-only inspection. Encryption
  configuration was not changed.
- PDF/DOCX structure checks are not malware scanning. ChatGPT/Claude history accepts
  manually supplied JSON; no AI provider integration or external parsing was added.
- Full candidate profile edit history beyond version/timestamp remains outside the
  approved seven-table Stage 3 schema. pgvector is not enabled and is not needed here.

No model, migration, business service, new database table, commit or push was made.
