# Stage 2 implementation review

Stage 2 is implemented in code and validated on disposable PostgreSQL 18. Following
the user's explicit approval, **it was migrated to Windows on 2026-10-20**.
See the [deployment record](stage-2-windows-deployment.md) for the verified backup,
preserved company data and live UI checks. No Windows seed rows, roles, extensions,
company updates, imports, service changes or network changes were executed.

The interface now follows the supplied Jobmitra reference: red JM branding, navy
text, white navigation/cards, pale gray background and pale red active states.
The Company Directory has the same palette; its search and CRUD behavior remain
unchanged. All assets are local and no frontend framework was added.

## Inspected baseline and unresolved live verification

The existing app factory is `src/jobmitra/main.py:create_app`. Company Management
has UUID keys, a shared SQLAlchemy Base/session dependency and revision
`0001_company_management`. There was no implemented staff/JD workflow, domain
catalog or UI prototype in the inspected repository. The `activities` package was
a placeholder; the new worklog module owns activities and tasks without removing it.

Configured Windows target: `192.168.1.51:5432`, database `jobmitra_dev`, login
`jobmitra_app`. Credentials are read from the existing settings and never included
in this report. During the initial review, preflight reports recorded
`host_unreachable` (No route to host). The successful 2026-10-20 preflight verified
131 companies / 108 contacts, revision 0001, row hashes, extensions and metadata
before the approved deployment. No PostgreSQL reconfiguration was required.

The user's repeated preflight command also encountered `FileExistsError` because
the helper intentionally refused to overwrite a report. That secondary issue is
fixed: the helper reserves its private output before connecting and chooses a
timestamped sibling on collision. Prior reports are retained, new files are mode
0600, and an unwritable output directory fails before any connection attempt.
Two focused tests verify these behaviors. A saved report is successful only when
its `status` is `captured`; a file's existence alone does not verify connectivity.

## Changed files and purpose

All paths below are relative to the project root. This workspace has no Git
repository, so this is an implementation inventory rather than a Git diff.

| Files | Purpose |
| --- | --- |
| `src/jobmitra/modules/staff/__init__.py`, `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py` | Dynamic staff directory, validation, active-staff checks and HTTP/pages. |
| `src/jobmitra/modules/jobs/models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py` | JD criteria, recruiter memberships, targets/status, ATS JSON, concurrency and directory/workspace. |
| `src/jobmitra/modules/worklog/__init__.py`, `models.py`, `schemas.py`, `repository.py`, `service.py`, `router.py` | Automatic history, notes and employee follow-up tasks. |
| `src/jobmitra/modules/stage2.py` | Explicit registry of exactly five new ORM models. |
| `src/jobmitra/core/workflow.py` | Safe workflow errors, request/session dependency, mutation-origin check, office-date and audit serialization helpers. |
| `src/jobmitra/core/validation.py` | Shared input/read schemas, strict positive/nonnegative integers, UTC output timestamps and skill deduplication. |
| `src/jobmitra/core/pages.py` | Shared Jinja renderer, office-time display, local-asset CSP and no-store headers. |
| `src/jobmitra/core/config.py`, `.env.example` | Configurable office timezone, default `Asia/Kolkata`; existing `.env` unchanged. |
| `src/jobmitra/main.py` | Compose Stage 2 routers/assets alongside existing Company Management; retain the root Company redirect. |
| `src/jobmitra/templates/stage2/base.html`, `overview.html`, `directory.html`, `job_rows.html`, `new.html`, `manual_fields.html`, `workspace.html`, `staff.html`, `tasks.html`, `task_rows.html` | Shared red/navy shell and all Stage 2 pages/fragments/forms. |
| `src/jobmitra/static/stage2/workflow.css`, `workflow.mjs`, `favicon.svg` | Responsive styles, red JM mark, small typed-JSON form controller and staff selection. |
| `src/jobmitra/static/stage2/vendor/htmx.min.js`, `HTMX-LICENSE`, `README.md` | Locally bundled HTMX 2.0.11 and provenance/license. No CDN runtime. |
| `src/jobmitra/modules/companies/templates/companies/directory.html`, `static/directory.css` | Navigation into Stage 2 and requested red/navy visual theme only. |
| `migrations/env.py` | Register Stage 2 metadata; exclude unmanaged tables; preserve remote execution guard unless deliberately opted into for a later approved run. |
| `migrations/versions/0002_jd_tracking_add_jd_tracking.py` | The single additive Stage 2 revision. |
| `scripts/test_stage2_isolated.py` | Disposable PostgreSQL 18 cluster, focused tests and optional separate preview. |
| `scripts/stage2_preflight.py` | Database-enforced read-only baseline capture without row values or credentials in output. |
| `tests/test_stage2.py` | Focused workflow, database constraints, HTTP/UI and migration tests. |
| `tests/test_stage2_preflight.py` | Report collision preservation and fail-before-connect checks. |
| `tests/test_company_schema.py`, `tests/test_company_migration.py` | Keep Stage 1's two-table contract scoped to revision 0001; Stage 2 tests separately verify head. Original column/constraint tests remain. |
| `docs/stage-2-implementation-map.md`, `docs/stage-2-schema.md`, this file, `README.md` | Scope, complete schema, review/commands and setup links. |
| `outputs/stage-2/0002_jd_tracking.sql`, `sql-review.json`, `validation.json`, `windows-preflight*.json` | Reviewable SQL, structural counts, validation and failed read-only baseline attempts. |

Company models, normalization, importer, repository and service were not changed.
The original `0001_company_management.py` was not changed. Spreadsheets were not
edited or imported. No new Python production dependency was added.

## Classes and service contracts

| Class / module | Responsibility |
| --- | --- |
| `StaffMember` | UUID staff identity, display name, active flag and timestamps. |
| `JobRequirement` | Employer-confirmed JD fields, separate ATS enrichment, target, closure and version. |
| `JobRecruiter` | Equal many-to-many memberships, assignment/removal timestamps and composite key. |
| `Activity` | JD event/note, meaningful before/after JSON, actor and timestamp. |
| `Task` | JD follow-up, assigned/creating staff, optional due date and completion metadata. |
| `StaffCreate`, `StaffPatch`, `StaffRead` | Add/rename/deactivate inputs and staff output with duplicate-name warning. |
| `RecordedAction` | Selected actor UUID and expected JD version for a mutation. |
| `OptionalCriteria`, `ManualCriteria` | Partial input fields versus complete validated employer criteria; range checks and deduplicated skills. |
| `JobCreate`, `JobPatch`, `JobRead` | Minimal creation, omitted-versus-cleared PATCH and detailed output including computed target state/recruiters. |
| `RecruiterUpdate` | Complete desired unique set of recruiter IDs. |
| `TargetPatch`, `StatusPatch` | Paired target date/milestone and status/closure validation. |
| `ATSJsonV1`, `ATSUpdate` | Schema-v1 enrichment structure, selected actor/version and staff-reviewed flag. |
| `NoteCreate`, `TaskCreate`, `TaskPatch`, `TaskRead` | Note/task validation and task output with computed overdue and current JD version. |
| `StaffService` | `add_staff`, `rename_staff`, `deactivate_staff`, `list_active_staff`; `patch_staff` routes edits. Names can duplicate with a warning; IDs never merge. |
| `JobRequirementService` | `create_job`, `update_manual_criteria`, `set_recruiters`, `change_target`, `confirm_shortlist`, `change_status`, `close_job`, `save_ats_json`, `list_jobs`, `get_job_detail`. |
| `ActivityService` | Internal `append_change_event` joins its caller's transaction; `add_note` owns a transaction; `get_job_history` returns the timeline. |
| `TaskService` | `create_task`, `patch_task`, `mark_done`, `cancel_task`, `reassign_task`, `list_my_tasks`. Done/Cancelled actions apply to Pending tasks. |

Repositories contain SQL and never commit. Mutation services own one
`session.begin()` transaction per action. A failure in history insertion rolls
back the business change too. The dependency closes sessions and safely maps
expected validation/conflict/database errors without returning driver messages.
The FastAPI lifespan disposes the engine. No AI calls occur inside transactions.

`locked_job` takes a short parent-JD row lock and checks the submitted version;
stale writes return HTTP 409. `record_action` increments that version once and
appends the event for meaningful changes. No-op saves do neither. PATCH uses
`model_fields_set`, validates the merged result and preserves omitted values.
Notes and task actions also use the parent JD version so concurrent edits are
visible rather than silently lost. Company/contact ownership is service-validated
without altering Stage 1 tables. The JD directory uses two SELECTs for many rows,
including recruiters, rather than querying recruiters separately for every JD.

## Pages and HTTP endpoints

| Page / API | Operations |
| --- | --- |
| `/overview` | Actual database counts and target links. |
| `/requirements`, `/requirements/new`, `/requirements/{id}` | Filtered directory, quick creation and workspace. |
| `/staff`, `/tasks` | Staff maintenance and My/Team follow-ups. |
| `/api/staff` | GET list (`active_only` optional), POST add. |
| `/api/staff/{id}` | PATCH rename/deactivate. |
| `/api/jobs` | GET directory; POST create. |
| `/api/jobs/{id}` | GET detail; PATCH employer criteria. |
| `/api/jobs/{id}/recruiters` | PUT desired recruiter set. |
| `/api/jobs/{id}/target`, `/status` | PATCH tracking fields. |
| `/api/jobs/{id}/shortlist-completion` | POST staff-confirmed SHORTLIST only. |
| `/api/jobs/{id}/ats-json` | PUT separate validated enrichment. |
| `/api/jobs/{id}/activities`, `/notes` | GET history; POST optional note. |
| `/api/jobs/{id}/tasks` | GET job tasks; POST follow-up. |
| `/api/tasks`, `/api/tasks/{id}` | GET filtered tasks; PATCH task. |

Mutation requests use JSON and `X-Jobmitra-UI: 1`, with same-origin validation.
This is not authentication. “Recording as” stores only the selected staff UUID
in sessionStorage and explicitly describes self-selected/unverified attribution.
Switching the recorder never silently reassigns tasks. Keep the current server on
the trusted development interface; personal-data deployment needs access control.

## Tables and reviewed migration SQL

The [complete schema](stage-2-schema.md) lists every column, nullability, default,
foreign key, check and index directly from the registered ORM metadata.

| New table | Primary key and relationships |
| --- | --- |
| `staff_members` | UUID; referenced by creators, actors, recruiters and task owners. |
| `job_requirements` | UUID; required company/creator, optional existing contact, closing staff and SHORTLIST confirming staff. |
| `job_recruiters` | Composite `(job_id, staff_id)`; NULL removal timestamp means active. |
| `activities` | UUID; required JD, optional actor; append-only through app endpoints. |
| `tasks` | UUID; required JD/assignee/creator, optional completion actor. |

Revision `0002_jd_tracking` follows `0001_company_management`. The reviewed
[upgrade SQL](../outputs/stage-2/0002_jd_tracking.sql) contains:

- 5 CREATE TABLE statements, 5 primary keys, 13 foreign keys (all RESTRICT).
- 23 CHECK constraints and 8 explicit CREATE INDEX statements.
- One normal revision UPDATE from 0001 to 0002 in `alembic_version`.
- BEGIN/COMMIT; no company ALTER/DROP, business-row INSERT/UPDATE/DELETE,
  extension/vector changes, role changes, seeds or company re-import.

SQL SHA-256: `96077db111212335b79a1b59b3ee1e316a5516df1fb93ec3a335e4ce7e6f4570`.
Fresh offline generation matched the checked-in artifact byte-for-byte.
The isolated round-trip test compares Company rows and column metadata before and
after upgrade, verifies unrelated sentinel data survives, checks the ORM schema
against migrated metadata and downgrades only the five Stage 2 tables.
These tests provide isolated proof. The later Windows baseline and deployment
verification are recorded separately in the deployment record.

Unchanged source SHA-256 values:

- `modules/companies/models.py`: `5cdc68047d0b67d7933bfe4d2d6d10e30ffb4aa681971e913820e7eeaec73896`.
- `migrations/versions/0001_company_management.py`: `bd58878c1f81545e4899be1055240813fc859a3989dd0b741f75adae458dd903`.

## Focused validation

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
.venv/bin/python scripts/test_stage2_isolated.py
.venv/bin/python -m pytest -q tests/test_stage2_preflight.py
node --check src/jobmitra/static/stage2/workflow.mjs
```

- Isolated Stage 2 + Stage 1 schema/migration checks: **61 passed in 2.93s**,
  including 45 Stage 2 tests. One upstream FastAPI/Starlette TestClient/httpx
  deprecation warning; no failed or skipped tests in that run.
- Preflight report regression checks: **2 passed in 0.47s**, no database connection.
- Ruff on all changed/new Python files: passed. Workflow JavaScript syntax: passed.
- Browser workflow: create a minimal JD, persist two recruiters, save reviewed
  enrichment, add Power BI as required, retain JSON and show ATS Stale; verified.
- HTMX skill filtering returned the correct fragment; desktop/mobile layouts checked.
- The red theme is checked separately after the workflow run; see validation output.

After the theme update: the isolated page-rendering test passed in 0.99s;
the two preflight tests plus Company asset/input test passed together (3 in 0.69s),
and all 6 existing client-side Company search tests passed (mean search across 166
synthetic companies: 0.040ms; informational browser-memory search, not DB latency).
Desktop 1440px and mobile 390px rendered the red `rgb(224, 0, 0)` brand/buttons;
page width matched the viewport. Wide JD tables scroll within their own container.
No unrelated full regression suite was run after the visual-only changes.

Visual review artifacts: [desktop](../output/playwright/stage2-red-desktop.png),
[mobile](../output/playwright/stage2-red-mobile.png),
[Company mobile](../output/playwright/company-red-mobile.png). These are local
ignored browser artifacts containing only isolated synthetic preview records.

The runner creates a PostgreSQL 18 cluster under a mode-0700 private temporary
directory, disables TCP, uses a private Unix socket, replaces inherited database
settings and verifies `listen_addresses` plus the actual data directory before
test writes. It stops and deletes the cluster on exit. No Windows tests run.
Use `JOBMITRA_TEST_PG_BIN` if PostgreSQL 18 server binaries are outside Homebrew's
usual paths. Client-only `libpq` tools are insufficient for this isolated runner.

## Three review walkthroughs

**Create JD.** Add staff at `/staff`, select Recording as, then open Requirements
→ Add JD. Choose an existing company and enter a title; save with the optional
fields blank. `workflow.mjs` → POST `/api/jobs` → `JobCreate` →
`JobRequirementService.create_job`. Inside one transaction: require active actor,
validate existing company/contact, insert UUID JD, append `JD_CREATED`, return the
detail. Unknown employer facts stay NULL, salary units Unknown, skills empty,
status Draft and version 1. Creation does not require ATS or recruiter assignment.

**Assign a second recruiter.** Open Manage Recruiters, select both employees and
save. JavaScript → PUT `/api/jobs/{id}/recruiters` → `RecruiterUpdate` →
`set_recruiters`. One transaction locks the JD, checks its current version,
validates newly assigned active staff, inserts/reactivates memberships, preserves
the first recruiter and appends one `RECRUITERS_CHANGED` before/after event with
one version increment. There is no primary/supporting designation or owner.
Removing someone stamps `removed_at`; re-adding reuses that same composite key.

**Edit required skills.** With existing ATS JSON, open Edit JD and add `Power BI`
to required skills. JavaScript sends only changed manual fields with actor/version
→ PATCH `/api/jobs/{id}` → `JobPatch` → `update_manual_criteria`. One transaction
locks/checks the JD, validates merged criteria, deduplicates case-insensitively,
updates required skills, marks existing enrichment Stale, preserves its JSON and
appends one `JD_CRITERIA_CHANGED` event. No reason is required. No AI suggestion
is copied into manual criteria. Reopen History to inspect before/after and actor.

The isolated browser exercise saved `Excel, Power BI, power bi` as exactly
`["Excel", "Power BI"]`, kept both recruiters and the existing ATS summary, and
recorded four events across creation, assignment, enrichment and criteria editing.

## Original review commands and approval boundary

The approval boundary below was satisfied on 2026-10-20 when the user requested
creating the tables. Deployment is complete; these commands are retained as
reference, not instructions to repeat the migration.

Read-only Windows connectivity/baseline commands (enter the password only at psql's
prompt; the Python helper reads the existing environment):

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
psql -h 192.168.1.51 -p 5432 -U jobmitra_app -d jobmitra_dev -W -c 'SELECT 1'
.venv/bin/python scripts/stage2_preflight.py --output outputs/stage-2/windows-preflight-terminal.json
```

The second command now preserves any existing report under its original name and
saves a timestamped sibling for the new run. Its database transaction is forced
read-only. Confirm `status: captured`, actual company counts/hashes, expected
revision 0001 and extension metadata before considering the migration.

Offline review and a separate disposable preview:

```sh
.venv/bin/alembic upgrade 0001_company_management:0002_jd_tracking --sql
.venv/bin/python scripts/test_stage2_isolated.py --serve
# Preview: http://127.0.0.1:8765/requirements
# Stop with Ctrl-C; its private database is disposable.
```

The approved deployment used the reviewed revision after verifying a fresh backup,
the current baseline, exact target and schema-owner privileges. The equivalent
CLI workflow is:

```sh
umask 077
mkdir -p backups
pg_dump -h 192.168.1.51 -p 5432 -U jobmitra_app -d jobmitra_dev -W \
  --format=custom --no-owner --no-acl \
  --file="backups/jobmitra_dev-before-stage2-$(date +%Y%m%dT%H%M%S).dump"
# Only after verifying that backup and approving this specific migration:
.venv/bin/alembic -x allow_remote=true upgrade 0002_jd_tracking
```

Use the existing authorized schema owner if the runtime login lacks CREATE or
REFERENCES privileges; this stage creates no roles or grants. No automatic app
startup migration exists. After an approved apply, capture another read-only
report and verify revision 0002, unchanged Company counts/row hashes and pgvector
metadata. New JDs/staff/tasks must be entered deliberately; no production seeds.

SELECTION/JOINING remain tracking-only. Domains remain optional free text because
there is no approved catalog. Global staff maintenance has no dedicated audit table.
SHORTLIST completion is explicitly staff-confirmed, not candidate-count evidence.

**Approval received and deployment completed on 2026-10-20.** This approval covered
the five Stage 2 tables; future schema changes still require separate approval.
