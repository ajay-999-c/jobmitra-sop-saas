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
