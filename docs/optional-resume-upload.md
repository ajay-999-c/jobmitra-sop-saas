# Optional resume upload — Phase 1

Candidate creation remains a JSON request. Add Candidate and Register Walk-in can optionally
upload an original PDF/DOCX after successful creation. A failed upload leaves the registered
candidate intact and provides a profile link for retry; it never repeats candidate creation.
Edit Candidate and existing document/modified-resume/parse-history workflows are unchanged.

## Files and responsibilities

- `src/jobmitra/modules/candidates/models.py`: additive `CandidateResume` model.
- `src/jobmitra/modules/candidates/resumes.py`: grouped prototype routes, public metadata,
  transactional version service, bounded upload, history, preview and download routes.
- `src/jobmitra/core/config.py`, `.env.example`: resume size limit.
- `src/jobmitra/main.py`: register the new router.
- `migrations/env.py`: include the new table in managed metadata comparisons without changing
  the historical Stage 3 table list.
- `migrations/versions/0007_candidate_resumes.py`: new table, indexes and constraints.
- `src/jobmitra/static/candidates/resumes.mjs`: file selection/removal, in-memory staff
  upload, blob download/PDF viewing and history rendering.
- `src/jobmitra/static/candidates/desk.mjs`: optional upload after existing JSON registration.
- `src/jobmitra/static/candidates/desk.css`: wrap long filenames and parsed JSON on mobile.
- `src/jobmitra/templates/candidates/{base,candidate_form,quick_candidate_form,profile}.html`:
  include the new controls without removing existing fields.
- `src/jobmitra/templates/candidates/{resume_input,resume_panel}.html`:
  optional upload input and profile resume section.
- `tests/test_optional_resumes.py`: isolated PostgreSQL/storage regression tests.
- `outputs/optional-resumes/0006-to-0007-reviewed.sql`: offline generated SQL for review only.

## Configuration and access

The original private directory is reused through `JOBMITRA_DOCUMENT_STORAGE_ROOT`.
For Windows, set this locally to `D:/JobmitraData/private-documents`; it must already exist
and be writable by the backend service identity. No directory is created or relocated by
this feature. Files stay outside static/templates; storage keys are random and never returned
in HTTP metadata. Original bytes and hashes are preserved. Existing document size settings
remain unchanged.

- `JOBMITRA_RESUME_MAX_BYTES=10485760`: new resume limit, default 10 MiB.
This prototype intentionally has no authentication or resume-specific credentials/login prompts.
Anyone who can reach the application can use its resume endpoints. Application-wide authentication
will be implemented separately before production deployment. The existing same-origin write guard
is retained; it is not authentication. Candidate/resume association checks, private file storage,
file validation, and path-safe retrieval are unchanged.

The resume router remains separate so a future application-wide authentication dependency can
protect all resume operations without redesigning storage or version services.

## APIs

These routes work without authentication:

- `GET /api/candidates/{candidate_id}/resumes`: history and nullable parsed JSON.
- `POST /api/candidates/{candidate_id}/resumes`: raw PDF/DOCX body, URL-encoded original
  filename in `X-Document-Filename`, and existing `X-Jobmitra-UI: 1`/same-origin write guard.
- `GET /api/candidates/{candidate_id}/resumes/{resume_id}/download`: attachment.
- `GET /api/candidates/{candidate_id}/resumes/{resume_id}/preview`: inline PDF; DOCX attachment.

Responses omit storage paths and keys. Parse diagnostics are exposed only as a generic error;
full internal diagnostics can remain in the database. Uploaded file validation uses the existing
PDF signature/EOF and DOCX archive/XML checks; it is not antivirus scanning.

## Migration and consistency

Revision `0007_candidate_resumes` follows the existing, uncommitted `0006_jd_catalog_links`.
Review and approve that dependency separately before deployment. Neither migration was applied
to Windows. The reviewed 0006-to-0007 SQL creates only `candidate_resumes`, two indexes and
constraints, and advances `alembic_version`. It does not alter candidate/company/JD rows.
Downgrade requires an online check and refuses to drop nonempty resume metadata.

The new table contains the requested UUID identity/candidate foreign key, original filename,
private storage key, MIME type, size, SHA-256, nullable extracted text/JSONB/error, parsing state,
active flag and timestamps. Its candidate foreign key uses `ON DELETE RESTRICT`.
A partial unique index permits at most one active resume per candidate. Uploads lock the candidate
row, save validated immutable bytes, deactivate the previous version, and insert the new version
in one database transaction. Failure rolls back metadata and removes the newly saved file.
Previous originals remain available. Process crashes across filesystem/database commits still
require operational reconciliation and coordinated database/file backups.

No historical document rows or files are backfilled. Existing `candidate_documents` and
`resume_parse_results` stay separate and visible in their existing profile section. New uploads
appear in the new Resume section. No external parsing calls or profile inference run.

## Future parsing

`ResumeService.original(candidate_id, resume_id)` resolves an existing immutable original for
a future parser. Parsing state starts at `not_parsed`; extracted text, JSON and errors
start NULL. Future work includes parser jobs, structured schema validation, safe failure handling,
and per-employee identity if required. Do not mutate original bytes or automatically replace
manually entered candidate fields.

## Verification

Focused tests use `scripts/test_stage3_isolated.py` with a disposable local PostgreSQL cluster,
TCP disabled, and temporary document storage. Browser checks use the same isolated approach
at desktop 1440×900 and mobile 390×844. No Windows database, real candidate records or historical
resume files are used.

Authentication-removal verification: 27 focused isolated tests passed; the migration-execution
test was deselected because schema/migrations are unchanged. Twelve desktop/mobile browser checks
passed, including no-login registration, automatic history, download, replacement, failed-upload
recovery, no Authorization headers and no login dialog. Ruff, JavaScript syntax and Git whitespace
checks passed. No live database access or pending migration execution occurred.
