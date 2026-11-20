> Frontend update (20 Nov 2026): the earlier independent presentation described below is superseded by the immutable approved V12 HTML integration. See [approved UI verification](v12-approved-ui-verification.md) and [element matrix](v12-approved-control-matrix.md). Backend/schema safeguards below remain applicable.

# Unified Workspace V12 development review

Implemented on `feature/unified-workspace-v12` from checkpoint `2e0c7bc`.
Production remains SQLite V2. No live migration, application cutover, commit or push
is part of this implementation. The V12 feature flag defaults to false, and startup
never invokes the V3 upgrade.

## Architecture and compatibility decisions

The three routes `/workspace-v12/companies`, `/workspace-v12/candidates` and
`/workspace-v12/jobs` use the existing FastAPI/Jinja/module architecture and canonical
SQLite IDs. Company records come from SQLite, candidate profiles reuse the existing
search/resume services, and JD tracking reuses the existing workflow/round services.
The HTML reference supplies presentation and interactions only: no demo records,
browser-local masters, name-based identity joins or localStorage are imported.
Legacy routes are retained and labeled as PostgreSQL tools.

The proposal is a design, not executable SQL. The implementation resolves these
compatibility points:

* Preserve the eight existing canonical tables. Add `company_audit_events` as a
  ninth, append-only audit table because recruitment events require a candidate or
  JD; company-only changes cannot safely fit that contract.
* Retain the original `SELECTED` stage for Not Joined/Selection Cancelled and derive
  the effective closed status from `selection_outcome`. Neither becomes rejection.
* Record selection date separately from actual joining date, UTC recording time,
  confirmation evidence and declared actor. Existing ambiguous legacy selected or
  joined rows remain conservatively locked; do not manufacture placement facts.
* Use serialized `BEGIN IMMEDIATE` transactions plus database triggers for global
  allocation checks. Another unresolved selection/joining blocks both new pool
  association and selection in another existing membership. Existing memberships
  and events remain intact. Selected/joined candidates remain searchable.
* Count successful placements only from explicit joining confirmation and actual
  `joined_on`. Week starts Monday; dates use Asia/Kolkata, inclusive custom bounds,
  calendar months and years. Reactivation retains the historical placement count.
* Extend embedded company contact objects with validated email/primary-email fields;
  preserve contact IDs, names, phones, order and source JSON. JD contact choice saves
  a snapshot and audit event. Company audit records create/edit facts without
  inventing history for the 136 existing companies.

## Migration and validator contract

`schema.sql`, `SCHEMA_VERSION=2`, the existing initializer and V1→V2 upgrade remain
unchanged. `UNIFIED_SCHEMA_VERSION=3` and `upgrade_v2_to_v3.sql` compose the expected
V3 schema. `validate()` accepts the exact known V2 or V3 object signatures; it does
not relax validation to arbitrary extra tables/triggers. `upgrade_unified()` is an
explicit API, transactional, idempotent and checks every original field and ID.

Necessary additive columns cover placement facts/action provenance on
`jd_candidates`, contact snapshots/action provenance on `job_descriptions`, and
company audit request metadata. Derived allocation, placement and dashboard views
replace duplicated placement storage. Relevant stage/audit triggers and indexes are
versioned with the patch. No old rows are backfilled, merged or deleted.

Rehearse only into a new private directory:

```sh
.venv/bin/python scripts/rehearse_unified_v12.py \
  --source /absolute/path/to/verified/ats.sqlite3 \
  --output /absolute/path/to/new/private/rehearsal
```

The script reads its source with SQLite read-only mode, uses the backup API to
create copies, validates schema/integrity/FKs, reconciles every pre-existing field,
tests a forced transaction rollback, and verifies repeat upgrade makes no changes.
It exposes no production-cutover option. Process interruption is covered by tests.

The populated rehearsal at `runtime/v12-development/rehearsal-final/` preserved
187 candidates, 136 companies, 110 contact objects, 17 resume/parse records and 204
events, with zero JDs/associations/rounds/activities before and after. Its new
company audit table starts empty. Reports and databases are private/ignored.

The loopback preview at `http://127.0.0.1:8766/workspace-v12/companies` uses a
separate `runtime/v12-development/preview.sqlite3` plus private copied ATS resume
files and clearly named synthetic fixtures. Its PostgreSQL address is an unused
loopback port. It is neither the production application nor the preservation
rehearsal database. Temporary capability keys are private and never in source.

## Action, resume and email behavior

Outcome/contact/company/parsed-approval requests carry UUID keys and immutable
request hashes. Other V3 writes require `Idempotency-Key`; transactional receipt
events prevent duplicate resources and stale request retries. A reused key with a
different request conflicts. Receipt events remain in the audit database but are
filtered from the business timeline. Original change/stage events remain the
canonical business audit. V2 behavior remains compatible.

Parsing is a reviewed, versioned JSON workflow. The user sees new/same/conflicting
master fields, explicitly chooses approved fields, and the transaction saves a new
parsed version, applies only those fields and refreshes search. Original resumes
and other versions remain available. Imported historical parsed evidence still
requires renewed review; no processor identity is silently attached.

Email context is a read-only preview using canonical candidate/JD/company/contact
IDs. Candidate preselection previews withhold company details. Recipient and subject
can be edited/copied; authorized selection contexts can open the existing full
Email Studio in an embedded view. Preview and copy create no send or recruitment
milestone events. No SMTP, payment, invoice or financial transaction is enabled.

V3 editing uses optional shared operator/supervisor capabilities, an eight-hour
HttpOnly SameSite cookie and same-origin checks. There are no default keys. Use
independent cryptographically random secrets if configuring an isolated preview.
The recorded name is **declared**, not a verified individual login; reactivation
requires the supervisor capability. A production identity/access policy needs
explicit review before live use. Keep the SQLite file private behind one app host.

## Legacy operational migration plan — not executed

PostgreSQL remains authoritative for the legacy tools and their operational history.
ATS SQLite is authoritative for its imported candidate/company master identities,
ATS resume versions, JDs, memberships and new ATS events. The separate resume
processor remains authoritative for its own processing candidates, resumes and
parse-control identities. File evidence stays associated with its original store.

The checkpoint observed the following legacy backlog; recount and freeze a fresh
source snapshot before any future migration. Every future target row needs an
explicit source-system/table/primary-key mapping, original source JSON, original
timestamps and a stable event deduplication key. Do not map by names or invented
chronology. These targets are design proposals requiring separate schema review.

| Legacy source | Checkpoint rows | Proposed treatment / reconciliation gate |
| --- | ---: | --- |
| `job_requirements` | 7 | Map company UUID via existing canonical company ID. Preserve every JD field and source UUID. Resolve workflow/status/owner semantics; use an explicit provenance mapping before inserting into canonical JDs. Never infer candidate membership. |
| `activities` | 23 | Reconcile real source candidate/JD foreign keys independently. Only attach using verified mappings; retain unresolved references in preserved evidence. Append original activity/event facts once with source PK and actor snapshot. |
| `tasks` | 2 | Preserve task owner, dates, status and entity references in a separately approved task entity; tasks are not recruitment milestones. |
| `job_recruiters` | 4 | Preserve recruiter IDs and history; design explicit actor mapping. Do not conflate recruiters, staff, shared capabilities or processor users. |
| `candidate_visits` | 2 | Preserve original candidate UUID, visit date, notes and recorder in an approved visit-history entity; no invented JD association. |
| `job_search_requests` | 3 | Preserve request identity, candidate/visit links, preferences, follow-ups and actors in a request-history entity; never manufacture selections or JDs. |
| `staff_members` | 5 | Preserve staff UUIDs and actor snapshots in a separately reviewed identity model. No automatic login provisioning. |
| Domain catalogs | Recount | Preserve catalog IDs/hierarchy/active flags and candidate/JD references; approve mapping before introducing catalogs to SQLite. Free text stays intact. |

Future procedure: fresh complete PostgreSQL/SQLite/processor/file backups → restore
and reconcile in isolation → field-by-field mapping review including nulls, decimal
money, JSON, timezone and unresolved FKs → dry run → duplicate/idempotency and
failure/rollback tests → exact source/target counts and exception register → user
approval → controlled live transaction with conflicting writers stopped → final
reconciliation and retained rollback evidence. Keep PostgreSQL, original documents
and all source IDs accessible until that process succeeds.

## Validation and remaining limits

Synthetic tests cover migration identity preservation, interruption/rollback,
idempotency, allocation races, explicit joining/closure/reactivation, email/contact
ownership and no-send behavior, reporting periods, access gates, parsed review,
search enrichment and default-off startup. Existing Python/JavaScript suites and
desktop/mobile browser checks form the deployment gate; private logs live under
`runtime/v12-development/` and screenshots under `output/playwright/`.

Validation on 19 November 2026: **419 Python tests passed, 16 opt-in tests skipped;
20 JavaScript tests passed**. The 14 V12 cases are included in the Python total.
The legacy create/drop fixture and its imported resume tests ran in a separate
disposable PostgreSQL cluster to avoid dropping tables used by the migrated session
fixture. Ruff, JavaScript syntax and Git whitespace checks passed. Desktop 1440px
and mobile 390px checks covered all three workspaces, profile tabs, searchable
joined candidates, allocation blocking, explicit selection/joining, contact email
editing, no-send previews/copy, and custom-date controls. The populated clone and
the unchanged production baseline passed integrity/FK and complete-row checks.

The seven historically unavailable resume files remain unresolved; their metadata
and source evidence are preserved. No replacement files are fabricated. Existing
imported salary values/source precision remain intact. Ordinary salary-edit APIs
still accept whole INR; V12 only submits changed profile fields so unrelated edits
do not coerce historical fractional salaries. An exact-money editing contract is a
separate review. Multiple selection episodes for the same candidate/JD need a
future episode model; the current association preserves one selection and immutable
joining/closure facts. Legacy ambiguous outcomes need reviewed evidence rather than
automatic backfills. Shared capabilities do not provide individual authentication.

Live deployment requires a new current backup, a rehearsal against that exact
backup and deployed application version, writer coordination, reviewed identity
policy, explicit user approval and a separate production cutover procedure. This
development implementation intentionally stops before that gate.
