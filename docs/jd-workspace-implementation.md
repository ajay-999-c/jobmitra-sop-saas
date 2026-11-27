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

### Interview and pipeline verification

The approved three-section editor retains the canonical versioned workflow review,
retirement/restore and occupied-round rules. The ordinary impact/safety panels are
removed; Review still computes the same candidate impact. Saved round identifiers
remain unchanged on removal/restoration. Stage titles are validated at3–80characters.
Primary pipeline actions remain Email, Next Stage, Move to Stage and Not Selected;
Profile, Feedback, Schedule Interview and Placement use a compact accessible menu.
Selected candidates retain explicit joining/closure actions and Submission retains
its checkboxes/composer. No email template bytes were changed.

Nine focused remote PostgreSQL/adapter tests and23 JavaScript checks passed.
Browser verification confirmed: Pool completion and Contact opening on attachment;
existing attachment replay without reset; normal/direct progression, source-stage
feedback, explicit screening feedback and an interview activity with
`invitation_sent=false`. An occupied round's Remove control is disabled and the
server independently rejects retirement. Contact Email opens the existing Studio
with canonical candidate/JD context, verified recipient and screening template;
Gmail remains disabled. Screenshots04/05 record editor and pipeline actions.
Generator consistency, immutable reference checks, Ruff and whitespace passed.

### Attachment correction model (reviewed before implementation)

The existing append-only recruitment event ledger supplies the persistence model:
`ATTACHMENT_REMOVED` / `ATTACHMENT_RESTORED` reference the canonical membership.
No new table, core-stage value or deletion is needed. The latest correction controls
active participation; original membership/events remain available for history.
Only exactly one original Pool attachment and its automatic Pool→Contact movement
are eligible. Any other recruitment evidence, feedback, appointment, email attempt,
selection/joining or unknown imported history blocks correction. Each explicit
confirmation uses a request UUID and a revision covering membership, history and
JD status, inside the existing serialized transaction. Restore reuses the same
membership and requires active JD/candidate plus normal allocation eligibility.
Counts/pipeline exclude removed participation, but the profile and historical JD
association remain. Regression tests cover replay, conflicts, meaningful activity,
master/resume/other-JD preservation, restoration and immutable ledger behavior.

Closure/correction integration passed12 focused backend tests and the existing
sourcing JS checks. Browser correction of synthetic membership54 removed its active
counts1→0; Restore reused54 and returned counts0→1. No candidate master was deleted.
The explicit Close JD dialog showed its one pending candidate and retained JD
Activity after closure. Closure uses the existing CLOSED status plus an immutable
reason/audit event and guarded revision; it never auto-closes overdue/filled JDs.
Removed links cannot receive recruitment actions, email context or appointments
until explicitly restored. Candidate profile JD history retains corrected links.
No schema migration is required for this correction/closure ledger.

### Targeted refresh and synchronization

`GET /api/v12/approved/jobs/{id}/state` returns only that JD's linked people,
company, recruitment events, activities and placements; it excludes resume/profile
bootstrap data. Conditional ETags return304 for unchanged state. JD mutations now
refresh this scope, without broadcasting inactive Candidate Desk searches.
`JOBMITRA_JD_POLL_SECONDS` defaults15, accepts5–120, and is documented in both
tracked ENV examples. No private ENV file was edited.

The visible-workspace poller serializes reads, pauses hidden/inactive workspaces,
resumes on focus/navigation and ignores late pre-mutation results. Unsaved JD and
workflow forms/dialogs retain their content with a Reload and review notice.
Ordinary JD updates retain the existing guarded revision and409 conflict response.
Selected stage, filters, rail position and open Email Studio drafts are retained.
Five isolated PostgreSQL route/service tests passed, including ETag304 and configured
interval; three synchronization JS checks cover overlap, hidden state, recovery,
deduplication and stale-response rejection. Existing23 JS checks also passed.
Two real browser sessions confirmed: remote location save200; first session draft
unchanged; stale save409 JD_CONFLICT; explicit review loaded the remote value.
Remote candidate feedback appeared automatically while the selected Contact stage
and unsent Email Studio note remained unchanged. Gmail was disabled throughout.

### Measured optimization and final verification

The existing integrated components are now generated separately as approved-jd,
approved-candidate, approved-companies and approved-email modules. Their canonical
markup/handlers remain the same. Startup reads only access policy plus the first
JD Dashboard page/summary/filter options. Other components mount on demand;
Candidate Desk/Companies still use a batched compatibility snapshot when first
opened. That remaining snapshot is deliberately not described as eliminated.
New/Edit/Switch JD loads minimal contact/employee/JD selector metadata on demand.
Public content-versioned modules/CSS use immutable caching; bare helper imports
revalidate. No private API, document, database or authenticated HTML cache policy
was relaxed. No framework, infrastructure, dependency or index was introduced.

Backend projections reuse the canonical per-membership transformation. All jobs,
rounds and memberships are read in three batches inside the same repeatable-read
snapshot. Candidate results batch participation and preserve the original
selection/joining eligibility rules, including historical locks. Scoped reads and
legacy full-state responses retain the same fields, salary precision and IDs.

Comparable fixture:244 synthetic candidates,2 companies,15 JDs,54 memberships,
465 events. Both service runs used this unchanged remote PostgreSQL dataset;
3 samples per service. SQL counts exclude one initial cached-extension probe.

| Measurement | Before | After |
| --- | ---: | ---: |
| Full state, median | 3076.98ms /134 SQL | 1222.59ms /16 SQL |
| Selected JD, median | 255.16ms /18 SQL | 195.61ms /12 SQL |
| Candidate search,10 results, median | 314.30ms /32 SQL | 91.76ms /5 SQL |
| Dashboard, median | 95.69ms /6 SQL | 120.36ms /6 SQL |
| Full-state JSON bytes | 1,003,097 | 1,003,097 |
| Selected-JD JSON bytes | 26,401 | 26,401 |
| Search JSON bytes | 10,464 | 10,464 |
| Dashboard JSON bytes | 8,842 | 8,874 |

Mac browser, cache disabled, one recorded run per condition:

| Browser measurement | Before | After |
| --- | ---: | ---: |
| Initial dashboard usable | 4424.4ms | 260.1ms |
| API requests at readiness | 4 | 2 |
| Initial resource entries | 28 | 21 |
| Initial full-state HTTP body | 928,391 bytes | Not requested |
| Bootstrap module bytes | 486,733 | 4,448 |
| Long tasks during initial load | One212ms | None observed |
| Open JD through populated Pool | 1580.9ms | 823.0ms |
| Contact stage switch | 37.4ms | 29.2ms |
| Candidate partial search, including debounce | 842.8ms | 792.5ms |
| Employee partial search, including debounce | 299.5ms | 791.7ms |
| Company selector availability/filter | 19.5ms | 188.4ms |

Employee/selector samples include asynchronous cold/on-demand work and are not
claimed as improvements. Employee HTTP medians were42.84→59.24ms (339bytes).
Company metadata now loads only when needed instead of in initial startup.
Dashboard service timings varied with the LAN; its SQL/metric rules are unchanged.
The representative dashboard EXPLAIN ANALYZE measured0.314→0.253ms server execution
(0.660→0.602ms planning), supporting round-trip/payload work rather than speculative
indexes. These are Mac app/browser→office PostgreSQL measurements, not Windows
NSSM or concurrent production-load benchmarks. Runtime traces are private/ignored.

Final focused batch:25 Python tests passed;38 JS checks passed. It covers canonical
employee CRUD/UUID/FK/history, inactive assignments, real isolated Alembic rollback,
new Active defaults/null salary semantics, guarded edits, workflow retirement and
restore, correction/closure, scoped ETag304, batch equivalence/constant query count,
real selection/joining eligibility, public caching, immutable CSS/reference and
legacy URL routing. Existing blocked/cumulative/historical/email actions, retry and
stale-response checks passed. Ruff, Python/JS syntax, generated-source and Git
whitespace checks passed. Starlette emits its existing httpx deprecation warning;
no unrelated package change was made.

Browser checked default dashboard, five-tab order, persistent sidebar, employee
search/CRUD (earlier checkpoint), real JD creation/assignment, zero/null preservation,
interview edit/remove/restore/occupied protection, Contact attachment, direct/normal
progression, feedback, scheduling, correction/restoration, explicit closure and
history. Two sessions verified automatic feedback updates, unsaved JD409 conflicts,
Reload and review, and an unchanged unsent Email Studio draft. The final lazy build
again synchronized feedback across sessions. All nine stage cards measure138×114px.
Candidate Desk loaded244 results, Register Candidate and Foundit; Companies retained
Prepare Proposal. Lazy Email opened without mounting Candidate Desk and read back
the canonical candidate, recipient and JD. Gmail stayed disabled; no email was sent.

Screenshots (local ignored artifacts, all synthetic data):
- `output/playwright/jd-workspace/01-employees.png`
- `output/playwright/jd-workspace/02-dashboard-desktop.png` (1600×1000 viewport)
- `output/playwright/jd-workspace/02-dashboard-mobile.png` (390×844 viewport)
- `output/playwright/jd-workspace/03-create-jd.png`
- `output/playwright/jd-workspace/04-interview-rounds.png`
- `output/playwright/jd-workspace/05-pipeline-actions.png`

Both immutable HTML reference hashes remain unchanged. The embedded approved Email
Studio document is byte-identical after module extraction. Proposal templates,
Gmail transport/security, resume/storage services and Windows NSSM configuration
were not changed. No office/public/production records or schema were written.
Only disposable/synthetic remote namespaces received functional test writes.

### Local checkpoint list and deployment boundary

- `5f7d2b0` — employee management and recruiter assignment.
- `5a0dd2e` — approved workspace navigation/layout.
- `dfd9496` — interview management and pipeline actions.
- `f3fbaf3` — explicit closure and auditable attachment correction.
- `95feb5d` — targeted refresh and synchronization.
- Performance checkpoint: see the final local Git log/report.

No push or deployment is authorized. Before office deployment, separately approve
backups and explicit Alembic0008 plus workspace_v1 migration to the office schema;
its original schema was intentionally left unmigrated. Rehearse the same release
under native Windows/NSSM with the real office dataset and approved access policy.
No cutover, real Gmail send or Windows storage validation was performed here.
