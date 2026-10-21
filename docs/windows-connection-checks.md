# Windows connection and Company Directory checks

As of 2026-10-20, the backend connects successfully and the Company Directory
visibly displays all 131 Windows companies. Readiness and all checked Stage 2 pages
return HTTP 200. The approved migration is applied at `0002_jd_tracking`; see the
[deployment record](stage-2-windows-deployment.md). The diagnostics below describe
the earlier connection failure and remain optional troubleshooting reference.

The saved application settings already target Windows PostgreSQL at
`192.168.1.51:5432`, database `jobmitra_dev`, login `jobmitra_app`. The password
is configured privately in the existing settings; it is not included here.

The real backend should run from Mac Terminal on port 8000:

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
.venv/bin/python -m uvicorn jobmitra.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/companies>. Port 8765 is the separate disposable
Stage 2 preview; its synthetic entries are not the Windows company list.

The existing `/companies` page selects company IDs and names from PostgreSQL and
embeds that lightweight list for client-side search. `/api/companies` returns
the same source. No import, migration or new table is needed to display existing
Company Management records. The separately approved Stage 2 migration is now
applied, and its pages load successfully.

## Historical diagnostic evidence — 2026-10-19

- The backend responds on port 8000, but `/health/ready`, `/api/companies` and
  `/companies` returned HTTP 503 during verification.
- A read-only preflight from both Codex and Mac Terminal reports `host_unreachable`
  (driver says No route to host), with no SQLSTATE. This is not an empty-list result.
- The Mac has a route/ARP entry for the Windows host. The user reports that `nc`
  succeeds in Terminal, while Python's preflight fails there.
- The user reports that Python's macOS Local Network permission is already enabled.
  A disabled toggle is therefore not a confirmed root cause.
- No PostgreSQL server/network configuration or database records were changed.

## Same-context diagnostic report

Run in the same Mac Terminal used to start the backend:

```sh
cd /Users/mac/Documents/jobmitra/sop-pipeline
.venv/bin/python scripts/stage2_preflight.py --diagnose-network \
  --output outputs/stage-2/windows-network-diagnostic.json
```

This captures raw Python TCP connectivity, an `nc` connection check and an actual
`psql SELECT 1` using explicit application settings, followed by the original
read-only psycopg baseline. It also records libpq implementation/version and only
the **names** of inherited `PG*` environment variables. The psql probe ignores
those inherited libpq overrides and uses the configured target, SSL mode and
password privately. No raw client stderr, password, URL or row values are printed.
The password is passed only in the child process environment, never in argv.

Reports are private mode 0600. Reusing an output name preserves the old file and
creates a timestamped sibling. An output-permission failure occurs before querying
the database. All SQL in this helper runs with database-enforced read-only mode.

Interpret the probes together rather than inferring a password problem from 503:

- Raw TCP failure means that Python cannot establish a TCP connection in that
  launch context; it has not reached database authentication.
- A successful TCP probe does not prove that PostgreSQL credentials work. The
  psql/psycopg results test the database protocol and authentication too.
- If explicit-settings psql works but psycopg fails, inspect named libpq overrides
  such as `PGHOSTADDR` or `PGSERVICE` and compare client/driver results.
- `authentication_failed` calls for checking private credential/settings consistency;
  it does not justify resetting credentials or changing the Windows server.
- `host_unreachable`, `network_permission_denied`, refusal and timeout remain
  distinct safe diagnostic categories. Do not print the full driver exception.

macOS controls local network access per app in System Settings → Privacy & Security
→ Local Network ([Apple's instructions](https://support.apple.com/en-euro/guide/mac-help/mchla4f49138/mac)).
That setting is one possible cause to verify, not proof of the cause in this case.
No privacy, firewall or network setting is changed by the helper.

After connectivity succeeds, verify readiness returns 200, compare the API list
with the rendered company count and test client-side filtering in the browser.
Do not substitute the disposable preview data or silently run a migration.

Focused diagnostic validation after adding the comparison mode: 17 tests passed
in 0.73s, covering report preservation, credentials redaction, libpq override
isolation, timeouts and CLI cleanup/classification. Ruff passed. No Windows write
or full regression suite was run.
