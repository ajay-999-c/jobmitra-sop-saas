# Explicit Office LAN access

Office LAN mode authorizes the office network rather than an individual login.
It is disabled by default. When enabled, approved clients can use all existing
V12 workflows, including supervisor reactivation, without passwords, capability
tokens, unlock controls or actor-name authentication prompts. Normal business
confirmations, dates, reasons and document approvals still apply.

## Verify and configure the office network

On 24 November 2026 the Mac interface was `192.168.1.25`, mask `255.255.255.0`,
gateway `192.168.1.1`, confirming `192.168.1.0/24`. The configured PostgreSQL host
remains `192.168.1.51`; a database address alone is not proof of the client subnet.
Confirm the Windows server/client subnet with `ipconfig` before activation.
DHCP client address changes within the verified subnet do not require policy changes.

Add these exact supported values to the private environment actually used by the
Windows service (`.env`, its explicitly loaded `.env.v12.postgres`, or its NSSM
environment). Retain the existing PostgreSQL backend/schema/credentials and private
document roots. Never copy credentials into Git or reports.

```dotenv
JOBMITRA_LOCAL_V12=0
JOBMITRA_ATS_V2_ENABLED=true
JOBMITRA_UNIFIED_V12_ENABLED=true
JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=false
JOBMITRA_OFFICE_LAN_ENABLED=true
JOBMITRA_OFFICE_LAN_CIDRS=192.168.1.0/24,127.0.0.1/32,::1/128
JOBMITRA_OFFICE_LAN_HOSTS=
```

The loopback entries permit local health checks; remove them if local access must
also be denied. Additional verified private subnets are comma-separated CIDRs.
Empty, malformed, noncanonical and public ranges fail startup. Private ranges
must fall within RFC1918 IPv4, IPv6 ULA or explicit loopback networks. No private
network is implicitly trusted. Office mode and loopback direct-editing mode are
mutually exclusive. Office mode requires both ATS V2 and Unified V12.

IP Host headers must belong to the same allowlist. For an existing internal DNS
name, explicitly configure it, for example `JOBMITRA_OFFICE_LAN_HOSTS=jobmitra.office`.
Use only verified internal names. Arbitrary Host headers and DNS-rebinding names
are rejected. Exact DNS allowlisting does not bypass client subnet verification.

The examples remain disabled by default. Do not treat
`JOBMITRA_V12_POSTGRES_TRUSTED_LAN` as an application access setting: that separate
flag controls database transport validation and does not enable Office LAN mode.
PostgreSQL authentication remains required.

## Windows CMD and NSSM

With the settings in the checkout-root `.env`, the existing command works:

```cmd
python -m uvicorn jobmitra.main:app --app-dir src --host 0.0.0.0 --port 8002 --workers 1 --no-access-log
```

If using the separate private file:

```cmd
uv run --env-file .env.v12.postgres --no-sync python -m uvicorn jobmitra.main:app --app-dir src --host 0.0.0.0 --port 8002 --workers 1 --no-access-log
```

Clear conflicting inherited variables as described in the Windows runbook. For
NSSM, keep Application pointing at the existing virtual environment's Python and
AppDirectory at the checkout root. Use these AppParameters if loading the separate
file through Uvicorn rather than the service environment:

```text
-m uvicorn jobmitra.main:app --app-dir src --host 0.0.0.0 --port 8002 --workers 1 --no-access-log --env-file C:/Users/PC/Documents/jobmitra-saas/jobmitra-sop-saas/.env.v12.postgres
```

NSSM/system process environment overrides dotenv values, so review old
`JOBMITRA_LOCAL_V12`, direct-editing and office-mode overrides. Load the reviewed
code and settings with a separately approved service restart. No NSSM setting,
service restart, firewall rule or live private environment is changed by this task.

Use direct office connections, not a reverse proxy or public forwarding/NAT.
The middleware rejects `Forwarded`, all `X-Forwarded-*` and common proxy client-IP
headers, even when Uvicorn has already rewritten its ASGI client address. The
exact command above remains supported; adding `--no-proxy-headers` is an optional
extra hardening measure for a direct-only service. Do not publish the port on the
internet or place an untrusted proxy in an allowed subnet.

Open `http://<verified-Windows-office-IP>:8002/`. All three V12 pages, document
routes, Email Studio, legacy APIs, static resources and health endpoints share the
same subnet boundary. `/api/v12/access` reports `office_lan=true`, `editing=true`
and an explicitly unverified shared office actor. It issues no login cookie.

## Safeguards and audit semantics

The network middleware verifies each request before any route runs. The existing
same-origin checks, input validation, stale updates, idempotency, eligibility,
ownership, transactions, document SHA verification and private filesystem handling
remain active. Unsupported networks cannot fall back to password authentication
while Office mode is enabled. Turning Office mode off preserves the existing
operator/supervisor deployment mode; loopback direct editing remains separate.

Audit records normally identify the authorization role as `OFFICE_LAN` and the
default actor as `Office LAN user (shared access; individual identity unverified)`.
No staff identity is fabricated. Existing immutable SQLite/PostgreSQL reactivation
guards require the legacy `SUPERVISOR_TOKEN` database capability tag. Office
reactivation maps its approved supervisor authority to that tag and atomically
appends `OFFICE_LAN_SUPERVISOR_AUTHORIZED` evidence identifying the actual office
policy, unverified individual identity, declared actor and request key. This
distinguishes the policy from an actual token login without changing a trigger or
schema. Retry/stale/reason/date and confirmed-joining requirements remain enforced.

Plain office HTTP may lack `crypto.randomUUID` and SubtleCrypto. Shared browser
helpers retain UUID v4 generation using `crypto.getRandomValues` and exact SHA-256
verification using a tested fallback. Cryptographic randomness and checksums are
never skipped. Email Studio templates, original approved HTML, PDF content and
workspace layouts remain unchanged.

## Validation and activation gate

Focused tests use synthetic temporary SQLite databases and disposable PostgreSQL
schemas only. They cover candidate/company/JD CRUD and read-back, original/altered
resumes, parsed approval, proposal/signed copies, selection/joining/reactivation,
protected-mode operator/supervisor checks, invalid networks, outside peers,
forwarded spoofing after Uvicorn rewriting, Host checks and rollback/idempotency.
Browser checks use a synthetic loopback HTTP Office-mode preview with unavailable
secure-context crypto APIs simulated, not existing records. Native Windows LAN
browser/NTFS validation remains pending.
Live PostgreSQL verification is read-only. No existing candidate/company records,
production settings, schemas or databases are migrated or changed.

Before enabling on Windows, confirm the deployed revision, subnet, service settings,
native document roots/ACLs and a second office client's access. Confirm an outside
client cannot reach pages/APIs and that health/access responses match the mode.
No commit or push is made until review.

## Focused results for this implementation

- 62 focused SQLite/access/startup cases passed, including all-network boundary,
  forwarded spoofing after Uvicorn rewriting, required configuration, missing-store
  rejection, normal protected operator/supervisor operation and Office workflows.
- 10 focused PostgreSQL cases passed in the disposable private-socket restore,
  including no-token Office workflows and reactivation without modifying triggers.
- One JavaScript crypto test passed: eight SHA-256 vectors/byte sequences through
  10 MB against Node's digest, 1,000 UUID v4 values, and fail-closed missing randomness.
- Browser verification passed with both secure-context crypto APIs unavailable:
  company create/read-back, candidate registration with an original PDF,
  candidate edit/read-back, altered upload/download with exact SHA, zero attempted
  authentication prompts and zero console errors/warnings. Unlock Editing was hidden.
- Read-only verification of the actual PostgreSQL server confirmed unchanged public
  rows, sealed rows/metadata, DDL/ownership/ACLs and freeze guards. Original SQLite
  files, approved HTML and all 15 available original document hashes matched.
- Ruff, Python/JavaScript syntax, Git whitespace and generated-artifact consistency
  passed. The full regression suite was not run. No native Windows result is claimed.

Files changed for Office LAN implementation:

```text
.env.example
.env.v12.postgres.example
src/jobmitra/core/config.py
src/jobmitra/core/office_lan.py
src/jobmitra/main.py
src/jobmitra/modules/ats_v2/unified_access.py
src/jobmitra/modules/ats_v2/unified_router.py
src/jobmitra/modules/ats_v2/unified.py
src/jobmitra/static/ats_v2/approved-api.mjs
src/jobmitra/static/ats_v2/candidate-desk.mjs
src/jobmitra/static/ats_v2/parsed-resume.mjs
src/jobmitra/static/ats_v2/proposal-workflow.mjs
src/jobmitra/static/ats_v2/shared.mjs
src/jobmitra/static/ats_v2/unified.mjs
src/jobmitra/static/ats_v2/crypto.mjs
tests/test_v12_office_lan.py
tests/test_v12_postgres_backend.py
tests/test_office_crypto.test.mjs
docs/v12-office-lan.md
docs/v12-windows-postgresql-validation.md
```

The release also includes the `.gitignore` exception and PostgreSQL ENV/runbook
setup. Private configuration, databases, documents, backups and runtime evidence
remain excluded. Unrelated historical reference files are preserved and excluded
from this release. Committing source does not enable Office mode or change NSSM.
