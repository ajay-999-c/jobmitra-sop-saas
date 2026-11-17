# Resume Processing demo

The new `/resume-processing` workspace is integrated into `jobmitra.main:app` and the shared Jobmitra navigation. It operates independently of Candidate Desk and PostgreSQL. It is disabled until the processor paths are configured.

## Connection to the existing processor

The local source is `../jobmitra-resume-processing`, whose origin is `https://github.com/ajay-999-c/jobmitra-resume-preprocessing.git`. No clone was necessary, no nested repository was added, and no source changes were made in that repository.

SOP stores registration/link metadata in the existing SQLite `candidates`, `resumes` and `resume_parses` tables. It opens the configured existing database with SQLite `mode=rw`; a missing database or unsupported schema produces a setup error instead of creating or migrating a database. No PostgreSQL models, data, migrations or synchronization are involved.

`src/jobmitra/modules/resume_processing/bridge.py` runs in the processor's separate Python environment. The web process does not import Docling, GLiNER, Torch or LangChain. It reuses:

- `app.services.extraction.make_converter/extract_markdown`: CPU Docling, OCR disabled, existing scanned-document checks.
- `app.services.pii_pipeline.load_gliner/sanitize_resume`: existing GLiNER/Regex masking and identity detection.
- `app.core.batch`: SHA-256, atomic file writing, input privacy gates and the existing cross-process command lock.
- `run_llm.preflight`, `groq_quota_wait`, `retry_delay`, `temporary_error`, `persist_json`: eligibility/integrity checks, quota pacing, bounded retries and immutable file publication.
- `app.services.llm_parser.make_chain/parse_resume/parser_signature`: Groq `openai/gpt-oss-120b`, reasoning `medium`, temperature `0`, strict JSON Schema and unchanged V3 prompt/ResumeProfile. Only sanitized text is sent to the chain; identity mappings remain local.
- `app.services.alter_resume.load_resume_for_export` and `generate_alter_resume.generate`: local candidate-name restoration, professional output screening, approved ATS V2 mapping, HTML preview, selectable-text PDF and editable DOCX renderers.

The old Groq batch CLI remains a paired pilot. The new bridge dispatches exactly the requested uploaded document and records its version/canonical pointers directly; it never calls that batch selection function or processes unrelated candidates.

A one-slot dispatcher returns promptly while its separate child process does the heavy work. The existing processor command lock also prevents simultaneous CLI/model work. Run one Uvicorn worker. A job has a 15-minute timeout; persisted abandoned claims become `FAILED / INTERRUPTED` after 16 minutes and need an explicit retry. They are never automatically replayed after a restart. Model SDK retries remain zero; transient errors have at most one bridge retry, 429 is deferred, and schema/privacy/output-token failures are not retried automatically. Provider account quotas and output-token budgets retain the processor configuration.

## Storage, identities and review

Original uploads are immutable hash-named files in the processor's `private/sop_uploads/`. Extracted Markdown, sanitized Markdown, parsed JSON and exports remain in that processor's existing private storage tree. All new private files receive restrictive POSIX permissions; use equivalent NTFS ACLs on Windows. Nothing is mounted as public static data.

A repeated upload of identical bytes for the same candidate reuses the document ID. Changed bytes create another preserved document version. An existing hash associated with another candidate is rejected. Matching names never merge candidates. Contact matches require selecting an existing candidate explicitly; conflicting email/mobile identity matches require local review. Existing candidate contacts are not overwritten. Name comparison/identity screening retains the processor's local checks.

A control row with `parser_signature='sop-control-v1'`, `llm_status='CONTROL'` and an empty artifact path stores authorization, stage, safe errors and export references in `resume_parses.metadata_json`. It contains no resume Markdown or professional JSON bodies and is excluded from completed parse selection. This uses the existing schema; there is no new table or column. Canonical professional parse versions have their own signatures and immutable JSON files.

`COMPLETED` parsing is not factual approval. The employee reviews the professional-data preview against the original, then approves the exact parse ID and JSON SHA-256. Approval metadata records `local-demo-unverified`, the time and reviewed hash; local demo actions are not attributed to a verified employee. ATS generation requires that approval and rechecks source/parse integrity and privacy. Revoking approval or changing the canonical version disables previous downloads. Final files contain the local candidate name and validated professional information; personal contact details, DOB and residential addresses are excluded. Empty optional sections are hidden by the existing template. Rejected data cannot be edited in this demo UI; correct/review it using the processor's existing versioned workflow rather than modifying an approved JSON file in place.

## Authentication and PostgreSQL availability

The current localhost demo opens without a username or password, as requested. Every page/API/download route requires a loopback client and a `localhost`, `127.0.0.1` or `::1` Host. Non-local access is rejected. Existing candidate consent, same-origin protection, privacy gates and explicit factual review remain required. Any local user can access this processor workspace; this mode does not verify employee identity. Bind Uvicorn to `127.0.0.1`. Configure proper employee authentication before a future shared/network deployment.

The shared page is rendered without a PostgreSQL session or staff query. Existing application startup only constructs the lazy SQLAlchemy engine; it does not connect. PostgreSQL can remain unavailable for this module. Existing DB settings still must be syntactically valid for application startup; do not remove or replace them. `/health/ready` continues to check PostgreSQL, while `/api/resume-processing/health` checks the SQLite component independently. Other modules retain their existing behavior.

## Windows setup (PowerShell)

Keep the SOP and processor checkouts as siblings. If the processor is absent:

```powershell
Set-Location D:\Jobmitra
# Uses your existing authorized GitHub credentials.
git clone https://github.com/ajay-999-c/jobmitra-resume-preprocessing.git jobmitra-resume-processing
```

Keep the existing environments/configuration. For a new SOP environment only:

```powershell
Set-Location D:\Jobmitra\sop-pipeline
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The processor's existing `gen_ai` environment was verified locally as Python 3.11 with Docling, GLiNER, LangChain Groq, python-docx and pypdf. No heavy dependencies were added to SOP. On Windows, use the processor's established environment and install its dependencies if missing:

```powershell
conda activate gen_ai
Set-Location D:\Jobmitra\jobmitra-resume-processing
python -m pip install -r requirements.txt
python --version
```

Install/use local Chrome or Chromium for the existing PDF fallback, or configure the processor's supported WeasyPrint/native dependencies. The current renderer already supports standard Windows Chrome paths. Docling and GLiNER model weights must be available in the local model cache; first-time model downloads require network access. Their Windows runtime/memory behavior still needs verification on the target i3 computer.

Add these values to the **existing SOP `.env`**, using actual absolute paths. Do not replace that file or alter its PostgreSQL/document-storage settings:

```ini
JOBMITRA_RESUME_PROCESSING_ENABLED=true
JOBMITRA_RESUME_PROCESSING_REPO=D:/Jobmitra/jobmitra-resume-processing
JOBMITRA_RESUME_PROCESSING_PYTHON=C:/Users/EMPLOYEE/miniconda3/envs/gen_ai/python.exe
JOBMITRA_RESUME_PROCESSING_DATABASE=D:/Jobmitra/jobmitra-resume-processing/private/jobmitra_candidates.sqlite3
JOBMITRA_RESUME_MAX_BYTES=10485760
```

Point at the existing processor database; no initialization command is required or provided by the adapter. Retain the processor's own `.env` and configure `GROQ_API_KEY` there. Existing `groq_api_key` / `grok_api_key` aliases remain supported. Do not put credentials in source files or command arguments. The bridge uses the approved model/reasoning/prompt and the shared limited-mask eligibility policy. Detected-name uncertainty/residuals, unmasked email/phone/personal URLs and artifact corruption block; registered-name differences, DOB and address findings are visible non-blocking warnings. Optional account quotas and `JOBMITRA_GROQ_MAX_OUTPUT_TOKENS` come from the processor configuration. A missing API key produces a safe configuration error when uncached parsing is requested.

On this Mac the equivalent paths are:

```text
Repository: /Users/mac/Documents/jobmitra/jobmitra-resume-processing
Python: /Users/mac/miniconda3/envs/gen_ai/bin/python
SQLite: /Users/mac/Documents/jobmitra/jobmitra-resume-processing/private/jobmitra_candidates.sqlite3
```

Launch from SOP with the preserved entrypoint:

```powershell
Set-Location D:\Jobmitra\sop-pipeline
.\.venv\Scripts\python.exe -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Do not run an existing incompatible process on the same port. `--no-access-log` also keeps document/candidate identifiers out of normal request logs. No Alembic or PostgreSQL recovery command is needed for this feature.

## Manual demo with one authorized resume

1. Configure the existing database/environment above; restart SOP once to load them.
2. Open `http://127.0.0.1:8000/resume-processing` or choose **Resume Processing** in the portal. The page opens directly without login on localhost.
3. Enter the candidate's full name. Add mobile, email and city if supplied. If using an existing local candidate, select it explicitly after checking identity. Choose a PDF/DOCX and confirm the candidate's processing/external-parsing authorization.
4. Click **Upload & Register**. It displays the hash-linked original and saved status. Click **Process Resume** once. No separate Python script is needed.
5. Observe uploaded → extraction → masking → Groq parsing. Refreshing the page retains status; recent resume selection restores previous uploads. A scanned PDF, unresolved detected name, required-masking failure, artifact corruption or invalid output stops safely. Name mismatches and DOB/address findings are displayed as warnings and do not stop parsing. Sanitized text may still contain DOB/address and may be sent to Groq; it is not fully anonymized.
6. At **Review Required**, open **View original resume** and check the professional preview. Confirm factual review, then click **Approve reviewed version**. Pydantic validity alone does not approve it.
7. Click **Generate ATS Resumes**. When completed, choose **Preview Resume**, **Download Jobmitra Branded PDF**, **Download Plain ATS PDF** or **Download Editable DOCX**.
8. Check identity, facts, optional sections and selectable PDF text before distributing any file. **Needs correction** revokes approval and blocks downloads.

## Offline tests

Set portable test paths, then run SOP's focused tests:

```powershell
$env:JOBMITRA_TEST_PROCESSOR_REPO='D:/Jobmitra/jobmitra-resume-processing'
$env:JOBMITRA_TEST_PROCESSOR_PYTHON='C:/Users/EMPLOYEE/miniconda3/envs/gen_ai/python.exe'
Set-Location D:\Jobmitra\sop-pipeline
.\.venv\Scripts\python.exe -m pytest -q tests/test_resume_processing.py
```

`tests/resume_processing_worker_checks.py` runs under that separate interpreter. It uses temporary synthetic SQLite databases/storage, mocked extraction/GLiNER and mocked strict Groq responses; HTTP is explicitly blocked at the model boundary. It exercises actual profile validation, persisted stages, hash/version reuse, privacy blocks, retry/defer/token errors, review and the real PDF/DOCX renderers. The HTTP composition test also runs the subprocess supervisor, approves an exact version, generates all formats, downloads them and proves approval revocation blocks access. No live Groq requests or real-resume processing are part of automated validation. Local PDF rendering must be available; missing processor test paths are reported as skips, not passes.

For all SOP regression files on Mac use the existing Stage 3 isolated runner in separate groups:

```bash
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests --ignore=tests/test_candidate_quick_entry.py --ignore=tests/test_candidate_search.py --ignore=tests/test_optional_resumes.py --ignore=tests/test_foundit_quick_entry.py
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests/test_candidate_search.py tests/test_foundit_quick_entry.py
.venv/bin/python scripts/test_stage3_isolated.py --pytest-args tests/test_candidate_quick_entry.py tests/test_optional_resumes.py
node --test tests/*.mjs
```

The existing standalone quick-entry/upload fixtures call `Base.metadata.drop_all()`, while shared-schema tests retain a session-scoped fixture; other tests commit records and expect an empty database later. Consequently a single combined invocation contaminates those fixtures and reports missing-table/count failures. The commands above isolate those existing test behaviors without editing them.

Verified on Mac: **241 + 14 + 28 = 283 Python tests passed; 16 opt-in tests skipped** across the three groups. This includes **13 new endpoint/composition tests**, one of which invokes **9 additional processor-environment checks**. All **16 existing JavaScript tests** passed. Ruff, JavaScript syntax and Git whitespace checks passed. The earlier Stage 2 full discovery also passed (201 passed, 98 guarded skips). No live Groq request was made.

The runners use disposable PostgreSQL 18 clusters on private Unix sockets with TCP disabled. They do not contact the recovering/existing PostgreSQL deployment. Native Windows test setup differs; do not run those Unix-only isolation scripts on Windows.

## Remaining verification

Browser automation was unavailable in this session, so interactive visual QA and mobile-device behavior need a manual check. The HTTP upload/review/generation/download sequence and document contents were tested offline. Real Docling/GLiNER runtime and live Groq access are intentionally not tested on candidate data; the steps above are the authorized manual acceptance path. This task does not enable the module in the user's live `.env`, deploy to Windows, commit or push changes.

## Limited-mask eligibility update — 5 November 2026

SOP and standalone preflight share `app.core.eligibility`. A registered/detected name difference records `candidate_name_mismatch` and preserves the manually registered identity and candidate link. The detected name is still masked and checked for residuals. Local-only identity evidence in `private/masking/` is bound to the extraction, sanitized text and masking-version hashes. Neither identity mapping is passed to the LLM; output screening checks both identities locally.

DOB/address and other already detected out-of-scope personal-detail labels produce privacy warnings. They do not mark masking as failed or block `READY_FOR_LLM`. The legacy `JOBMITRA_BLOCK_OUT_OF_SCOPE_PII` selector no longer turns these warnings into blockers. Sanitized input may contain DOB/address; it is **not fully anonymized**. Consent remains required, and the approved prompt, ResumeProfile/output screening and ATS restrictions on personal information remain unchanged.

`bridge.py ... reevaluate FULL_DOCUMENT_ID` performs only local re-evaluation. It reuses saved extraction and valid sanitization, skips completed versions entirely, preserves history and never dispatches Groq. If an old mismatch stopped before sanitized text was saved, it reuses extraction and invokes only the unchanged local masker to create that missing artifact. Successful re-evaluation records `READY_FOR_LLM`; repeating it performs no metadata writes. An employee must explicitly click **Process Resume** to request parsing.
