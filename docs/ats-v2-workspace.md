# Parallel ATS JD Workspace and Candidate Search

The new workflow runs beside the existing `/requirements` JD Tracking and
`/candidate-desk` pages. It is disabled by default. Existing PostgreSQL pages and
schemas remain unchanged. Master-data imports are explicit, one-way operations;
ordinary ATS requests use SQLite only. Automatic emails, interview booking,
employee attribution, and login systems are not introduced.

## Pages and behavior

- `/jd-workspace-v2`: JD Dashboard, Create/Edit JD, Hiring Workflow, Candidate
  Pipeline, and JD Activity History. The dashboard links directly to each JD's
  pipeline and calculates deadlines using Asia/Kolkata calendar dates. Only
  explicit JOINED outcomes count toward vacancies. DRAFT/ON_HOLD deadlines are
  neutral; CLOSED and FILLED take precedence.
- `/candidate-search-v2`: isolated ATS candidate search, registration, profile
  edits, resume versions, activities, candidate history, and pool association.
- `/ats-v2/candidates/{candidate_id}`: direct link to the same search/profile page.
- The existing navigation gains **JD Workspace (New)** and **Candidate Desk (New)**
  when the feature flag is enabled.
  The old JD Tracking and Candidate Desk links and behavior are preserved.

The UI follows the supplied JD Workflow V5 and Candidate Search V1 layouts with
scoped CSS and ES modules. Every count and business record comes from the server.
There are no browser-persisted business records, demo candidates, dummy companies,
reset-demo actions, fabricated match percentages, or hardcoded server addresses.

Search supports quoted keyword phrases, Match Any/All, professional evidence,
current/preferred location, experience, expected salary, notice, availability,
unknown-value inclusion, relevance/recent/experience sorting, and server-side
pagination. Relevance is a count of matching evidence terms, not an AI score.
Salary filters use expected compensation only. Monthly and annual amounts are
normalized for the selected basis. The **Any / Indicative** mode compares the
recorded amounts for known bases for screening, without implying that the bases
are equivalent. Missing or non-comparable values follow the explicit
include-unknown-salary option. Linking a candidate creates one unique association,
starts at POOL, and never creates another candidate master.

Workflow saves use optimistic version checks. Four Jobmitra stages are fixed.
Company rounds have stable UUIDs and can be renamed, reordered, retired, or
restored. Saved rounds are never deleted. A round with currently assigned
candidates cannot be retired. Changing to UNKNOWN/DIRECT requires retiring unused
rounds first. A save increments one workflow version and never moves candidates.
Progression advances one stage at a time; UNKNOWN blocks company progression
until the company process is confirmed. SELECTED requires a separate JOINED
confirmation. JOINED and NOT_SELECTED are terminal retained outcomes. V3.1's
SELECTED-to-JOINED-only rule is retained. Feedback can be recorded at any retained
stage, including after an outcome.

## Connections and schema

The ATS uses its own SQLite `ats_v2_engine` for company options, candidate data,
JDs, workflows, activities and history. The company gateway never imports the
legacy PostgreSQL repository or opens a PostgreSQL session. Company creation and
reassignment validate an active local company and store its stable UUID identifier.
Inactive companies remain resolvable on historic JDs, but are excluded from new JD
options. Missing IDs are rejected; no dummy company or runtime fallback is used.

The existing `/companies` page still edits PostgreSQL through its original models,
services and connection. Use its existing **+ Add company** button for a missing
company. Newly created or edited legacy companies become available to the ATS
after an operator runs the explicit incremental, one-way company import:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_postgres_masters_to_sqlite.py --execute --companies-only
```

Then return to the new JD form and choose **Refresh company list**. Refresh reads
SQLite; it does not contact PostgreSQL or perform an import. No second company
form, ATS company-creation API, dual writes, or automatic synchronization is added.
Existing imported company options, JD creation, name resolution and recruitment
operations keep working when PostgreSQL is unavailable. Legacy PostgreSQL pages
still require their original database connection.

SQLite uses separate `ats_v2_engine` and `get_ats_session` helpers with explicit
`BEGIN IMMEDIATE` write transactions. PostgreSQL reads occur only in legacy
modules or the explicitly invoked import tool. No cross-database SQL join occurs.

The version-controlled `src/jobmitra/modules/ats_v2/schema.sql` now contains eight
business tables:

1. `companies` — imported local Company Master, UUID identifiers and import provenance
2. `candidates`
3. `candidate_resumes`
4. `job_descriptions`
5. `jd_interview_rounds`
6. `jd_candidates`
7. `recruitment_events`
8. `candidate_activities`

`companies` and `candidates` retain nullable `legacy_postgres_id` mappings.
Imported resume versions retain their source table and source record ID. These
stable mappings live on the existing records, rather than in an additional
mapping table. Company JSON fields preserve source contacts and other imported
master details. Import provenance is separate from recruitment audit payloads.
The local `job_descriptions.company_id` uses a UUID string referencing the imported
company. Backend and database checks require eligible companies for new JDs and
company reassignment.

The seven recruitment tables and V3.1 audit behavior remain: automatic
registration/field-change/workflow/round/stage/resume/activity events, changed-field
before/after JSON including NULL changes, append-only history, historical round
labels, and rejection-stage snapshots. Only optional FEEDBACK is inserted by the
service; movement itself is logged once by its trigger in the same transaction.
No raw resume text or parsed bodies are copied into audit events. UTC timestamps
are stored; the browser displays IST.

Normalized phone/email indexes support identity checks. Registration and profile
changes serialize duplicate checks with SQLite writes. Contact matches require
review of the existing profile and return HTTP 409; names alone never merge
candidates. Database constraints enforce foreign keys and unique JD associations.
Search and history have supporting indexes. FTS/shadow tables are not introduced.

Every SQLite connection enables foreign keys, recursive triggers, and a five-second
busy timeout. Explicit initialization enables WAL. Transactions roll back on
validation or storage failure. Schema/version/application markers are checked
against the owned schema. Existing incompatible, reference V3.1, or modified
databases are refused; the application never runs migrations or creates a database
automatically. This release has schema version 2. The frozen `schema_v1.sql` and
reviewed `upgrade_v1_to_v2.sql` support an explicit, transactional upgrade of an
exact owned V1 store; runtime validation requires V2. Future schema changes require
a separately reviewed SQLite migration. PostgreSQL Alembic revisions are untouched.

## Configuration and initialization

Keep the existing PostgreSQL and document-storage configuration. Add the following
to the existing `.env`, using real **absolute paths** outside public/static folders:

```ini
JOBMITRA_ATS_V2_ENABLED=true
JOBMITRA_ATS_V2_DATABASE=D:/JobmitraData/private/ats-v2.sqlite3
JOBMITRA_ATS_V2_RESUME_STORAGE_ROOT=D:/JobmitraData/private/ats-v2-resumes
JOBMITRA_RESUME_MAX_BYTES=10485760
```

The first three variables are the new configuration. `JOBMITRA_RESUME_MAX_BYTES`
is the existing shared upload-size setting. Keep it unchanged unless intentionally
changing that limit for all resume modules. `.env.example` keeps the new feature
disabled and contains placeholder paths only. This implementation does not edit
the local `.env` or enable the live feature.

Initialize a **new, separate** SQLite path explicitly. Do not point this at either
the Resume Processing database or the supplied eight-table reference database.
Initialization is idempotent for this exact owned schema; it never overwrites
existing records or converts another schema. The explicit master import handles
reviewed V1-to-V2 upgrades; ordinary application startup does not run that upgrade.

Windows PowerShell, from the existing checkout:

```powershell
Set-Location D:\Jobmitra\sop-pipeline
# Use the existing environment. Install project dependencies if needed.
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m jobmitra.modules.ats_v2.database --database "D:\JobmitraData\private\ats-v2.sqlite3"
# Add the configuration above to the existing .env, then restart the app.
.\.venv\Scripts\python.exe -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Then open `/jd-workspace-v2` or use its new navigation item. If disabled, its pages
and API return 404. If enabled but uninitialized/unavailable, its API returns a clear
503 while the legacy application keeps running. Disabling the flag hides the new
links and does not remove SQLite data or change old routes.

The same initializer on Mac/Linux is:

```bash
.venv/bin/python -m jobmitra.modules.ats_v2.database --database /absolute/private/path/ats-v2.sqlite3
```

Back up the SQLite store using SQLite's online backup API or with the application
stopped; do not copy only the main file while active WAL writes are possible.
Back up its private resume tree along with it. Existing `.gitignore` patterns cover
SQLite files and WAL/SHM/journals, `.env`, private/runtime/upload/resume directories,
PostgreSQL dumps/backups, caches, virtual environments, logs, and temporary files.
No source schemas, migrations, tests, or templates were newly ignored.

## Resume workflow and current limits

Original PDF/DOCX uploads are size/type checked and stored under private generated
relative paths. Windows drive paths, traversal, unsafe filenames, symlink escapes,
malformed/expanded/macro DOCX packages, and mismatched content types are rejected.
Original, parsed professional JSON, and standardized versions are separate
immutable records. Imported historical metadata remains visible even when its
source file is unavailable, with an explicit file status and no download action.
Historical parsed JSON is preserved as review-required evidence, separate from
current approved professional parses; it cannot automatically generate a new
standardized resume. Source bytes are hashed. New originals invalidate current
parsed/standardized selections while retaining every earlier version and download.
Identity changes require renewed professional-data review before generation.

Use **Attach reviewed parse** to attach professional JSON from the existing parsing
workflow against the current original resume, with explicit factual confirmation.
It accepts professional summary/title/employer, skills, qualification, work
experience, education, projects, certifications, and languages. Identity comes from
the candidate master, preserving the candidate name. Reviewed evidence participates
in search without silently overwriting manually entered candidate profile facts.

**Create standard resume** generates an escaped, versioned, printable HTML document
using those reviewed facts and the registered name. Existing standardized PDF/DOCX
files can also be uploaded separately. Automatic LLM parsing and automatic PDF/DOCX
rendering are **not connected in this new module**. The existing separate Resume
Processing flow is unchanged. No model calls or extra candidate database copies
occur as a side effect of registration, upload, or pool association.

## API

All endpoints below use `/api/ats-v2`. Mutation requests require the existing
`X-Jobmitra-UI: 1` same-origin convention. No new employee/login fields are accepted.
Validation errors omit submitted personal values and raw storage/driver errors.
Duplicate associations return 409; missing entities 404; invalid transitions/fields
422; unavailable company/storage services 503. Responses use `Cache-Control: no-store`.

| Method | Path | Function |
| --- | --- | --- |
| GET | `/health` | SQLite health |
| GET | `/companies` | Imported active SQLite company options, read only |
| GET | `/companies/{id}` | Local company details and contacts, read only |
| GET/POST | `/jobs` | Paginated JDs / create JD |
| GET/PATCH | `/jobs/{job_id}` | Read / edit JD |
| GET | `/dashboard` | Real deadline summary |
| GET/PUT | `/jobs/{job_id}/workflow` | Workflow, impact counts / save version |
| GET | `/jobs/{job_id}/pipeline` | Stage counts and candidate pipeline |
| POST | `/jobs/{job_id}/candidates` | Existing candidate association |
| POST | `/jobs/{job_id}/candidates/{link_id}/move` | Manual next stage or rejection |
| POST | `/jobs/{job_id}/candidates/{link_id}/feedback` | Standalone feedback |
| GET/POST | `/candidates` | Filtered paginated search / registration |
| GET/PATCH | `/candidates/{candidate_id}` | Profile and JD participation / edit |
| GET/POST | `/candidates/{candidate_id}/resumes` | Version history / raw PDF/DOCX upload |
| GET | `/candidates/{candidate_id}/resumes/{resume_id}/download` | Scoped immutable download |
| GET | `/resumes/{resume_id}/download` | Download alias |
| POST | `/candidates/{candidate_id}/parsed-resume` | Reviewed professional JSON version |
| POST | `/candidates/{candidate_id}/standardize` | Reviewed printable HTML version |
| GET/POST | `/candidates/{candidate_id}/activities` | Read / create activities |
| PATCH | `/activities/{activity_id}` | Edit/reschedule/complete/cancel activity |
| GET | `/history` | Candidate, JD, or candidate-in-JD history with pagination |

History selectors are `candidate_id`, `job_id`, and `jd_candidate_id`; combining
them narrows to their intersection. Search parameters are `keywords`, `match`,
`location`, `experience_min`, `experience_max`, `budget`, `salary_min`, `salary_max`, `salary_period`,
`salary_basis`, `max_notice_days`, `availability`, `include_unknown_experience`,
`include_unknown_salary`, `include_unknown_notice`, `sort`, `page`, and `page_size`.
The new salary bounds are inclusive; `budget` remains an additional upper bound.
The UI sends `INDICATIVE` for Any / Indicative. The API's historical default
`UNKNOWN` behavior is unchanged.
Raw uploads use URI-encoded `X-Resume-Filename`, optional `X-Resume-Kind` (ORIGINAL
or JOBMITRA_STANDARD), and `Content-Type: application/octet-stream`.

### Candidate Desk destinations

| Destination | Route | Data source |
|---|---|---|
| Candidate Search and registration | `/candidate-search-v2` | ATS SQLite |
| Candidate Profile, activities, Resumes | `/ats-v2/candidates/{candidate_id}` | ATS SQLite and private ATS resume files |
| Parsed Resumes | `/candidate-search-v2?section=parsed-resumes` | ATS SQLite and private ATS resume files |
| JD Pools | `/jd-workspace-v2?view=pipeline` | ATS SQLite |
| Today | `/candidate-desk` | Legacy PostgreSQL |
| Candidates | `/candidates` | Legacy PostgreSQL |
| Office Visits | `/office-visits` | Legacy PostgreSQL |
| Job Search Requests | `/job-search-requests` | Legacy PostgreSQL |
| Foundit Paste | `/candidates/foundit-import` | Legacy PostgreSQL |
| Domain Catalog | `/domains` | Legacy PostgreSQL |
| Resume Processing | `/resume-processing` | Separate Resume Processing SQLite store and private files |

Legacy screens do not read or write the ATS SQLite candidate master. In Parsed
Resumes, select a candidate to open their version history. Attach reviewed
professional JSON by pasting it or loading a local JSON file; preview it, confirm
the facts, and save. The existing API validates the data, requires a current
original resume, and updates searchable professional evidence.

## Tests

Portable Windows tests use only temporary SQLite databases, synthetic files, and
imported local company fixtures. Tests explicitly forbid runtime PostgreSQL
access. They do not connect to the configured live PostgreSQL or processor databases:

```powershell
Set-Location D:\Jobmitra\sop-pipeline
.\.venv\Scripts\python.exe -m pytest -q tests/test_ats_v2_database.py tests/test_ats_v2_candidates.py tests/test_ats_v2_jobs.py tests/test_ats_v2_companies.py tests/test_ats_v2_api.py
node --test tests/*.mjs
node --check src/jobmitra/static/ats_v2/workspace.mjs
node --check src/jobmitra/static/ats_v2/search.mjs
.\.venv\Scripts\python.exe -m ruff check src/jobmitra/modules/ats_v2 tests/test_ats_v2_database.py tests/test_ats_v2_candidates.py tests/test_ats_v2_jobs.py tests/test_ats_v2_companies.py tests/test_ats_v2_api.py
```

Legacy regression tests requiring PostgreSQL must use a disposable database.
The existing Mac isolation runners create private PostgreSQL 18 clusters with TCP
disabled. They are Unix-specific; do not run them on Windows or point destructive
test fixtures at a real database. The verified Mac commands are:

```bash
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests --ignore=tests/test_candidate_quick_entry.py --ignore=tests/test_candidate_search.py --ignore=tests/test_optional_resumes.py --ignore=tests/test_foundit_quick_entry.py
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests/test_candidate_search.py tests/test_foundit_quick_entry.py
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests/test_candidate_quick_entry.py tests/test_optional_resumes.py
node --test tests/*.mjs
```

The groups isolate existing fixtures that drop tables or assume empty databases.

Executed on Mac after the local-company migration adaptation:

- Main isolated group: **362 passed, 16 skipped**.
- Existing candidate search/Foundit group: **14 passed**.
- Existing registration/optional-resume group: **28 passed**.
- Total: **404 Python tests passed**. This includes **12 local company
  gateway/HTTP tests**, **31 mapping tests**, **15 import rehearsals**, and
  **7 explicit upgrade tests**, alongside candidate/workflow/legacy regressions.
- JavaScript regressions: **20 passed**, including four imported-resume rendering
  cases. All three ES modules passed Node syntax checks.
- The actual imported database was safely cloned: **42 workflow checks passed**
  using its company/candidate data, with PostgreSQL connections forbidden and all
  writes confined to the disposable clone. The clone and copied files were removed.
- Browser checks used actual populated SQLite company rows with PostgreSQL
  connections forbidden: loading, refresh, JD creation and name resolution passed
  without console errors. Screenshot: `output/playwright/ats-v2-local-companies.png`.
  The synthetic browser/server and temporary store were closed and cleaned up.
- Ruff, Git whitespace, backup integrity, source-ID reconciliation, actual
  idempotent rerun, SQLite integrity and foreign-key checks passed.
- One existing Starlette/httpx dependency deprecation warning was reported. No
  final test failures remain. An initial backup-handle test failure was corrected
  by explicitly closing SQLite backup handles and making backups self-contained;
  the final combined run passed.

Windows commands are provided for reproduction and were not executed on a
Windows machine. Regression tests use synthetic data and temporary databases.
The separate migration/discovery commands read the configured PostgreSQL source
in read-only transactions, and imported-data workflow checks use a disposable
clone. No live candidate journey or source row was changed by a write test.

## Source layout

New backend files live in `src/jobmitra/modules/ats_v2/` (`database.py`, `schema.sql`,
`schema_v1.sql`, `upgrade_v1_to_v2.sql`,
`common.py`, `companies.py`, `schemas.py`, `jobs.py`, `candidate_schemas.py`,
`candidates.py`, `resumes.py`, `router.py`, and package initializer). New templates
are `src/jobmitra/templates/ats_v2/base.html`, `workspace.html`, and `search.html`.
New frontend assets are `src/jobmitra/static/ats_v2/workspace.css`, `shared.mjs`,
`workspace.mjs`, and `search.mjs`. New tests are `tests/test_ats_v2_database.py`,
`test_ats_v2_candidates.py`, `test_ats_v2_jobs.py`, `test_ats_v2_companies.py`, and
`test_ats_v2_api.py`, and `tests/ats-v2-imported-resumes.test.mjs`. This guide is
`docs/ats-v2-workspace.md`.

Modified existing files are `.env.example`, `README.md`,
`src/jobmitra/core/config.py`, `src/jobmitra/main.py`,
`src/jobmitra/templates/stage2/base.html`, and
`src/jobmitra/templates/candidates/base.html`. Shared modifications are limited to
settings, application wiring, feature-gated navigation, and documentation.
Supplied root HTML/SQL references and audit bundle remain unchanged.
