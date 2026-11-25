# Clean JD Tracking integration

## Design and architecture mapping

Visual reference: `Jobmitra_JD_Tracking_Clean_Preview.html`, SHA-256
`ed5db4da04e1c023d9473fac7ab68f50eb30463694fc9b9968def4e33599a8ad`.
The prototype is a design source only; its script, sample records and simulated
navigation/transactions are never included in the application.

| Reference component | Existing canonical integration |
| --- | --- |
| Workspace navigation / Requirement / New JD | Existing approved header, JD shadow-root navigation and `switchJob` / `newJD` handlers |
| Compact summary | Existing `targetState`, `createdDate`, `dateLabel` and `countJoined`; no prototype date arithmetic |
| Grouped stage cards | Existing `stageDefs`, `stageCount`, `stagePending`, `stageRows` and `stageDecision`; dynamic configured rounds and cumulative reach retained |
| Candidate Pool / Find Candidates | Existing `GET /api/v12/approved/search`, with opt-in identity lookup and server pagination |
| Add to this JD | Existing `native.addToPool` -> `POST /api/ats-v2/jobs/{job_id}/candidates` -> `jobs.associate`; canonical IDs and existing receipt/transaction/eligibility rules |
| In this JD / stage dropdown | Existing membership projections and cumulative stage helpers; separate current/reached/selected/closed views |
| Next Stage | Backend `jobs.pipeline` next-stage fields, existing action confirmation and `/move`; existing `/outcome` selection/joining evidence flows |
| Profile | Existing canonical Full Candidate Profile |
| Email / batch submission | Existing `pipeline-email.mjs`, canonical `/api/v12/email-context` and unchanged Email Studio |
| JD Dashboard | Existing `jd-dashboard.mjs` and `/approved/jd-dashboard`; filters, ordering and pagination retained |
| Edit JD / Workflow / Placement / Activity | Existing adapters, services, history and confirmations retained |

`scripts/build_approved_v12.mjs` remains the generator. JD adapter replacements
call a maintained clean-pipeline module; prototype CSS is generated with a
`.jd-clean` scope inside the JD shadow root. Original approved V12 HTML and the
new design reference remain byte-identical. Companies/Candidate Desk styles and
Email Studio content are outside that scope.

The search extension is opt-in (`identity_lookup=true`) on the existing approved
search route. Default professional search behavior is unchanged. No new tables,
migrations, business states, authentication mode or document-storage changes.

## Verification boundary

Write verification uses a separate disposable PostgreSQL schema/preview with
synthetic data only. Never use `jobmitra_v12_dev_20261123_integration`, `public`,
the sealed snapshot, or the Mac port 8000 shared-office profile for write tests.
No Windows service/configuration or existing office record is changed.

## Inspected architecture and changed files

Inspected the immutable approved V12 HTML, the complete clean JD prototype,
`scripts/build_approved_v12.mjs`, the jobs adapter, `approved-api.mjs`,
`jd-dashboard.mjs`, `pipeline-email.mjs`, the approved/router search endpoints,
candidate search/profile indexing, `jobs.py`, `unified.py`, request receipts,
PostgreSQL runtime/scoping rules and Office LAN authorization.

Application changes:

- `scripts/build_approved_v12.mjs`: reproducible JD markup/CSS integration,
  clean module import and confirmation terminology.
- `scripts/v12-clean-jd.mjs`: hash-checked prototype CSS extraction and scoped
  header markup; excludes all prototype scripts/data.
- `scripts/v12-adapters/jobs.js`: compact header/workflow/pipeline adapters,
  canonical counts and backend-provided next destination.
- `src/jobmitra/static/ats_v2/jd-clean.mjs`: server search, compact tables,
  per-JD transient search state, eligibility and safe attachment/read-back.
- `src/jobmitra/static/ats_v2/jd-clean.css`: generated, scoped prototype CSS.
- `src/jobmitra/static/ats_v2/approved-api.mjs`: exposes the existing backend
  next-stage/round fields; adds no transition logic.
- `src/jobmitra/static/ats_v2/approved.mjs`: regenerated component runtime.
- `src/jobmitra/modules/ats_v2/candidate_schemas.py` and `candidates.py`:
  opt-in identity/location evidence on the existing parameterized search.
- `tests/test_clean_jd.py`, `tests/test_clean_jd.test.mjs` and the JD-specific
  preservation assertion in `tests/test_approved_v12.py`.
- This document and `Jobmitra_JD_Tracking_Clean_Preview.html`, the unchanged
  hash-checked build input required to reproduce the generated stylesheet.

`templates/v12/approved.html`, the JD Dashboard module, Companies/Candidate Desk
adapters, Email Studio, storage code, schemas and SQL migrations are unchanged.

## Element and screenshot parity

| Component | Result |
| --- | --- |
| Global header | Existing approved left-aligned navigation retained; prototype preview badge excluded |
| JD secondary tabs / selector / New JD | Existing canonical controls retained |
| Summary beside title | Created, target, joined/vacancies and existing target calculation; compact right-aligned card, responsive wrap |
| Redundant controls | Removed full-width target banner, version badge, repeated edit/workflow/pipeline shortcuts, four stage-stat boxes and long footer |
| Stage rail | Supplied blue/purple/green CSS, red selected outline, darker Joined accent; dynamic rounds; cumulative counts and existing awaiting rules |
| Candidate Pool | Find Candidates default; In this JD tab; compact search, server pagination and profile/add actions |
| Linked candidates | Compact table and current/reached/selected/closed dropdown; historical outcomes remain distinct |
| Next Stage | Visible destination from backend; existing confirmation, feedback and selection/joining evidence retained |
| Desktop | Reference and integration captured at 1465 × 1000 |
| Mobile | Reference and integration captured at 390 × 844; full-page captures; document width equals 390, workflow rail scrolls internally |

Computed interview colors were `rgb(245,241,252)` / `#9775d5` /
`rgb(103,64,165)`; outcome colors were `rgb(234,248,240)` / `#3ca779` /
`rgb(20,103,70)`. Core accent is `#7099d6`, core text `rgb(37,76,127)`;
selected stage background is white. The reference starts at 128px / 102px
minimum stage dimensions. The final sizing correction fixes every card to
138 × 114px with matching width, height and flex-basis, preventing title-driven
growth or shrinking. Titles clamp to two lines with ellipsis and a full-title
hover tooltip; counts and awaiting-action labels have fixed, aligned rows.
Focused desktop/mobile browser checks verified all 15 cards have identical
dimensions, including nine long custom interview titles, with horizontal
scrolling and the existing palette/selected outline retained.

## Verification on 25 November 2026

Preview: `http://127.0.0.1:8892/workspace-v12/jobs`.
PostgreSQL is Unix-socket-only, database `postgres`, isolated synthetic schema
`jobmitra_v12_dev_cleanjd_preview3`. It has no network connection to the office
PostgreSQL server. Ports 8000 and 8874 were not stopped or restarted.

| Functional check | Result / evidence |
| --- | --- |
| Dashboard search, clear, newest ordering and filters | PASS: browser search reduced 4 JDs to 1; Clear restored 4; focused dashboard API tests cover filters/sorting/pagination |
| JD selection and switching | PASS: configured, direct, unknown and nine-round custom JDs |
| Name/mobile/title/skills/location search | PASS: parameterized SQLite + PostgreSQL tests; browser name/mobile lookup; 14 results across 10/4-row server pages |
| Direct attachment and identity | PASS: synthetic candidate 4294967296 -> JD 1, membership 7, initial POOL, canonical read-back |
| Addition feedback/counts | PASS: 4 -> 5 linked; Pool reached 4 -> 5, awaiting 0 -> 1; retained query/JD; Already added disabled |
| Duplicate prevention and recovery | PASS: same receipt yields one membership; JS double click shares one promise; uncertain retry retains request owner; canonical read-back required |
| Eligibility | PASS: selected/on-hold and joined/placed candidates remain visible with reason and disabled Add; default service checks unchanged |
| In this JD and filters | PASS: Contact current view showed 1 candidate; All reached showed 5; closed filter retains Not Selected / Not Joined / cancellation distinctions |
| Next Stage / cumulative history | PASS: Pool -> Contact -> Screening -> Submission; earlier reached totals retained; feedback/events read back |
| Rejection and closure | PASS: browser rejection persisted with reason and red Not Selected state; no invalid Next Stage; distinct outcome/filter helper and backend tests |
| Interviews | PASS: actual configured round IDs/names, schedule activity and progression through 3 rounds; unknown plan explanatory state and 9-round scrolling |
| Selection / confirmed joining | PASS: existing effective-date and evidence confirmations; no generic Next Stage on Selected; joined_on/selected_on 2026-11-25, JOINED_CONFIRMED, PLACED_LOCKED |
| Profile and return | PASS: canonical Full Candidate Profile, resumes/parsed/JD History tabs; return retained JD/stage |
| Email / submission | PASS: existing screening/custom_round/submission templates; missing candidate email clearly shown; company draft uses hr@example.test; no send |
| Placement and activity | PASS: joined candidate in existing Placement & Billing; joining/selection/feedback history visible |
| Office LAN policy / PostgreSQL safety | PASS: password-free synthetic Office LAN requests; focused existing policy/service tests; no security changes |

Read-back for membership 7 confirmed one `ADDED`, six `MOVED`, six `FEEDBACK`,
one `COMPANY_SELECTED`, one `JOINING_CONFIRMED` and an `INTERVIEW` activity.
Internal retry receipts remain separate from visible recruitment history.
Browser console: zero application errors/warnings; observed API requests 200.

94 focused Python checks passed across the isolated SQLite/PostgreSQL runs,
including 4 new sourcing checks and 7 approved-source checks. 17 JavaScript
checks passed. Ruff, Python AST parsing, Node syntax, `git diff --check` and
`npm run check:v12` passed. The full project suite was not run.

An additional, unrelated sealed-snapshot clone test was attempted in the fresh
cluster and failed because it expects a populated staging/public restore fixture
(the empty public inventory produces `EMPTY_QUERY`). It is excluded from the
94 passing checks. No snapshot clone or migration code was changed to accommodate
that fixture. Native Windows browser verification remains pending.

## Screenshots

Artifacts are local review evidence, intentionally ignored by Git:

| Evidence | Path from project root |
| --- | --- |
| Reference desktop | `output/playwright/jd-reference-desktop.png` |
| Integrated desktop | `output/playwright/jd-clean-desktop.png` |
| Reference mobile | `output/playwright/jd-reference-mobile.png` |
| Integrated mobile | `output/playwright/jd-clean-mobile.png` |
| Candidate Pool search | `output/playwright/jd-clean-search.png` |
| Successful direct addition | `output/playwright/jd-clean-added.png` |
| Next Stage confirmation | `output/playwright/jd-clean-next-stage.png` |
| Final equal-sized cards, desktop | `output/playwright/jd-fixed-stage-cards-desktop.png` |
| Final equal-sized cards, mobile | `output/playwright/jd-fixed-stage-cards-mobile.png` |

Both HTML source checksums remain unchanged. Generated Companies/Candidate Desk
markup and embedded Email Studio compare byte-for-byte with HEAD. The meaningful
prototype deviations are real canonical records, pagination, true eligibility,
salary basis, cumulative/awaiting semantics, feedback/interview controls and
evidence-based outcomes instead of simulated actions. No office records,
production storage or Windows configuration changed. The implementation was
verified before the separately authorized release checkpoint and push.
