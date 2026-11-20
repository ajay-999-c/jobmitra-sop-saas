# Candidate parsed-resume and complete-edit verification

Verified on 20 November 2026, on `feature/unified-workspace-v12`. These two candidate features are implemented and tested only against isolated development data. Nothing was deployed. HEAD remains `2e0c7bc5b2d98949403490d887d7dee68fd26398`; the retained stash and staging area are unchanged. Existing work from earlier tasks remains in the working tree.

## Delivered behavior

Parsed Resume now separates Structured JSON and Jobmitra Altered Resume PDF within the approved Full Candidate Profile. Upload/paste creates an unapproved, preserved JSON draft tied to the exact canonical resume ID and SHA-256. History includes status, source version and timestamps. PDF upload/selection uses existing JOBMITRA_STANDARD storage, local extraction, inline preview and exact-byte download. Identical content/provenance reuses the existing version; different provenance can share the verified immutable PDF bytes through a separate metadata version. Original and altered histories remain separate.

The review shows current values, validated proposals and source evidence. Every proposal starts unchecked. Approval updates only checked fields, checks the displayed profile revision, creates an immutable reviewed version and audit records in the same transaction, reads the result back and refreshes search. Earlier JSON, unknown/rejected information, source documents and previous reviewed versions remain preserved. A draft alone never changes master fields or search evidence.

Complete Edit Candidate Details exposes 22 core fields, six additional scalar/evidence fields and four typed repeatable collections with 17 field types. It covers contact, links, location, professional details, employers/roles, exact months, salary period/basis, notice, availability, relocation, source, employment/education, certifications and projects. Only fields edited in the rendered form are submitted. Historical whitespace and unedited defaults are not normalized accidentally. Cancel performs no mutation. Stale changes return 409. Declared reviewer/capability and before/after state are audited; canonical SQLite/PostgreSQL identity mappings are not editable.

Salary inputs stay decimal strings through submission and validation. Supported new edits allow up to four decimal places; any SQLite value that cannot round-trip exactly is rejected transactionally. Untouched historical values remain untouched. Notice text is separate from verified normalized days. Exact experience months and derived years must remain consistent.

## Actual extraction capabilities and limits

`pypdf` extracts text locally. A conservative explicit-label parser can propose current title/designation, current employer, skills/technologies, qualification, current location, professional summary and explicitly labelled total years/months. Every proposal retains its source line as evidence.

There is no connected general narrative-to-structured resume parser or OCR. Narrative previous employers, dates, role histories, education, certifications, projects, responsibilities and achievements require reviewed structured JSON or manual editing. The existing separate Resume Processor invokes external LLM services and is not called here. No external ChatGPT/Claude/AI request was made.

Statuses are truthful: `PARTIAL_STRUCTURED_DRAFT` for limited labelled PDF extraction, `TEXT_ONLY_PARSER_PENDING` when text has no validated supported fields, `OCR_REQUIRED` when no usable text exists, and `EXTRACTION_FAILED` on extraction error. Uploaded JSON is a validated `STRUCTURED_DRAFT`; explicit review produces `APPROVED_FIELDS`. A text extraction success is not presented as a complete structured parse.

For historical JSON rows where original text bytes were never recorded, the UI explicitly says that download serializes preserved database metadata. The new upload/paste workflow preserves original UTF-8 bytes/text, including BOM and whitespace; reviewed versions download the original linked draft artifact.

Candidate Search includes canonical and explicitly reviewed professional evidence, including previous roles. It has no dedicated per-employment-date, role-duration, certification or project filters. Unknown JSON structures remain preserved but are not guessed into the typed schema. Those are remaining parser/advanced-search limitations.

## UI/API mapping and original controls

The complete mapping is in [the additive control inventory](v12-parsed-edit-additive-controls.md). Original approved controls were regenerated independently: **334 occurrences**, exactly matching the prior inventory (shell 4, Companies 65, JD 90, Candidate 114, Email 61). See [the original control parity matrix](v12-parsed-edit-control-matrix.md). This source inventory is not a claim that every conditional control was individually clicked in this pass.

| UI workflow | Actual API |
|---|---|
| Profile prefill/read-back | `GET /api/v12/approved/candidates/{cid}/profile` |
| Complete save | `PATCH /api/v12/approved/candidates/{cid}/profile` |
| Before/after audit | `GET /api/v12/approved/candidates/{cid}/profile-history` |
| JSON upload/paste | `POST /api/v12/approved/candidates/{cid}/parsed-drafts` |
| Draft/review details | `GET /api/v12/approved/candidates/{cid}/parsed-drafts/{id}` |
| Preserved JSON download | `GET /api/v12/approved/candidates/{cid}/parsed-drafts/{id}/download` |
| Altered PDF extraction | `POST /api/v12/approved/candidates/{cid}/resumes/{rid}/extract` |
| Inline PDF | `GET /api/v12/approved/candidates/{cid}/resumes/{rid}/preview` |
| Explicit field approval | `POST /api/v12/approved/candidates/{cid}/parsed-drafts/{id}/approve` |
| Existing resume history/upload | `GET/POST /api/ats-v2/candidates/{cid}/resumes` |
| Exact resume download | `GET /api/ats-v2/candidates/{cid}/resumes/{rid}/download` |
| Existing current-version control | `POST /api/v12/approved/candidates/{cid}/resumes/{rid}/current` |
| Search/refresh/access | `/api/v12/approved/search`, `/api/v12/approved/state`, `/api/v12/access` |

Private profile/history/JSON/PDF access requires the existing workspace capability session. Mutations require same-origin requests and UUID idempotency keys. Actor names are declared audit snapshots; they are not an individually verified identity-provider login. This existing development access model is unchanged.

## Changed files in this pass

New production code:

- `src/jobmitra/modules/ats_v2/parsed_documents.py` — draft normalization, local extraction, evidence, preservation, atomic approval.
- `src/jobmitra/modules/ats_v2/parsed_router.py` — private candidate parse/review/PDF endpoints.
- `src/jobmitra/static/ats_v2/parsed-resume.mjs` — JSON/PDF UI, source/history/evidence, explicit approval and verified downloads.

Updated production code:

- `src/jobmitra/modules/ats_v2/candidate_profiles.py` — typed history, exact salary checks, omitted-field preservation, composable transaction and revision safety.
- `src/jobmitra/modules/ats_v2/profile_router.py` — authenticated profile/history access.
- `src/jobmitra/modules/ats_v2/resumes.py` — valid PDF uploads, source metadata, existing-version/immutable-byte reuse, parse status projections.
- `src/jobmitra/modules/ats_v2/router.py` — upload metadata/reuse integration and private V3 download authorization.
- `src/jobmitra/modules/ats_v2/approved_router.py` — parsed router registration/private legacy parsed read.
- `src/jobmitra/static/ats_v2/candidate-desk.mjs` — complete editor refinements, rendered-value diff, structured rows and real downloads.
- `src/jobmitra/static/ats_v2/approved-api.mjs` — actual upload/read-back adapter and source/reuse options.
- `scripts/build_approved_v12.mjs`, `scripts/v12-adapters/candidates.js`, generated `src/jobmitra/static/ats_v2/approved.mjs` — delegate parsed UI, preserve salary fractions in candidate presentation, reproducible build.

Verification/documentation: new `tests/test_v12_parsed_documents.py`, updated candidate complete-edit tests and the existing V3 retry PDF fixture in `tests/test_unified_v12.py`, `scripts/inventory_approved_v12.mjs`, the two control inventories and this report. Runtime logs and browser artifacts are retained outside application source.

The complete editor/profile extension and some Candidate Desk/Foundit/navigation scaffolding were already saved by the preceding interrupted task. This pass completed/refined the requested edit workflow and added the parsed workflow. It did not expand or claim completion of unrelated Foundit/navigation work. The full `git status` includes earlier V12 changes and is not the change list for this request.

## Development schema

**No schema migration or new table was applied during this pass.** SQLite remains V3. JSON/PDF drafts reuse `candidate_resumes`. Complete edit reuses the already-installed optional `candidate_profile_versions` extension from the saved work: one append-only typed profile/audit table, one index, update/delete prevention triggers. Its `profile_json` stores typed additional profile fields; before/after/provenance and reviewer/timestamp/request identity remain separate. It does not overload unrelated core candidate columns. Original import JSON is retained unchanged.

The main isolated V3 database already had that extension before this request. All browser writes used a separate copy at `runtime/v12-parsed-edit/dev/ats.sqlite3`, with private resume/proposal copies. Startup never installs this extension automatically. Production V2 was not opened for mutation or upgraded. A production cutover remains separate work.

## Functionality results

| Check | Result | Evidence |
|---|---|---|
| Original upload/download | PASS | Actual UI upload and download; exact bytes/hash compared |
| Altered PDF upload/preview/download | PASS | Actual PDF viewer renders document; stored/downloaded bytes identical |
| Existing altered PDF reuse | PASS | UI reupload kept ID 251185852285075, one standardized version and one physical PDF; only a new parse draft was added |
| JSON upload/paste/history/source linkage | PASS | API tests and browser upload; exact BOM/whitespace and unknown fields retained |
| PDF limited extraction and source evidence | PASS | Labelled fixture creates partial draft; master unchanged before approval |
| Pending/OCR/error states | PASS | Automated text-only, blank and forced-extraction-failure cases |
| Selected-field approval | PASS | UI and API selected skills/title only; unselected employer unchanged |
| Original/rejected/version preservation | PASS | Raw JSON/source hashes, history, source ID and audit assertions |
| Complete edit and read-back | PASS | All 22 core fields, 6 extras and 4 collections filled through UI and reconciled independently |
| Historical salary/notice/whitespace | PASS | Exact decimals and notice evidence preserved; unrelated edit did not trim historical summary |
| Cancel | PASS | API state before/after equal |
| Stale editor and approval | PASS | Real second-reviewer update; save rejected 409; newer role and prior summary retained |
| Authorization/ownership/identity | PASS | Private reads/writes refused without access; cross-candidate/source and name checks |
| Duplicate request and rollback | PASS | Idempotency tests; forced failure after master save rolled back profile, audit and reviewed version together |
| Search skills/current/previous role | PASS | Real UI returns one correct candidate; actual API returns canonical ID for all three terms |
| Companies/JD/Email regressions | PASS | Existing suites, read-only browser smoke and byte-identical component/Email checks |
| Desktop/mobile | PASS | Edit bounds and document overflow checks at widths 390, 768, 1024, 1440; screenshots inspected |
| Production preservation | PASS | Every row/schema/artifact compared against protected checkpoint; integrity/FK checks pass |

Broad Python regression: **472 passed, 16 skipped** (444 canonical + 28 separate compatibility tests). The skipped tests require six opt-in company import, seven opt-in company UI and three live-database integrations; they were not run against production. Tests used a disposable local PostgreSQL cluster, never the configured production PostgreSQL. The targeted candidate/parsed group passed **21 tests** and is included in that regression. JavaScript: **20 passed**. Scoped Ruff and `npm run check:v12` passed. Browser expected stale-write HTTP 409 was verified as a rejection, not a JavaScript failure. One CLI response-body eviction was resolved through independent API/SQLite read-back; no click-only success was counted.

## Screenshots

| View | Desktop | Mobile |
|---|---|---|
| Complete editor | [1440px](../output/playwright/v12-complete-edit-1440.png) | [390px](../output/playwright/v12-complete-edit-390.png) |
| Parsed JSON/PDF | [1440px](../output/playwright/v12-parsed-resume-1440.png) | [390px](../output/playwright/v12-parsed-resume-390.png) |

Additional evidence: [PDF actually rendered](../output/playwright/v12-pdf-preview-current.png), [mobile PDF preview](../output/playwright/v12-pdf-preview-mobile.png), [live PDF reuse and unapproved draft](../output/playwright/v12-parsed-live-reuse.png), [all-field editor](../output/playwright/v12-complete-edit-filled-desktop.png), [structured histories](../output/playwright/v12-complete-edit-structured-desktop.png), [stale-save rejection](../output/playwright/v12-complete-edit-stale-conflict.png), [precise persisted values](../output/playwright/v12-complete-edit-readback.png), [search read-back](../output/playwright/v12-approved-search-readback.png), [Companies](../output/playwright/v12-parsed-edit-company-regression.png), [JD](../output/playwright/v12-parsed-edit-jd-regression.png), [Email Studio](../output/playwright/v12-parsed-edit-email-regression.png). Native PDF content is lazily painted by Chromium when scrolled into view; the focused PDF screenshot verifies actual rendering.

## Preservation proof

Approved original HTML remains byte-identical:

`Jobmitra_Unified_Workspace_V12_Companies_Integrated (1).html`

SHA-256: `a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.

All other baselined original references and Email Studio files are unchanged. Companies/JD markup, styles and component logic match the pre-request generated implementation byte-for-byte. Embedded Email Studio matches both the pre-request bytes and immutable original; its standalone files were not edited. Company/JD/Proposal backend files were unchanged in this pass.

Production ATS and Resume Processor: every row/schema matches the protected checkpoint. Production retains **187 candidates, 136 companies, 17 resumes, 204 recruitment events**. All protected file hashes match: 8 ATS resumes, 8 legacy documents, 282 processor artifacts. PostgreSQL received no production connection/migration/write. Git HEAD/stash are unchanged; no commit, push or deployment.

Main isolated V3 remains **190 candidates, 139 companies, 20 resumes, 288 events**, every row/schema equal to its pre-request snapshot. Test copy has **191 candidates, 139 companies, 27 resumes, 319 events**; every pre-existing relational row is identical. The added candidate and related versions/events are clearly named synthetic fixtures, not hardcoded application data. Test-copy integrity is `ok` and foreign-key violations are zero.

Actual browser downloads matched their sources:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| Original PDF | 1441 | `71913270e0199e6a7f119abee8edf3ad6e48e89c7e5f3d5b30a70e31c65b5250` |
| Altered PDF | 1652 | `c94e2e5cf7316d1d192e346b0b329942fba4f0e0e792c0d7d214620d29df8121` |
| Uploaded JSON | 217 | `91cf9c1f32a11e44f2733ebd91d417273ab356784226b85a2d5fbf2c55e1a0de` |

Evidence: `runtime/v12-parsed-edit/database-preservation.json`, `download-verification.json`, `browser-edit-readback.json`, regression logs and `runtime/v12-parity/final-safety-verification.json`.

The dedicated test preview is on `http://127.0.0.1:8002/workspace-v12/candidates?section=candidates&candidate_id=281158723955596`. It uses the separate synthetic-test copy. Existing servers/configuration were not switched to this database; no production deployment was performed.
