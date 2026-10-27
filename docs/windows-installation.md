# Jobmitra — Windows installation

This guide runs the existing FastAPI website on **Windows**, using PowerShell.
The existing PostgreSQL server is `192.168.1.51:5432`, database `jobmitra_dev`,
application role `jobmitra_app`. All modules use one website on port 8000.

This code requires Alembic revision `0007_candidate_resumes`; the last read-only
Windows inspection reported `0005_jd_general_skills`. Recheck before deployment.
Installing another backend does not require recreating its tables, importing Excel
data or seeding DEMO records. Check the actual revision before proceeding.

These instructions were checked against the repository; native Windows execution
has not been tested as part of writing this guide. For the existing Mac-backend /
Windows-database arrangement, use the [README](../README.md) instead.

## 1. Prerequisites

- Install 64-bit Python 3.12 from [Python for Windows](https://www.python.org/downloads/windows/).
  The project requires Python 3.12 or newer; commands below use 3.12 explicitly.
- Install [Git for Windows](https://git-scm.com/downloads/win) if using Git to obtain the project.
- Use PostgreSQL 18 and its command-line tools. The
  [official Windows installer page](https://www.postgresql.org/download/windows/)
  links to an installer that includes the server and pgAdmin.
  **Skip server installation when using the already-configured Windows database.**
- No Docker, Redis, Celery, Node.js or external AI service is needed to run Jobmitra.

Check Python and Git in a new PowerShell window:

```powershell
py -3.12 --version
git --version
```

## 2. Obtain the project and install dependencies

Copy the project source to `C:\Jobmitra\sop-pipeline`, or clone your actual approved
repository URL there. Do not copy the Mac `.venv` directory: create a Windows
environment. Credentials, backups, runtime manifests and resumes are not supplied
by a Git clone.

```powershell
Set-Location C:\Jobmitra\sop-pipeline
py -3.12 -m pip install --user uv
py -3.12 -m uv sync --frozen --extra dev --python 3.12
```

`uv sync --frozen` uses the committed `uv.lock` without updating it. If `uv` is
unavailable, this alternative installs compatible dependency versions from
`pyproject.toml`, rather than the exact lockfile versions:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Use the virtual environment's executables directly. Activation and changes to
PowerShell execution policy are unnecessary. The optional Excel dependency is not
needed for normal operation; installation does not authorize an import.

## 3. Configure the environment privately

Copy the template only if `.env` does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Edit these values in Notepad. Replace the password placeholder locally, keeping the
password quoted if it contains spaces or `#`. Do not paste a real password into a
command, chat, screenshot or Git commit.

```dotenv
JOBMITRA_DB_HOST=192.168.1.51
JOBMITRA_DB_PORT=5432
JOBMITRA_DB_NAME=jobmitra_dev
JOBMITRA_DB_USER=jobmitra_app
JOBMITRA_DB_PASSWORD='REPLACE_LOCALLY'
JOBMITRA_DB_SSLMODE=prefer
JOBMITRA_DB_CONNECT_TIMEOUT=5
JOBMITRA_DB_POOL_SIZE=3
JOBMITRA_DB_MAX_OVERFLOW=0
JOBMITRA_DB_POOL_TIMEOUT=5
JOBMITRA_DB_STATEMENT_TIMEOUT_MS=5000
JOBMITRA_OFFICE_TIMEZONE=Asia/Kolkata
JOBMITRA_AI_ENABLED=false
JOBMITRA_DOCUMENT_STORAGE_ROOT=D:/JobmitraData/private-documents
JOBMITRA_DOCUMENT_MAX_BYTES=12582912
```

When FastAPI runs on the **same Windows PC as PostgreSQL**, use `127.0.0.1` for
`JOBMITRA_DB_HOST`. From another PC, retain the database server's reachable LAN
address. Do not use the database name as the login name.

Run commands from the project root: `.env` is resolved relative to the working
directory. Shell environment variables take precedence. To inspect override
**names only**, without exposing their values:

```powershell
Get-ChildItem Env:JOBMITRA_* | Select-Object -ExpandProperty Name
```

Restart FastAPI after changing settings; settings are cached within each process.

## 4. Prepare private resume storage

Use a persistent local NTFS directory outside the repository, public static folders,
OneDrive and temporary directories. The application publishes files through
`os.link`; the filesystem must support hard links. Python supports this operation
on Windows. See [Python's filesystem documentation](https://docs.python.org/3/library/os.html#os.link).

For a **new directory**, run the following as the Windows account that will run
FastAPI. If directory creation is denied, have an administrator create it and grant
that account access; do not routinely run the backend as administrator.

```powershell
$jobmitraAccount = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$jobmitraStorage = 'D:\JobmitraData\private-documents'
New-Item -ItemType Directory -Path $jobmitraStorage -Force | Out-Null
icacls $jobmitraStorage /grant:r "${jobmitraAccount}:(OI)(CI)M" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"
icacls $jobmitraStorage /inheritance:r
icacls $jobmitraStorage

icacls .env /grant:r "${jobmitraAccount}:F" "*S-1-5-18:F" "*S-1-5-32-544:F"
icacls .env /inheritance:r
icacls .env
```

Check every command for success. These grants retain the runtime account, SYSTEM
and local Administrators. Review any other **explicit** permissions on a reused
directory or file: disabling inheritance does not remove existing explicit grants.
If a service account will run FastAPI, grant that specific account access instead.
Windows ACLs provide privacy here; Unix `chmod 0600/0700` checks are not a substitute.
See [Microsoft's `icacls` reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).

### Moving the existing backend from Mac

Existing resume bytes are stored at
`/Users/mac/Documents/jobmitra/private-documents` on the Mac; PostgreSQL stores
their metadata, IDs and parsed JSON. **Pointing Windows at an empty directory will
not make those resumes available.**

Before switching the backend:

1. Coordinate a maintenance window and stop uploads/edits on the old backend.
2. Back up both PostgreSQL and the complete private document directory.
3. Securely copy the private files to the Windows directory, preserving every opaque
   storage filename and file byte. Do not rename files to candidate names.
4. Verify file counts and SHA-256 values against `candidate_documents` metadata;
   apply and verify the Windows folder/file ACLs.
5. Start the Windows backend and verify existing original/modified-version downloads.

Do not rewrite candidate/document IDs or re-upload existing files to reconstruct
their links. Do not operate two backends with separate, unsynchronized storage
directories against the same database. Keep the original Mac files and backups
until the migration has been reviewed and accepted.

## 5. Check PostgreSQL and the schema

The application login must already have the required table permissions. Reuse the
existing database and role; do not run role-creation or migration helper scripts as
part of ordinary installation.

The following commands are read-only. Adjust the PostgreSQL tools path or host if
needed. `-W` prompts for the password without putting it in shell history.

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\psql.exe' -h 192.168.1.51 -p 5432 -U jobmitra_app -d jobmitra_dev -W -c 'SELECT version_num FROM public.alembic_version;'
.\.venv\Scripts\jobmitra-db.exe health
.\.venv\Scripts\jobmitra-db.exe benchmark --iterations 100
.\.venv\Scripts\alembic.exe heads
.\.venv\Scripts\alembic.exe history
```

For this version, expect `0007_candidate_resumes`. Pending `0006_jd_catalog_links`
adds nullable JD catalog links; `0007_candidate_resumes` creates resume metadata.
Neither is automatically applied by installing or starting the application. `heads` and `history`
inspect local migration source, not the applied database revision. Use the SQL
query above for the actual database revision.

If the database is empty, the version table is missing, or its revision differs,
stop and prepare a separately approved initialization/upgrade plan. A fresh server
needs its database/login provisioned, migration SQL reviewed and the approved
revision applied before business pages work. Do not run `upgrade head` blindly on
the existing database. See the [migration review](windows-stage2-stage3-readiness.md)
and [reviewed SQL](../outputs/windows-migration/0002-to-0004-reviewed.sql).
pgvector is not required by the currently implemented modules.

## 6. Start the unified website

```powershell
Set-Location C:\Jobmitra\sop-pipeline
.\.venv\Scripts\python.exe -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Leave this PowerShell window running. Open:

- <http://127.0.0.1:8000/> — overview and shared navigation.
- <http://127.0.0.1:8000/companies> — Company Directory.
- <http://127.0.0.1:8000/requirements> — JD Tracking.
- <http://127.0.0.1:8000/candidates> — Candidate Directory.
- <http://127.0.0.1:8000/docs> — API documentation.

Use `Ctrl+C` for a graceful stop. Start with one worker and no development reload;
each worker has its own database connection pool. This foreground command does not
install an automatically restarting Windows service.

In another PowerShell window, check liveness and database readiness:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Readiness should return HTTP 200. Review the existing directories and document
downloads before permitting normal edits. Tests that create synthetic records need
explicitly approved test data and a backup; do not use historical records as fixtures.

The loopback address is accessible only on the backend PC. Multi-device access,
firewall rules, TLS, access control and service installation are separate deployment
work. The current “Working as” selection is attribution, not verified login.

## 7. Windows-specific limitations and troubleshooting

| Symptom | Check |
| --- | --- |
| `py -3.12` is unavailable | Install Python 3.12 with its launcher, or consistently substitute your installed supported interpreter. |
| `ModuleNotFoundError: jobmitra` | Use `.venv\Scripts\python.exe` and install the project from its root. |
| Invalid `Asia/Kolkata` timezone | Check `.\.venv\Scripts\python.exe -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Kolkata'))"`. The lockfile includes the Windows `tzdata` dependency through psycopg; reinstall dependencies if missing. |
| HTTP 503 / database unavailable | Check settings, environment overrides and PostgreSQL service availability. Run `jobmitra-db health`; do not print raw driver exceptions or connection URLs. |
| Missing candidate/JD tables | Check the applied revision. Request migration review rather than creating tables from the application. |
| Upload fails or an existing download returns 404 | Check the configured absolute directory, account ACLs, hard-link support and whether the existing files were copied. No fallback directory is created. |
| Port 8000 is in use | Identify the existing application before stopping it. Use another approved port if necessary; all modules still run through the same FastAPI server. |

Windows commonly needs the `tzdata` package because it lacks the system IANA
timezone database; see [Python's timezone documentation](https://docs.python.org/3/library/zoneinfo.html#data-sources).

The existing `scripts/test_stage2_isolated.py` and `scripts/test_stage3_isolated.py`
use `/private/tmp`, Unix sockets and Mac-style interpreter/tool paths. They are not
native Windows test runners. `scripts/demo_acceptance.py` also imports Unix-only
`fcntl` and assumes the Mac storage path; its tests are therefore not native
Windows compatible either. Do not run these scripts, remove their safeguards or
point a full test suite at the shared database to work around that limitation.

Keep database backups and private file backups together. Protect `.env`, resume
files, database dumps and runtime reports from Git and public folders. Installing
Jobmitra does not automatically configure backups, import company spreadsheets,
seed DEMO data, install authentication or call ChatGPT/Claude.


## Service configuration and current resume deployment

Use an editable checkout (`uv sync --frozen` or `pip install -e .`), retaining the root HTML
resources. The application loads the checkout-root `.env` using an absolute path derived from
its configuration module, even if NSSM starts it with a different working directory.
Process environment variables still override `.env`; restart the service after intentional
configuration changes. Never copy the Mac `.env` over an existing Windows `.env`.

Set NSSM Application to the checkout's `.venv\Scripts\python.exe`, AppDirectory to the
checkout root, and AppParameters to `-m uvicorn jobmitra.main:app --host 0.0.0.0 --port 8000`.
These are configuration examples, not changes performed by this release.

Retain `JOBMITRA_DOCUMENT_STORAGE_ROOT` from the existing Windows `.env` unchanged.
An example is `D:/JobmitraData/private-documents`. Absolute native Windows drive paths,
backslashes, spaces and UNC paths are supported by pathlib. Relative paths are rejected
explicitly, so a service cannot silently write into its working directory. Create the exact
configured directory only as a deliberate provisioning step and grant the service account
read/write access. UNC shares also need share permissions and a suitable service identity;
LocalSystem access to a network share is not guaranteed. No fallback directory is created.

`JOBMITRA_DOCUMENT_MAX_BYTES` controls legacy documents; `JOBMITRA_RESUME_MAX_BYTES`
controls optional originals (default 10485760 bytes). Uploads validate file type/signature/size,
use random immutable filenames and store only keys in PostgreSQL. Bounded request buffering
uses the OS temporary directory; validated files are published in the configured private root.
There is no automatic resume parser or processed-output directory in this phase. Original,
modified and manually supplied parsed-JSON workflows remain separate.

Before deploying migrations, make and verify a database backup and a matching private-file
backup. Review 0006 and 0007 together. Applying migration source from Git requires separate
approval; do not use `stamp` to bypass missing tables. See
[optional resume deployment notes](optional-resume-upload.md) and the
[reviewed 0007 SQL](../outputs/optional-resumes/0006-to-0007-reviewed.sql).

Native Windows/NSSM execution and service-account permissions must still be verified on
Windows. Mac tests cover Windows path semantics with test doubles, native temporary paths
with spaces, changed working directories, missing directories and simulated denied access.
The prototype intentionally has no authentication; add application-wide access controls
before production deployment.


Release verification on macOS: 185 focused tests passed across foundation/configuration,
Windows path test doubles, candidate registration/resumes, JD catalog/migrations,
Foundit workflows, Email Studio and preflight helpers. PostgreSQL tests used a disposable
Unix-socket cluster with TCP disabled and temporary private files; no Windows data was
modified. Ruff, JavaScript syntax and staged whitespace checks passed. The existing
Starlette/httpx TestClient deprecation warning is unrelated to this release.
