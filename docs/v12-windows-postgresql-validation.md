# Windows CMD update and PostgreSQL development validation

This uses `jobmitra_dev.jobmitra_v12_dev_20261123_integration` on the approved
private office server. It contains development/test records. No production
cutover, provisioning, SQLite migration, NSSM restart or firewall change is needed.
Native Windows access was unavailable from the Mac; the steps below must be run
on Windows and their results reviewed before declaring Windows readiness.

## 1. Inspect and update the existing checkout

In Windows **CMD**, inspect first:

```cmd
cd /d C:\Users\PC\Documents\jobmitra-saas\jobmitra-sop-saas
git status --short
git branch --show-current
git remote get-url origin
```

Stop if there are tracked modifications, staged changes or unexpected untracked
files. Preserve them; do not reset, clean, overwrite or automatically stash them.
The branch must be `feature/unified-workspace-v12` and origin must be
`ajay-999-c/jobmitra-sop-saas`. Only after those checks pass:

```cmd
git fetch origin
git pull --ff-only origin feature/unified-workspace-v12
git rev-parse HEAD
git rev-parse origin/feature/unified-workspace-v12
git status -sb
uv sync --locked
uv run --no-sync python -c "import fastapi,uvicorn,sqlalchemy,psycopg,reportlab,pypdf; from io import BytesIO; from reportlab.pdfgen.canvas import Canvas; b=BytesIO(); c=Canvas(b); c.drawString(30,750,'Development dependency check'); c.save(); assert len(pypdf.PdfReader(BytesIO(b.getvalue())).pages)==1; print('Dependencies, PostgreSQL driver and in-memory PDF processing OK')"
```

Both hashes must match the pushed release hash reported with this runbook.
A divergent branch must be inspected rather than forced. Dependency resolution
uses the committed lockfile; no unrelated upgrade is required.

## 2. Inspect existing storage without changing it

Do not assume `D:` exists. This prints only configured document roots, not database
credentials. Also inspect the proposed external location read-only:

```cmd
uv run --no-sync python -c "from jobmitra.core.config import Settings; s=Settings(); print('Resume root:',s.ats_v2_resume_storage_root); print('Proposal root:',s.unified_v12_proposal_storage_root); print('Legacy document root:',s.document_storage_root)"
if exist "D:\JobmitraData\resumes" dir /a "D:\JobmitraData\resumes"
if exist "D:\JobmitraData\resumes\original" dir /a "D:\JobmitraData\resumes\original"
if exist "D:\JobmitraData\resumes\altered" dir /a "D:\JobmitraData\resumes\altered"
if exist "D:\JobmitraData\resumes\parsed" dir /a "D:\JobmitraData\resumes\parsed"
if exist "D:\JobmitraData\resumes" icacls "D:\JobmitraData\resumes"
```

Do not change existing/global ACLs. The application creates private new leaves
and rejects unsafe existing permissions, junctions/reparse points and hard links.
Before setting the PostgreSQL profile below, run the focused storage tests in this
fresh CMD window. They use synthetic temporary fixtures, not the configured server:

```cmd
set "JOBMITRA_LOCAL_V12=0"
set "JOBMITRA_V12_BACKEND=sqlite"
set "JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=false"
uv run --no-sync pytest tests/test_v12_proposal_storage.py tests/test_v12_resume_storage.py tests/test_v12_parsed_documents.py -q
```

Stop if native ACL/reparse/atomic-write checks fail. Do not repair production
permissions or weaken security to pass them. The next section selects PostgreSQL
and restores loopback development editing for the application.

## 3. Select the isolated profile in this CMD window only

For the separately configured password-free office network policy, see
[Office LAN mode](v12-office-lan.md). It requires an explicit verified CIDR list
and `JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=false`; the loopback examples below
continue to use the original local-only policy.

### Preferred: a separate private environment file

From the project root in an interactive Windows CMD prompt:

```cmd
if not exist .env.v12.postgres copy .env.v12.postgres.example .env.v12.postgres
notepad .env.v12.postgres
```

Fill the existing private database username/password, keep credentials quoted,
and save/close the editor. The absolute storage paths assume the checkout shown
above; adjust them if needed, keeping all roots inside its `runtime` directory.
Parsed storage shares the resume root; no additional parsed-root variable exists.

Clear old process overrides so `uv` loads the selected profile consistently. These
commands clear only the current CMD environment and do not change `.env`, system
settings or services. Use single `%V` interactively; a `.bat` file needs `%%V`.

```cmd
for /f "tokens=1 delims==" %V in ('set JOBMITRA_ 2^>nul') do @set "%V="
for /f "tokens=1 delims==" %V in ('set UVICORN_ 2^>nul') do @set "%V="
set "UV_NO_ENV_FILE="
set "UV_ENV_FILE="
uv run --env-file .env.v12.postgres --no-sync python -c "from jobmitra.core.config import get_settings; from jobmitra.modules.ats_v2.postgres import validate_configuration; from jobmitra.core.local_v12 import validate_direct_editing; s=get_settings(); validate_configuration(s); validate_direct_editing(s); print('Backend:',s.v12_backend,'Development:',s.v12_postgres_development,'Schema:',s.v12_postgres_schema)"
uv run --env-file .env.v12.postgres --no-sync python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8002 --workers 1
```

The preflight must print `postgresql`, `True`, and
`jobmitra_v12_dev_20261123_integration`. It does not test passwords or write data.
Application startup subsequently authenticates and validates the existing schema.
`uv` puts file values into the process environment, which overrides corresponding
settings in the project's legacy `.env`; that file need not be modified. Unspecified
optional settings can still come from `.env`. There is no SQLite fallback.
Never use a production/LAN bind with this development profile.

In another CMD window after startup:

```cmd
curl --fail http://127.0.0.1:8002/health/ready
curl --fail http://127.0.0.1:8002/api/ats-v2/health
```

Readiness must succeed and the ATS response must report `storage=postgresql`.
The preflight above confirms the schema without exposing credentials. Then open
`http://127.0.0.1:8002/`. Git ignores `.env.v12.postgres`; only the placeholder
example can be tracked. Git pull does not transfer private documents.

### Alternative: set individual process variables

Reuse the existing private database username/password configuration. Never paste
passwords into commands, Git, screenshots or terminal results. These are the exact
supported settings; they do not rewrite `.env` or Windows services:

```cmd
set "JOBMITRA_LOCAL_V12=0"
set "JOBMITRA_V12_BACKEND=postgresql"
set "JOBMITRA_V12_POSTGRES_DEVELOPMENT=true"
set "JOBMITRA_V12_POSTGRES_SCHEMA=jobmitra_v12_dev_20261123_integration"
set "JOBMITRA_DB_HOST=192.168.1.51"
set "JOBMITRA_DB_PORT=5432"
set "JOBMITRA_DB_NAME=jobmitra_dev"
set "JOBMITRA_DB_SSLMODE=disable"
set "JOBMITRA_V12_POSTGRES_TRUSTED_LAN=true"
set "JOBMITRA_ATS_V2_ENABLED=true"
set "JOBMITRA_UNIFIED_V12_ENABLED=true"
set "JOBMITRA_UNIFIED_V12_PROPOSALS_ENABLED=true"
set "JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=true"
set "JOBMITRA_RESUME_PROCESSING_ENABLED=false"
set "JOBMITRA_AI_ENABLED=false"
set "JOBMITRA_V12_DEV_FILES=%CD%\runtime\v12-pg-dev"
set "JOBMITRA_ATS_V2_RESUME_STORAGE_ROOT=%JOBMITRA_V12_DEV_FILES%\resumes"
set "JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT=%JOBMITRA_V12_DEV_FILES%\proposals"
set "JOBMITRA_DOCUMENT_STORAGE_ROOT=%JOBMITRA_V12_DEV_FILES%\legacy-documents"
```

The server currently has no TLS. The explicit exception above applies only on the
previously confirmed trusted private office LAN. Elsewhere use certificate-verified
TLS or an approved encrypted tunnel. PostgreSQL failures do not fall back to SQLite.
The schema already exists; do not run either PostgreSQL provisioning or staging
import scripts as part of startup.

The default roots above isolate development files under this checkout's runtime
directory. Direct editing requires those isolated roots and direct loopback access.
If inspection verifies an external NTFS root such as `D:\JobmitraData\resumes`,
use a dedicated development subdirectory there only with
`JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=false` and the existing operator
capability configuration. External roots are configurable, but do not bypass the
current direct-editing isolation restriction or point development at production
document storage. Choose the actual root after the Windows inspection.

New writes under the selected resume root use:

```text
resumes/
  original/candidate_<canonical ID>/<immutable UUID>.pdf or .docx
  altered/candidate_<canonical ID>/<immutable UUID>.pdf, .docx or .html
  parsed/candidate_<canonical ID>/<immutable UUID>.json
```

Parsed PDF workflows reference their immutable source PDF in `altered/` and store
the extraction JSON in `parsed/`; they do not duplicate the source PDF. Exact raw
JSON remains in PostgreSQL as well. New JSON downloads verify the stored file's
SHA/size and agreement with the database artifact. Approved versions reference
their original draft rather than duplicating bytes. Existing metadata-only JSON
and historical `<candidate ID>/<kind>/...` paths remain supported without relocation.

## 4. Transfer the verified historical files outside Git

The protected Mac checkpoint has 15 available files: ten resume files, four
proposal PDFs and one received signed-copy fixture. Seven unresolved references
and three JSON/text-only records are retained. Git transfers source code, not
these private files or the SQLite databases.

Use an approved private transfer channel. Transfer only the verified source trees
and the private `final-staging-verification.json` and
`private-document-manifest.json` to protected Windows locations outside the repo.
Preserve manifest-relative keys exactly, including older layouts. Do not rewrite
the manifest or PostgreSQL paths to make them resemble the new upload layout.
Choose disjoint source and development destination roots, then set these private
local paths to their actual inspected locations:

```cmd
set /p "JOBMITRA_TRANSFER_PROOF=Full path to private final-staging-verification.json: "
set /p "JOBMITRA_TRANSFER_MANIFEST=Full path to private private-document-manifest.json: "
set /p "JOBMITRA_TRANSFER_RESUMES=Full path to verified transferred source resume root: "
set /p "JOBMITRA_TRANSFER_PROPOSALS=Full path to verified transferred source proposal root: "
set /p "JOBMITRA_TRANSFER_REPORT=Full path to a new private output report: "
uv run --no-sync python scripts/copy_v12_dev_documents.py --source-proof "%JOBMITRA_TRANSFER_PROOF%" --document-manifest "%JOBMITRA_TRANSFER_MANIFEST%" --source-resume-root "%JOBMITRA_TRANSFER_RESUMES%" --source-proposal-root "%JOBMITRA_TRANSFER_PROPOSALS%" --report "%JOBMITRA_TRANSFER_REPORT%"
```

The tool validates the manifest hash, live canonical IDs and document metadata,
source SHA/size, exclusive publication and destination SHA/size. Existing identical
files are skipped; conflicts fail without replacement. Expect 15 copied on the
first clean destination, or copied plus identical skips totaling 15. Missing
historical references must remain seven; metadata-only count is three.

The development copy also contains separately labelled application-verification
fixtures created after that snapshot. Their documents are not part of the
15-file historical manifest. Transfer those separately with verified identities
and checksums only if their old fixture downloads are needed, or test with new
Windows development fixtures. Do not fabricate replacements or alter their rows.

## 5. Focused native Windows checks and startup

```cmd
uv run --no-sync python -m uvicorn jobmitra.main:app --app-dir src --host 127.0.0.1 --port 8002 --workers 1
```

In a second CMD window:

```cmd
curl --fail http://127.0.0.1:8002/health/ready
curl --fail http://127.0.0.1:8002/api/ats-v2/health
```

Confirm `storage=postgresql`. Open:

- `http://127.0.0.1:8002/` — redirects to the approved Companies workspace.
- `http://127.0.0.1:8002/workspace-v12/companies`
- `http://127.0.0.1:8002/workspace-v12/candidates`
- `http://127.0.0.1:8002/workspace-v12/jobs`

Verify logo visibility, left-aligned desktop tabs, unchanged active styling,
mobile wrapping, refresh, back/forward and no browser console/API errors.
Use clearly labelled development records for these checks:

| Workflow | Native evidence required |
| --- | --- |
| Companies | Directory, contact IDs, edit/save API read-back and audit history |
| Proposals | Generate approved PDF, history/version replay, signed-copy upload/download with exact SHA/bytes |
| Candidates | Dashboard/search/directory filters, registration, edit/save read-back and duplicate/stale rejection |
| Resumes | New original/altered PDF and DOCX, canonical versions, relative folders and exact download SHA |
| Parsed documents | Altered PDF extraction, raw JSON including original whitespace/BOM, selective approval, physical JSON/hash and file/DB agreement |
| JD Tracking | Create/edit, candidate attachment, rounds, feedback, selection and confirmed joining |
| History/eligibility | One event per retry, preserved history and joined candidate allocation blocked |
| Protected data | Read-only protected-schema fingerprints match the private preflight proof; original SQLite hashes unchanged |

Do not send test emails. Report native failures with secrets and candidate/client
details removed. Record the Windows commit hash, storage test summary, health
responses, actual storage roots and workflow read-back results. Production rollout
remains blocked until these native results and document transfers are verified.

## Rollback

Stop only this manually started development process with Ctrl+C. Close the CMD
window to clear process-only settings. Keep the development schema and private
files as evidence. Returning to SQLite requires that machine's existing verified
isolated V3 copy; never create an empty database or migrate production to roll back.
