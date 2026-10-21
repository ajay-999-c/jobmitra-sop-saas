# Stage 2 implementation map — review scope

## Inspected baseline

Entry point: `src/jobmitra/main.py:create_app`; shared SQLAlchemy Base and session
dependency: `core/database.py`. Company models, service, repository and router live
in `modules/companies`, with package-local Jinja templates and static assets.
Existing company IDs are UUIDs. At the initial inspection Alembic had the single revision
`0001_company_management`. Dependencies already provide FastAPI, SQLAlchemy 2,
psycopg 3, Pydantic v2, Alembic and Jinja. No domain catalog, Stage 2 prototype,
staff module, implemented jobs module or authentication existed at that inspection.

The initial Windows baseline attempt could not connect. On 2026-10-20 a successful
read-only preflight verified 131 companies, 108 contacts and revision 0001. Following
the user's explicit approval, revision 0002 was applied with existing data preserved.
See the [deployment record](stage-2-windows-deployment.md).

## Implementation

- `modules/staff/{models,schemas,repository,service,router}.py`: StaffMember,
  dynamic add/rename/deactivate, duplicate-name warning; `/api/staff` and `/staff`.
- `modules/jobs/{models,schemas,repository,service,router}.py`: JobRequirement,
  JobRecruiter; employer-confirmed criteria, version checks, recruiter membership,
  target/status/closure, separate validated ATS JSON; `/api/jobs`, job detail and
  `/recruiters`, `/target`, `/status`, `/ats-json`, `/shortlist-completion` actions.
- `modules/worklog/{models,schemas,repository,service,router}.py`: Activity, Task;
  append-only change history/notes, follow-up tasks and employee/team filters;
  `/api/jobs/{id}/activities`, `/notes`, `/tasks`, `/api/tasks` and task PATCH.
- `modules/stage2.py`: explicit registration of exactly five new business models.
- `core/workflow.py`: shared safe HTTP errors, mutation-origin check, calendar and
  JSON audit-value helpers. Services own one transaction per action; repositories
  never commit. Parent JD locking plus expected version protects all job actions.
- `src/jobmitra/templates/stage2/` and `static/stage2/`: overview `/overview`,
  requirements `/requirements`, quick creation `/requirements/new`, workspace
  `/requirements/{id}`, staff `/staff`, tasks `/tasks`. Local HTMX for list
  fragments, minimal vanilla JavaScript for typed JSON forms, no CDN runtime.
- One additive revision `0002_jd_tracking`, down_revision
  `0001_company_management`, plus an offline SQL artifact for review.
- Focused tests and a disposable local PostgreSQL 18 runner that uses a private
  Unix socket with TCP disabled and explicit settings independent of `.env`.

## Decisions and actual-repository differences

- Company models, original migration and company data stay unchanged. A small
  navigation link can expose the new pages without replacing the company UI.
- Existing `activities` is only a placeholder package. The approved `worklog`
  module owns the new activities/tasks tables; the placeholder is preserved.
- Existing company service commits at action end. New Stage 2 services make
  transaction ownership explicit with `session.begin()`; no Stage 1 rewrite.
- Add the two explicitly approved SHORTLIST timestamp/staff fields. They represent
  self-selected staff confirmation only. Selection/Joining cannot be completed
  in Stage 2; no candidate tables, pipeline status column or fabricated counters.
- Activities require a JD at database level. There is no global staff audit table;
  existing staff references are retained and actor names are snapshotted in JD
  history. Staff deactivation does not remove recruiter assignments or old tasks.
- Office dates use configurable `JOBMITRA_OFFICE_TIMEZONE`, default Asia/Kolkata.
- Domain/subdomain are nullable free text until an approved catalog exists; no
  taxonomy or company-industry inference is introduced.
- Existing Alembic only permits a local target. Keep remote execution blocked by
  default and add a deliberate CLI opt-in for approved runs. Implementation tests
  use only a disposable local cluster; the separately approved Windows deployment
  was completed on 2026-10-20.
- No authentication: Recording as is visibly self-selected/unverified attribution.
  No PostgreSQL login creation, password changes, extensions, seeds or Windows
  service/network configuration are part of Stage 2.
- Follow-up UI direction: use the supplied red Jobmitra theme rather than green.
  Update Stage 2 navigation, controls and surfaces and Company Directory branding
  without changing company search/CRUD behavior or database schema.
