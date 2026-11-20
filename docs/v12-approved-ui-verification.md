# Approved V12 integration verification

Verified on 20 November 2026. Review preview: `http://127.0.0.1:8768/workspace-v12/companies`.
The preview uses `runtime/v12-parity/approved-preview.sqlite3` and copied private resume storage.
Production remains SQLite V2. No production migration, deployment, commit, push, reset, clean or stash operation was performed.

The presentation now comes from the approved HTML rather than the earlier independent V12 templates.
The generator verifies SHA-256 `a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e` before reading it.
It writes separate application artifacts and never writes the original reference.
All three original shadow-component style blocks and static element IDs match the reference, in order.
The embedded Email Studio document is also byte-identical; the parent supplies canonical context at runtime.

This establishes source and workflow parity, with the explicitly listed integration changes below.
It is not a claim of identical pixels across fictional reference records and actual database records,
or a claim that every conditional control occurrence has been individually clicked.

## Deviations corrected

| Earlier deviation | Correction and evidence |
|---|---|
| Independent Companies, Candidate Desk and JD Tracking layouts | Generated the original shell, original component markup, styles, navigation, tabs, wording, responsive rules and renderers from the immutable approved file. Desktop/mobile screenshots below. |
| Simplified candidate interface omitted the approved full profile and document review flow | Restored Candidate Search, Dashboard, Candidates, JD Pools, Resumes, Full Candidate Profile, original resume upload, parsed JSON preview/field checkboxes/identity confirmation and JD history. |
| Independent company cards/contact editor/analytics presentation | Restored approved period/scope controls, metrics, chart, directory, company tabs, placement register, company form, contacts and placement detail modal. |
| Independent JD editor and stages | Restored approved JD dashboard/editor, workflow presets, round names/modes/reorder/archive, review confirmation, stage cards, cumulative stage lists, batch email selection, feedback, interview and placement workflows. |
| Prototype seed records and browser persistence | Removed master seed creation and localStorage/IndexedDB persistence. Empty workspace browser verification left candidates, companies and jobs at zero. Historical imported records, including any old names containing “DEMO”, are preserved. |
| Prototype successful mutation messages | Save confirmation follows successful API persistence and fresh state reconciliation. Invalid, foreign-ID, duplicate, stale, unauthorized and allocation-blocked requests are rejected by services. |
| Resume filename-only storage and local JSON promotion | Actual private resume bytes/version lineage, scoped downloads, exact raw JSON preservation and explicit approved-field updates. Earlier source JSON and identity are retained. |
| Name-based company/contact matching | Company UUID, contact UUID, candidate ID, JD ID, membership ID and round UUID flow through API requests. Optional JD contact text remains compatibility text; only an exact contact UUID selects a canonical contact. |
| Selection and feedback could partially succeed | One transaction records the outcome and optional typed feedback; injected feedback failure rolls the outcome back. Retries replay once. |
| Selection treated as joining | Explicit actual date/evidence confirmation; joined date drives placement analytics. Selected candidates stay searchable but cannot join another pool. |
| Closed selections displayed as active work or raw codes | Distinct Not Joined / Selection Cancelled labels and terminal behavior. Historical selected stage/date remain; closed outcomes are not converted into Not Selected. |
| Manual placement/interview notes appeared as latest recruitment feedback | Latest feedback excludes interview schedules and placement milestones. Their separate timeline evidence remains available. |
| Email context had a missing confirmed joining date | Prefill now includes canonical `joined_on`; browser read-back verified `2026-11-20`. |
| Concurrent company forms could overwrite newer values | Company/contact/archive writes require the exact snapshot revision from the form; a fresh stale request returns 409 without any row/event change. Browser verification: another save 200, stale form 409 with identical state, reloaded form 200. Idempotent retries still replay. No schema change. |
| Archived contacts could remain default recipients | Archived records remain in contact/audit history, but live recipient selection and prefill require an active contact. Historical JD contact snapshots remain unchanged. |
| First generated template returned HTTP 500 | Wrapped literal approved shell CSS in Jinja raw blocks; all three workspace URLs return HTTP 200. |
| Empty JD initialization assumed a first record | Empty database initialization now renders all three workspaces without errors or demo records. |

## Deliberate integration differences

The original file itself has **none** of these changes. They apply only to the generated application.

- Reset/simulate/create-demo controls retain their approved placement and styling, with truthful Reload records / Record JD selection / Create company wording. Reload never erases data.
- Company delete and contact removal archive evidence instead of deleting originals. Company/contact IDs, source register IDs and historical snapshots are retained.
- Original prototype/local-storage help text is replaced by truthful server-storage and audit descriptions.
- Editing requires an explicitly configured operator/supervisor capability and a declared actor. Actual outcome date, joining evidence or closure reason is requested before the corresponding write.
- Canonical IDs replace prototype IDs. No mapping uses a company name or contact name as an identity key.
- The unchanged embedded Email Studio's example-data control is intercepted by its parent and relabeled Reload candidate details; it reloads the canonical context. It creates no example master records and changes no standalone Email Studio file.
- Manual offer/onboarding/follow-up/invoice/payment statuses record facts only. They do not send email, issue invoices, collect money or claim those operations succeeded.
- Staff, Foundit Paste and Domain Catalog controls use their retained legacy routes; their PostgreSQL compatibility remains intact. Their migration into the SQLite workspace is deferred. The original reserved placeholder markup remains preserved.

## UI-to-API mapping

`C` = canonical candidate ID, `J` = JD ID, `L` = JD membership ID, `R` = resume version ID,
`CO` = company UUID. Contact and interview round references are UUIDs.
All approved writes use same-origin checks, capability checks, transactions and request idempotency.
View controls and unsaved drafts remain in memory; they do not invent persistence.

| Approved controls/workflow | Canonical service |
|---|---|
| Companies / Candidate Desk / JD Tracking shell and pane navigation | `GET /workspace-v12/{companies,candidates,jobs}`; initial/refresh `GET /api/v12/approved/state` |
| Editing capability | `GET/POST/DELETE /api/v12/access` |
| Candidate keywords, location, experience min/max, expected salary min/max, period/basis, Any/All, notice, availability, unknown toggles, sort, Search and Clear | `GET /api/v12/approved/search` with corresponding query parameters; every result page retrieved from the service |
| Candidate dashboard/list/profile, resume metadata, history, current eligibility | `GET /api/v12/approved/state`; canonical services `GET /api/ats-v2/candidates/{C}`, `/resumes`, `/activities`, `/history`; `GET /api/v12/candidates/{C}/eligibility` |
| Registration form, optional original resume, explicit separate-identity confirmation | `POST /api/v12/approved/registration` atomically records candidate + optional file/version + immutable registration facts |
| Edit professional skills/summary | `PATCH /api/ats-v2/candidates/{C}`; search evidence refreshed |
| Upload original resume from profile | `POST /api/ats-v2/candidates/{C}/resumes` with original bytes and filename headers |
| Resume version Download | `GET /api/ats-v2/candidates/{C}/resumes/{R}/download` |
| Parsed JSON upload/paste, preview, identity checkbox, individual field approval, Apply | Preview is unsaved draft; `POST /api/v12/approved/candidates/{C}/parsed` persists exact raw text, original source JSON, source resume ID and only approved fields |
| Download JSON | `GET /api/v12/approved/candidates/{C}/parsed/{R}`, downloaded as the preserved original text |
| Active JD choice / Add to JD / View Existing JD Pool | `POST /api/ats-v2/jobs/{J}/candidates`; existing membership and global eligibility gates; `GET /api/ats-v2/jobs/{J}/pipeline` |
| Office Visits, candidate/purpose/date/notes and Save | `POST /api/v12/approved/candidates/{C}/activity`, `OFFICE_VISIT` facts |
| Job Search Requests, role/location/status/notes and Save | Same activity service, `JOB_SEARCH_REQUEST`; original request status retained in details; closed/fulfilled use DONE activity state |
| Companies directory/search/scope, company tabs and chart | Canonical `GET /api/v12/approved/state`; reporting uses original renderer on canonical placements/calendar bounds; verified against `GET /api/v12/placements?period=...&company_id=...` |
| This week / month / year / Custom dates / Apply dates | Same canonical placement data; custom dates and calendar periods reconciled with `/api/v12/placements` |
| Add company | `POST /api/v12/companies` |
| Company form, contact fields, Add/Remove/Primary, Save; company Archive | `PATCH /api/v12/approved/companies/{CO}`; required snapshot revision, stable contact IDs, archived removed entries and full company audit history |
| Record JD selection, eligible candidate/JD choice, confirmation | `POST /api/v12/approved/jobs/{J}/candidates/{L}/outcome` (`SELECT`), requiring an existing eligible membership and completed configured workflow |
| Placement register filters/search/details, eligibility preview | Canonical placement/eligibility projection; no write |
| Placement Confirm joined / Mark not joined | Same atomic outcome service (`JOIN`, `NOT_JOINED`), explicit date/evidence/reason; original selection retained |
| Open JD Pipeline / company JD Open / candidate JD history Open | Canonical J passed to the approved JD component; `GET /api/ats-v2/jobs/{J}`, `/workflow`, `/pipeline` |
| JD picker/dashboard/activity | `GET /api/v12/approved/state`; `GET /api/ats-v2/jobs`, `/dashboard`, `/history` underlying canonical services |
| New JD / Edit JD / all detail fields / Save | `POST /api/ats-v2/jobs`; `PATCH /api/ats-v2/jobs/{J}`; exact optional contact UUID choice uses `PUT /api/v12/jobs/{J}/contact` |
| Workflow mode/presets/add/reorder/round name/mode/remove/archive/discard/review | Unsaved draft until confirmation; `PUT /api/ats-v2/jobs/{J}/workflow` with stable round UUIDs and workflow version |
| Stage cards / All / In progress / Selected-Joined / Not Selected | Original cumulative renderer on canonical memberships/events, including distinct closed outcomes |
| Advance / Not selected / optional feedback + source | `POST /api/ats-v2/jobs/{J}/candidates/{L}/move` with expected stage/round/workflow version; selection uses atomic outcome service |
| Feedback / Save feedback | `POST /api/ats-v2/jobs/{J}/candidates/{L}/feedback` |
| Interview date/time/mode/venue/notes / Save | Activity adapter, `INTERVIEW`, canonical J and round UUID, `invitation_sent:false` |
| Placement milestone Update/status/note/Save | Activity adapter, `PLACEMENT_MILESTONE`, explicit manual-fact/delivery/financial flags |
| Candidate Email and batch Include / Compose submission | `GET /api/v12/email-context?candidate_id=C&job_id=J&audience=...`; validated membership and canonical contact UUIDs; original Email Studio receives draft context |
| Email recipient/contact/subject/body edits, reset, copy, HTML download, close | Unchanged Email Studio draft controls; no recruitment, send or delivery write. Parent reload supplies canonical context. |
| Existing standalone Email Studio pages | `/email`, `/email/updates`, `/email/submission`, `/email/proposal`; unchanged files/routes |
| Staff / Foundit Paste / Domain Catalog | Retained `/staff`, `/candidates/foundit-import`, `/domains` legacy services; no route retired |

The expanded [element matrix](v12-approved-control-matrix.md) identifies each source control occurrence,
its renderer and service family. The initial [before matrix](v12-ui-parity-before.md) is retained as the audit baseline.

## Functionality results

PASS means a saved fact/read-back or meaningful automated assertion was checked, not only a click.
Browser fixtures are synthetic and reside only in the isolated preview. Backend fixtures use fresh temporary stores.

| Workflow | Result | Evidence |
|---|---|---|
| Candidate Search, combined filters and salary conversion | PASS | Skill + Pune + 3 years + 30 days + availability + CTC ₹45–55k monthly returned exactly the candidate with ₹600k annual expected salary. Valid ₹30–40k range returned zero. Clear filters restores query state. Existing search tests cover matching/unknown/ordering. |
| Candidate registration + original resume | PASS | UI-created canonical C `281158723955594`; resume `251185852285071`; salary periods, experience, notice and source read back. Atomic failure/retry/duplicate tests. |
| Full Candidate Profile | PASS | Original overview/document/history tabs restored; canonical name/title/skills/salary and JD participation verified. |
| Resume versions/downloads | PASS | UI uploaded second original `251185852285073`; both prior/current downloads HTTP 200 and exact bytes equal the synthetic original. Earlier version retained. |
| Parsed JSON approvals/download | PASS | UI approved skills/summary/projects and unchecked conflicting title; title stayed API Engineer. Exact original JSON, including unapproved title, remained downloadable byte-for-byte; skills searchable. Identity/ownership/rollback tests pass. |
| JD pool membership | PASS | UI association L `3` on J `3`; persisted once; repeat/duplicate and blocked eligibility tests. |
| JD create/edit/contact | PASS | UI-created J `3`, company/contact UUIDs and contact email snapshot read back; target/location/skills/vacancies persisted. Exact UUID required for explicit contact identity. |
| Configured interview workflow | PASS | Two UI-created round UUIDs, names/modes and order persisted only after workflow confirmation. Unsaved reorder did not mutate backend. |
| Contact → screening → submission → interview rounds | PASS | Browser advancement + API read-back at each stage; round UUIDs matched configured rounds. |
| Feedback/source | PASS | Actual feedback persisted with COMPANY/JOBMITRA source; selection feedback and outcome atomic rollback/retry verified. |
| Interview scheduling | PASS | Browser schedule `2026-11-21 14:30 Asia/Kolkata` read as `09:00Z`, correct Technical Review UUID/venue/notes; no invitation sent. |
| Selection / joining / placement analytics | PASS | Pending selection blocked new pool (409, target JD unchanged); explicit joining `2026-11-20` yields one confirmed placement and zero pending. Custom range ending Nov19 excludes joining. |
| Not Joined / canonical JD navigation | PASS | Original company modal opened J3, then closed synthetic L4; selected date/stage retained, closed date/reason stored, eligibility released, confirmed placement total unchanged. The original Add to JD control then created exactly one new POOL membership on J1. Cancellation/reactivation covered by backend tests. |
| Company create/contact edit/primary/archive | PASS | Browser-created company/contact; actual ID/email/phone read-back. Tests retain IDs/created_at/phone arrays and archived evidence; reject stale snapshots, foreign ownership and archived live recipients. |
| Office visit / job search request | PASS | Original forms saved actual activities and purpose/date/role/location/Following up details. |
| Placement milestone | PASS | Original editor saved offer ACCEPTED + note as a manual fact, `delivery_enabled:false`, `financial_transaction:false`. |
| Email Studio canonical prefill/edit/copy | PASS | Company submission uses actual contact email, editable recipient, correct current/expected CTC. Candidate joined email prefills actual email/date. Actual formatted clipboard read-back contained the canonical candidate body (1,251 characters). Copy/preview leaves canonical state unchanged; existing body-copy tests pass. |
| Email Studio Not Joined / Selection Cancelled message | BLOCKED BY APPROVED TEMPLATE GAP | Existing approved document has no corresponding template. Visible control reports the gap, opens no misleading rejection/selection email, and leaves DB state unchanged. Requires approved message content. |
| Empty Companies/Candidate Desk/JD Tracking | PASS | Zero masters before and after all pane navigation; no seed injection. |
| Legacy compatibility | PASS IN DISPOSABLE TEST DB | Existing routes retained; legacy PostgreSQL workflows exercised with private Unix-socket PostgreSQL 18, never configured production PostgreSQL. SQLite migration of those catalogs/identities remains deferred. |
| Standalone Email Studio | PASS | All four URLs HTTP 200. Every tracked Email Studio source/template/standalone HTML file byte-identical to checkpoint. |
| Original/production preservation | PASS | Protected reference hashes, every production SQLite/processor row and schema object, all retained source artifacts, HEAD and stash unchanged. |

Regression result: **398 + 28 = 426 Python passed; 16 skipped; 20 JavaScript passed**.
The 28-test group owns/drops its disposable schema and is separated from shared-fixture tests.
Skipped tests are opt-in integration/import/UI/processor checks with unsupported fixture prerequisites;
these are not reported as passes. Ruff, JavaScript syntax checks and `git diff --check` pass.
Private logs and reconciliation evidence: `runtime/v12-parity/`.

## Matching screenshot comparisons

Desktop viewport **1440 × 1000**; mobile viewport **390 × 844**. Full-page screenshots may have different heights
because the reference contains fictional records and the implementation displays saved records/filtered QA results.
Both use the same original responsive rules. Stage rails/navigation preserve the original horizontal scrolling on mobile.

| View | Desktop reference / integrated | Mobile reference / integrated | Review |
|---|---|---|---|
| Companies placement register | [reference](../output/playwright/v12-approved-companies-desktop.png) / [integrated](../output/playwright/v12-after-companies-desktop.png) | [reference](../output/playwright/v12-approved-companies-mobile.png) / [integrated](../output/playwright/v12-after-companies-mobile.png) | Approved directory, analytics, chart, tabs and responsive placement cards retained; saved metrics/data differ. |
| Candidate Search | [reference](../output/playwright/v12-approved-candidates-desktop.png) / [integrated](../output/playwright/v12-after-candidates-desktop.png) | [reference](../output/playwright/v12-approved-candidates-mobile.png) / [integrated](../output/playwright/v12-after-candidates-mobile.png) | Same controls, spacing, cards and mobile stacking; filtered real result and eligibility differ. |
| JD Tracking | [reference](../output/playwright/v12-approved-jobs-desktop.png) / [integrated](../output/playwright/v12-after-jobs-desktop.png) | [reference](../output/playwright/v12-approved-jobs-mobile.png) / [integrated](../output/playwright/v12-after-jobs-mobile.png) | Same workflow rail, stage colors, sections and controls; actual stage/round/outcome history. |
| Full Candidate Profile | [reference](../output/playwright/v12-approved-profile-desktop.png) / [integrated](../output/playwright/v12-after-profile-desktop.png) | [reference](../output/playwright/v12-approved-profile-mobile.png) / [integrated](../output/playwright/v12-after-profile-mobile.png) | Original profile and section tabs retained. |
| Parsed Resume | [reference](../output/playwright/v12-approved-parsed-desktop.png) / [integrated](../output/playwright/v12-after-parsed-desktop.png) | [reference](../output/playwright/v12-approved-parsed-mobile.png) / [integrated](../output/playwright/v12-after-parsed-mobile.png) | Original import/review controls retained; actual saved version metadata. |
| Email Studio | [reference](../output/playwright/v12-approved-email-desktop.png) / [integrated](../output/playwright/v12-after-email-desktop.png) | [reference](../output/playwright/v12-approved-email-mobile.png) / [integrated](../output/playwright/v12-after-email-mobile.png) | Same embedded document/layout and scrolling viewport; canonical recipient/date and runtime reload label differ. |

## Remaining work and deployment boundaries

1. Approve text/templates for Not Joined and Selection Cancelled email drafts. The approved source lacks these; no message has been invented or substituted.
2. Staff, Domain Catalog and Foundit retain the existing PostgreSQL implementation. Any migration of those services/identities needs its separate approved scope and UI specification; none was performed here.
3. Email transmission, real invitations, offer generation, invoicing and payment processing are not provided by the approved prototype or these adapters. Existing controls record manual facts or produce drafts; they never claim delivery/payment.
4. Production cutover still requires its own approved migration/deployment and identity/access decision. Current capability sessions record a declared actor, not an individually verified login. No production capability is configured by default.
5. Seven historically missing resume artifacts remain missing exceptions. Their original metadata is preserved; unavailable downloads are not fabricated.

## Preservation evidence

`runtime/v12-parity/final-safety-verification.json` compares protected backup snapshots using read-only SQLite connections:
production version 2; candidates **187**, companies **136**, embedded original contacts **110**, resumes **17**, historical events **204**;
zero production JDs/rounds/memberships/activities. Every original value/schema object matches the verified checkpoint backup.
Processor rows/schema also match. Source file hashes verified: ATS artifacts 8, legacy documents 8, processor artifacts 282.

`runtime/v12-parity/preview-reconciliation.json` additionally verifies every original row/field remains unchanged inside
the V3 preview; only synthetic QA records/events/activities were added. Integrity checks return `ok`, foreign-key violations zero.

The protected original HTML and all other baselined reference files remain byte-identical.
Checkpoint HEAD `2e0c7bc5b2d98949403490d887d7dee68fd26398` and retained stash remain unchanged.
Production PostgreSQL was not connected to or modified by this verification. All database tests used disposable stores.
