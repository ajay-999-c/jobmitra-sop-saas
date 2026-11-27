# JD workspace implementation

## Preflight — 27 November 2026

Both psql and the application's psycopg/SQLAlchemy adapter connected to the configured
office server, PostgreSQL 18.6 on Windows, `192.168.1.51:5432/jobmitra_dev`.
The existing V12 schema is `jobmitra_v12_dev_20261123_integration`; its manifest
passed validation. Read-only counts:244 candidates,146 companies,14 JDs,
53 memberships,852 recruitment events. Counts can change while office staff work.

Canonical employees already exist in `public.staff_members`:5 UUIDs,1 active.
The legacy `public.job_recruiters` table has4 assignments to legacy UUID jobs.
V12's bigint jobs have only `owner_name` text. Names cannot establish identities;
legacy assignments cannot be attached to unrelated bigint jobs by name.

## Identity and migration design

Reuse `StaffMember` and its existing canonical UUIDs. No second production employee
master, login, payroll or authenticated identity is introduced. Alembic0008 adds
nullable email/mobile/designation to that existing master and a request-keyed
staff-change audit. New identities use the existing UUID strategy. Inactive staff
remain addressable; a new assignment must reference an active identity.

The explicit V12 workspace extension adds a nullable `assigned_recruiter_id` FK
to that master, a scoped read-only directory view, assignment-change audit triggers
and a version manifest. Existing JDs remain NULL/Unassigned. Assignment changes are
timestamped by the database and recorded with canonical old/new IDs and name
snapshots. They do not assert which individual performed an action:Office LAN
is a network authorization policy, not a verified staff login.

Ordinary JD saves in an extended schema require a full-row revision token. A stale
token produces409; the user must review the latest record. Workflow versions and
membership expected-state guards remain unchanged.

Neither migration runs at startup. No migration or write is authorized against
the active office schema during this work. Tests provision a fresh namespace and
a disposable canonical-staff model in a separate namespace; the view/FK points
only there. This test copy is never the production employee directory.

## Deployment and recovery boundary

Before a separately approved deployment:take verified PostgreSQL and document
backups; rehearse Alembic0008 and the workspace extension on a restored database;
apply the canonical-staff migration, then the explicit V12 extension in controlled
transactions; validate manifest/FKs; verify all original row identities/counts;
only then restart the application. Do not run Alembic against office public as a
side effect of preview startup. The existing staff endpoints remain compatible.

Failure before migration commit rolls back the new columns/views/triggers/marker.
After employee/assignment data exists, preserve it and use forward recovery or a
verified restored staging copy; destructive downgrade is deliberately refused.
No push, office cutover, NSSM or firewall changes are part of this implementation.

## Checkpoints

Implementation and focused verification results will be recorded here as each
logical feature completes. The original approved HTML and newly supplied interview
round preview are immutable design references. The latter supplies presentation,
never demo masters, localStorage persistence or prototype business rules.

### Employee/assignment verification

Seven focused tests passed against disposable office PostgreSQL namespaces and one
temporary SQLite file. Coverage includes canonical UUID reuse via the existing staff
API, employee validation/search/edit/deactivation, request replay, inactive historical
assignments, new-assignment rejection, nullable legacy jobs, recruiter dashboard
search/filter, actual Alembic0008 rollback and preservation, assignment history,
ordinary-edit conflict rejection, protected-mode403 and cross-origin403.
Browser verification on the synthetic preview confirmed create/edit/search,
assignment after reload, deactivation and retained assignment with API read-back.
No unlock prompt appeared. Gmail was disabled; no mail was sent.

The optional SQLite extension uses the same StaffMember UUID format in an explicitly
upgraded isolated copy; no office staff or SQLite production store was migrated.
Canonical public remains the PostgreSQL employee master. An isolated fixture's staff
namespace must never be mistaken for or merged into that master.

Synthetic preview preparation is explicit in `scripts/preview_jd_workspace.py`.
Forking retains prior namespaces and archives the private identifier state; it
never deletes existing documents or recruitment history. Preview namespaces contain
synthetic examples only. Screenshots stay under ignored `output/playwright/jd-workspace/`.

### Local checkpoint1

`5f7d2b0` — `feat: add employee management and JD recruiter assignment`.
The checkpoint contains25 reviewed files. No private ENV, data, documents,
screenshots or runtime reports were staged. No push occurred.

### Approved workspace layout mapping

The immutable `Jobmitra_JD_Tracking_Interview_Rounds_Preview.html` reference has
SHA-256`6587ab895c7024cc03871338cfbe172c084a0528c88c7a7ad5b2c2f77793fed9`.
`scripts/v12-workspace-layout.mjs` extracts its CSS and builds a permanent sidebar
using the existing component IDs/event handlers. The reference's demo script and
localStorage are never imported. `jd-dashboard.mjs` renders the compact table over
the same server browse API/metric calculations; filters survive JD navigation.
The JD form retains all fields and salary-period conversion through the original
service adapters; optional sections are collapsible and Salary Budget replaces
Compensation. No salary/vacancy nulls are converted to zero. New JDs default Active;
existing explicit statuses remain unchanged. Selected JD header shows company,
location, responsible recruiter, status, dates, deadline and joined/vacancy counts.
Root/overview and the bare V12 route land on JD Dashboard without selecting a JD.
Global order is JD Tracking → Candidate Desk → Email → Companies → Employees.
JD navigation stays disabled until a real JD is chosen.

Browser verification confirmed default route/sidebar, PostgreSQL creation201,
recruiter persistence, true salary0, unknown max/vacancies remaining NULL, and
preserved dashboard query after opening/returning from a JD. The original approved
unified HTML and embedded Email Studio bytes remain unchanged. The redesign does
not replace canonical services with prototype state.

### Performance baseline

Before performance optimization, the244-candidate/14-JD/53-membership synthetic
remote PostgreSQL fixture produced a3329.5ms full-state fetch of900056 decoded bytes.
Navigation through the initial pipeline to dashboard took4051ms in the recorded
Mac browser sample. Four API requests had completed at readiness; three further
inactive-module search requests were subsequently observed. The raw trace is
private under runtime, with paths/timings only. No long task was observed in that
sample; the older tiny-local-fixture audit's207ms task is a different condition.
The final before/after benchmark will use comparable fixture shape and report its
limits rather than present this as measured Windows application performance.

Layout verification:16 focused Python checks passed (employee/assignment,
new Active default with unchanged explicit Drafts,7 legacy URL aliases and immutable
approved source/CSS);10 existing JS checks passed (selectors, request invalidation,
allocation, history and card styling). Controlled delayed old dashboard response was
ignored before the next250ms debounce fired. Browser checked a single New JD
entry point and retained query on return. Screenshots02/03 show dashboard/form.
