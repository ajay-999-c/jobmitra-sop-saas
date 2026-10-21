# Phase 1B validation — 15 October 2026

## Focused test results

- `node --test tests/company-search.test.mjs`: **6 passed**.
- `JOBMITRA_RUN_UI_TESTS=1 .venv/bin/pytest -q tests/test_company_ui.py`:
  **8 passed in 1.00 second**. One existing upstream Starlette/httpx deprecation warning.
- Ruff lint/format checks and JavaScript syntax checks passed for affected files.
- No unrelated full regression suite, migration suite or Excel analysis suite was run.

The search-only timing check averaged **0.046 ms** across 1,000 queries on an index
of 166 synthetic companies. This Node measurement excludes DOM rendering and network
time. The two ES modules plus CSS total approximately 15 KB, uncompressed. No new
application dependency or build system was added.

API checks verified one initial directory SELECT with only UUID/name projection,
no initial contact/phone loading, nullable fields, multiple contacts/phones, stable
IDs, contact ownership checks, immutable source IDs, normalized-name conflicts,
atomic rollback, stale save/delete rejection, local assets and escaped output.

## Real browser verification

Chrome tested against a temporary loopback server with 166 synthetic companies and
sample contacts inside one outer PostgreSQL transaction. The normal production
dependency was overridden only in that temporary external QA host. No preview/test
endpoint or test-data mode was added to the application.

Observed results:

- Complete, alphabetically sorted initial list and total count.
- Initial load: HTML plus three local assets; **no list/contact API requests**.
- Typing `RADHE` produced five matches including prefix and middle-of-name examples;
  **no API requests while typing**.
- Clicking a company issued a single detail GET and displayed its contact on demand.
- Editing city and postal code succeeded; `001234` retained its leading zeroes.
- Add Company with a contact and leading-zero phone succeeded; the list refreshed
  from 166 to 167 entries while retaining the search query.
- Confirmed Delete removed only that test company/contact; the list returned to 166.
- Local writes each triggered one lightweight list refresh after their mutation.
- After more than 30 seconds on the page, two dispatched focus events triggered
  **one** directory GET, with the query and count retained.
- Desktop (1280 × 720) and mobile (390 × 844) screenshots were visually inspected.
  The mobile page had no horizontal overflow; list scrolling and detail forms worked.
- Browser console: **0 errors, 0 warnings**.

QA screenshots are in ignored `output/playwright/` and show synthetic records only.
The temporary browser and QA server were closed after verification.

## Preservation checks

All API fixture writes and browser edits were inside outer rollback transactions.
After closing QA, an independent connection confirmed:

| Item | Result |
| --- | --- |
| Database | Local `jobmitra_dev` |
| `companies` rows | 0, matching the baseline |
| `company_contacts` rows | 0, matching the baseline |
| Public tables | Existing `companies`, `company_contacts`, `alembic_version` only |
| Business column sets | Match the existing two-table models |
| Alembic revision | `0001_company_management`, unchanged |
| pgvector | 0.8.7, unchanged |

No database schema DDL, migrations or Excel imports were executed for Phase 1B.
The original workbook's SHA-256 remains:
`97936c31d1bc52ccad2f78a347c741118e1557204066ec63b56e0102aee342c0`.

An existing malformed file in the virtual environment initially prevented test
collection. Restoring the pinned FastAPI 0.143.1 package from the local cache fixed
it without changing application dependencies or lock versions.

## Operating behavior

Run the normal backend and open `/companies`; no synthetic records remain. The
directory will show saved PostgreSQL companies or its empty state until companies
are manually added or a later import is explicitly authorized.

The list refreshes after local writes, on manual Refresh, and on returning to a
stale page. A continuously active page intentionally does not poll other devices.
Remote edits are protected by row locking and the existing `updated_at` token;
conflicts ask the employee to reload details without silently discarding their input.

The implemented boundary is Phase 1B Company Directory and basic CRUD. Authentication,
additional modules, server search at larger scale and data import remain separate work.
