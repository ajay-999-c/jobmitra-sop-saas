# Company PDF proposal workflow — isolated V12 implementation

20 November 2026. Branch `feature/unified-workspace-v12`.
This supersedes the email-body proposal integration described in `v12-startup-proposal.md`.
Startup routing, browser history synchronization and canonical company/contact validation were retained.
No reset, deletion of legacy functionality, commit, push or production cutover was performed.

## Workflow preview

**Companies → company → Details & contacts → Prepare Proposal → Generate PDF → Download PDF → Prepare Email → Upload Signed Copy → explicitly record acceptance evidence.**

The existing Companies header button and Email Studio overlay remain the entry point. The proposal-specific
iframe contains the canonical company name, active contact, editable recipient, consultant legal name,
issue date, optional reference, two approved fee options and an optional illustrative Annual CTC.
No proposal action or duplicate composer was added to Candidate Desk or JD Tracking.

Before generation, the form is an **unsaved Draft**. Generate PDF creates a **Prepared** immutable version,
private PDF file and SHA-256 checksum. A blank reference receives a server-generated reference.
Every stored version includes the actual company/contact snapshot, recipient, fee, original ten clauses,
source checksum, declared preparer and capability role. Form edits never change an earlier PDF.
Selecting history explicitly opens the preserved version; unsaved form changes require generation.

The PDF is branded, two-page A4 for the verified examples. It contains the commercial table, exact
percentage of Annual CTC, original payment/replacement/jurisdiction clauses, representative details,
closing statement and blank client acknowledgement fields. No signature or acceptance is generated.
Optional INR examples use Decimal percentage arithmetic, then round to two currency decimal places;
the 21/30-day figures are explicitly illustrative, rounded down, and never used to calculate the fee.

Prepare Email creates the requested short subject/body from the selected historical company/contact
snapshot. Missing email remains blank. To can be edited/copied without modifying the master or version.
**No PDF is attached automatically and nothing is sent.** The UI clearly requires downloading and manually
attaching the selected PDF in the user's mail application. Copy/preview/download do not record Sent.

Signed uploads require an existing proposal and authorized operator capability. They preserve the original
uploaded bytes as a new, separate private file and checksum. Upload alone does not change status.
Sent/Accepted/Declined require an explicit confirmed action, evidence, date and declared actor.
Accepted additionally requires a signed-copy reference belonging to that exact proposal and signatory name.
No Sent event is invented when recording acceptance directly. Accepted and Declined versions are terminal;
later offers require another proposal version. Every status event remains immutable.

## Examples and visual inspection

Fictional client: **Northstar Fictional Technologies Pvt. Ltd.** No real signature or client acceptance.

- [6% example PDF](../output/pdf/Jobmitra-Fictional-Proposal-6percent.pdf)
- [8.33% example PDF](../output/pdf/Jobmitra-Fictional-Proposal-8-33percent.pdf)
- 6% rendered pages: [page 1](../output/pdf/Jobmitra-Fictional-Proposal-6percent-page-1.png), [page 2](../output/pdf/Jobmitra-Fictional-Proposal-6percent-page-2.png)
- 8.33% rendered pages: [page 1](../output/pdf/Jobmitra-Fictional-Proposal-8-33percent-page-1.png), [page 2](../output/pdf/Jobmitra-Fictional-Proposal-8-33percent-page-2.png)
- Actual browser download: [PDF](../output/pdf/Jobmitra-Browser-Verified-8-33percent.pdf), [page 1](../output/pdf/Jobmitra-Browser-Verified-8-33percent-page-1.png), [page 2](../output/pdf/Jobmitra-Browser-Verified-8-33percent-page-2.png)
- Workflow: [desktop 1440×1000](../output/playwright/v12-pdf-workflow-desktop.png), [mobile 390×844](../output/playwright/v12-pdf-workflow-mobile.png)
- [Short email draft](../output/playwright/v12-pdf-email-desktop.png), [signed-copy/status evidence](../output/playwright/v12-pdf-signed-mobile.png)
- [Original candidate Email Studio compatibility](../output/playwright/v12-pdf-original-email-regression.png)

All example/download pages were rendered and visually inspected: readable clauses, complete tables,
blank acknowledgement fields, no overlapping text, clipping or blank trailing page. The actual browser
download was parsed, its checksum reconciled to the stored version, and all ten clauses extracted/verified.
The source logo is the existing `src/jobmitra/static/stage2/jobmitra-logo.jpeg`, unchanged.

## Proposal API mapping

Base: `/api/v12/approved/companies/{company_id}`. Company/proposal/contact/document IDs are canonical UUIDs.

| Method and suffix | Purpose / writes |
|---|---|
| GET `/proposal-context?company_contact_id=...` | Existing active-contact validation/prefill; no writes |
| GET `/proposal-workspace` | Proposal-specific iframe shell; no private history in HTML |
| GET `/proposals` | Authorized company-specific versions, checksums, signed references and status events |
| POST `/proposals` | Generate and privately store a new Prepared PDF version; idempotent retry |
| GET `/proposals/{proposal_id}/pdf?download=true` | Authorized verified original bytes; inline without download flag |
| GET `/proposals/{proposal_id}/email` | Authorized short draft for that version; no delivery/attachment or writes |
| POST `/proposals/{proposal_id}/signed-documents` | Authorized base64 PDF upload, max 10 MB; append a signed-copy reference |
| GET `/proposals/{proposal_id}/signed-documents/{signed_id}` | Authorized verified bytes; company/proposal ownership enforced |
| POST `/proposals/{proposal_id}/status` | Confirmed evidence-backed action; expected-event check prevents stale writes |

Writes use the existing same-origin and operator-capability boundary and require UUID idempotency keys.
Read access to history, generated/signed PDFs and email snapshots requires the same authorized capability.
Cross-company contacts are rejected; cross-company proposal/document URLs cannot resolve another record.
PDFs are not static assets. JSON request streams are bounded before parsing, including chunked requests.
Uploads validate complete PDF structure, size, extension/plain filename, encryption and active-content checks.
Unsafe PDFs are refused without rewriting signature bytes. Private paths reject symlinks; files use UUID
storage names, mode 600, a mode-700 directory, exclusive creation and file/directory fsync before DB commit.
Downloads verify size and checksum. Database writes use serialized `BEGIN IMMEDIATE` transactions.
Rollback removes only a newly created file proven unreferenced; uncertain commit/storage failures retain
bytes rather than risk deleting a committed document. A crash can leave an unreferenced private file;
there is no automatic orphan cleanup or overwrite.

The old `/proposal-studio` and standalone `/email/proposal` remain for compatibility, byte-identical.
They are no longer offered as the Companies proposal workflow. Existing Email Studio source files and
other communication templates have not been rewritten.

## Isolated database additions

Optional **V3 proposal extension v1**; core `user_version` remains 3. Exact schema validation recognizes
both the original V3 schema and the reviewed V3-plus-extension schema. Startup never installs the extension.

1. `company_proposals`: immutable company/contact/terms/PDF snapshots and generation idempotency.
2. `company_proposal_signed_documents`: immutable received-copy versions and upload attribution.
3. `company_proposal_status_events`: append-only explicit evidence, acceptance date and signatory.

There are three lookup indexes and six update/delete prevention triggers. Company/proposal foreign keys
restrict deletion. Existing company, candidate, resume, parsed JSON and historical event rows are not updated.

The extension was installed only on `runtime/v12-local/ats-v3.sqlite3`, after a SQLite backup to
`runtime/v12-pdf-proposal/pre-proposals-v3.sqlite3`. Every pre-existing local row and schema object was compared
before/after installation. Final existing-row reconciliation also passed after browser verification.
Integrity is `ok`; foreign-key violations are zero. Production V2 was never upgraded.

The explicit installer CLI is restricted to this existing isolated path and refuses V2, missing files,
hard links and symlinked paths. If preparing another development copy later, back it up first, then:

```bash
.venv/bin/python -m jobmitra.modules.ats_v2.proposal_store --database /Users/mac/Documents/jobmitra/sop-pipeline/runtime/v12-local/ats-v3.sqlite3
```

Safe startup remains:

```bash
JOBMITRA_LOCAL_V12=1 .venv/bin/python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

That local profile explicitly enables proposals and uses `runtime/v12-local/proposal-documents`.
Normal configuration defaults `unified_v12_proposals_enabled=False` and has no proposal storage root.
There is no production proposal configuration, migration or deployment in this work.

## Verification results

Full regression: **422 + 28 = 450 Python tests passed; 16 skipped**. Final PDF-only recheck: **18 passed**,
including the added long-company/reference pagination regression.
JavaScript: **20 passed**. Ruff, Node syntax, generated-artifact byte check and Git whitespace check passed.
Tests use disposable SQLite stores and a temporary local Unix-socket PostgreSQL cluster, never production.
The 16 existing skips are six opt-in company imports, seven opt-in company UI tests and three live-DB tests.
Private logs: `runtime/v12-pdf-proposal/`.

| Verification | Result |
|---|---|
| Correct company/contact and active-contact changes | Browser + API snapshot passed |
| 6% and 8.33% real A4 PDFs | Passed; all ten approved clauses extracted verbatim |
| Percentage precision | 600000.00 CTC → 36000.00 / 49980.00; no salary-day calculation |
| Blank email / manual recipient / copy | Browser + clipboard passed; master unchanged |
| PDF preview and actual download | Browser passed; parsed PDF checksum matches stored version |
| Short company-specific email and attachment reminder | Browser + API passed; no attachment/delivery claim |
| Preview/copy/download vs Sent | No automatic status event; Prepared remains Prepared |
| Signed upload | Browser + API passed; separate version, no automatic acceptance |
| Explicit acceptance, required signed reference/signatory | Browser + API passed |
| Unauthorized access / cross-company / archived contact | Rejected in isolated tests; company switching has separate history |
| Broken/renamed/encrypted/active/oversized PDFs; unsafe path | Rejected; no signed record saved |
| Retry, concurrent generation, rollback and stale status | Passed |
| Historical PDFs / signed versions / status history | Byte/checksum preservation and immutable DB triggers passed |
| Candidate Desk, Full Profile, resumes, JD and original Email Studio | Regression suite passed |
| Desktop / mobile layout | Inspected at 1440×1000 and 390×844; no horizontal overflow |

Browser upload/status evidence uses clearly labelled **synthetic fixtures** in the isolated copy. It is not
a real signature or client acceptance, and no email was delivered. Unsaved drafts are not persisted.

## Exact source files changed for this request

Modified existing integration files:

- `pyproject.toml`: ReportLab and pypdf application dependencies.
- `src/jobmitra/core/config.py`: opt-in proposal flag and private storage setting.
- `src/jobmitra/core/local_v12.py`: isolated proposal settings only.
- `src/jobmitra/modules/ats_v2/database.py`: exact optional-extension validation; no automatic migration.
- `src/jobmitra/modules/ats_v2/approved_router.py`: include the company PDF routes.
- `src/jobmitra/static/ats_v2/v12-shell.mjs`: retain startup/navigation and company action; replace email-only adapter with PDF workflow iframe.
- `src/jobmitra/static/ats_v2/v12-shell.css`: proposal-iframe-only styles.
- `README.md`: current workflow report link.

Added:

- `src/jobmitra/modules/ats_v2/proposal_documents.py`
- `src/jobmitra/modules/ats_v2/proposal_pdf.py`
- `src/jobmitra/modules/ats_v2/proposal_router.py`
- `src/jobmitra/modules/ats_v2/proposal_store.py`
- `src/jobmitra/modules/ats_v2/proposal_schema.sql`
- `src/jobmitra/modules/ats_v2/proposal_terms.json`
- `src/jobmitra/templates/v12/proposal.html`
- `src/jobmitra/static/ats_v2/proposal-workflow.mjs`
- `tests/test_v12_proposal_pdf.py`
- `docs/v12-pdf-proposal.md`

Requested PDF/PNG artifacts are under `output/pdf` and `output/playwright`; private snapshots/logs/backups
and generated/signed source PDFs remain under ignored `runtime/`. The rendering-only PyMuPDF package was
installed in the development virtual environment; the application uses ReportLab/pypdf.

## Preservation and remaining boundaries

Approved V12 reference SHA-256 remains
`a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.
Generated approved UI and all baselined standalone Email Studio HTML/router/template bytes are unchanged.
The original ten clauses match the untouched dual-rate composer source checksum
`cb3f47308cb7dac56c48fef38be958a145e9db5faa96575226668767b4b56d40`.

Production SQLite V2 and Resume Processor rows/schema match their protected checkpoint backups;
all protected resume/document artifacts, checkpoint HEAD and retained stash remain unchanged.
Production PostgreSQL was not contacted or modified. No production migration, commit, push or deployment.

Remaining boundaries: manual email attachment/delivery; no cryptographic verification that an uploaded
PDF was genuinely signed; existing shared operator capability and declared-name attribution, rather than
individual staff authentication. Unsupported font glyphs are refused before saving rather than silently
omitted. No commercial clause was independently rewritten or interpreted as legal advice.

Implementation stops here for review of the isolated PDF workflow.
