# Phase 1B — lightweight Company Directory

Implemented on 15 October 2026. This phase uses the existing two-table PostgreSQL 18
schema. It adds no migrations, runtime dependencies, data imports or other modules.

## Run locally

From the project root with the existing local `jobmitra_dev` environment:

```sh
source .venv/bin/activate
uvicorn jobmitra.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/companies>. `/` redirects there. The real directory shows
only PostgreSQL records; it does not read Excel or manufacture sample records. With
no saved companies, it shows the empty state and Add Company button.

## Directory and search requirements

- FastAPI serves a Jinja2 page with the full alphabetically ordered company list
  and an embedded JSON snapshot containing **only UUID and company name**.
- The initial page uses one directory SELECT and no follow-up list API request.
  Contacts, phone numbers and addresses are excluded from the search snapshot.
- The browser builds a small in-memory index once for each snapshot. Every search
  input event filters locally; no fetch, debounce request or server round trip.
- Matching is case-insensitive substring matching anywhere in names. Results rank
  exact names first, then prefixes, then other contains matches; each tier sorts
  alphabetically. Empty/whitespace-only search shows all companies.
- `radhe` matches Radhe Industries, Radhesham Industry and Radhe Exports, plus names
  such as Shree Radhe Metals. A result count shows matches and total loaded companies.
- Search normalization uses Unicode NFKC, lowercase and whitespace collapse. It is
  for finding names; database identity uniqueness continues to use the existing
  Python casefold normalizer. Punctuation is retained.
- The initial list is complete; no pagination, virtualization or UI framework.
  The list scrolls independently on desktop and has a bounded height on mobile.

`static/search.mjs` owns pure indexing/ranking functions. Its optional field list
makes deliberate contact/phone search expansion straightforward, but those details
are not currently fetched or searched. `repository.directory` owns the small SQL
projection. If size later justifies server search, replace the search-provider
boundary and add a PostgreSQL query endpoint after measuring payload/render costs.

## Basic CRUD behavior

- Selecting a company fetches its current complete details and contacts once on
  demand. Selecting it again or using Reload details fetches a fresh representation.
- Add Company requires a company name only. Contacts and phone lists may be empty;
  contact name and designation may be NULL. Optional address fields remain blank/NULL.
- Phone textareas accept one number per line. Numbers remain strings and retain
  leading zeroes; exact duplicates are removed without guessing country or ownership.
- Contacts can be added, edited and removed in the company editor. Existing contact
  UUIDs are retained; only explicitly new contact cards get new UUIDs.
- Editing preserves the company UUID and original `source_register_ids`. Source IDs
  display read-only and are rejected as request input. New manual companies have no
  spreadsheet references.
- Save is one transaction for company and contact changes. Duplicate names produce
  a readable conflict instead of overwriting another company. Validation and database
  failures retain the form inputs and roll back database changes.
- Delete requires a confirmation and the current update token. It explicitly deletes
  that company's contacts, then that company, in one transaction. Foreign-key conflicts
  from other records roll back the operation; no schema cascades were introduced.
- Unsaved changes prompt before switching/canceling or leaving. In-flight saves are
  guarded against double submission. Network failure does not clear the form.
- DOM text uses escaped Jinja output, `tojson`, `textContent` and input values. No
  company-supplied HTML is interpreted. Writes require same-origin browser requests
  and the UI's custom request header. No authentication/authorization module is added.

## Freshness without polling or persistent caches

1. Each page visit gets a new database-backed snapshot. Responses and local assets
   use `Cache-Control: no-store`; fetches use `cache: no-store`.
2. Successful local create/edit/delete updates the in-memory list and revalidates the
   lightweight list once. A pending earlier refresh finishes before this new refresh,
   preventing an old response from winning the save race. Current search text is retained.
3. The Refresh button always requests the latest lightweight snapshot. A failed
   refresh explicitly says that the last loaded list remains visible and can be retried.
4. Returning focus/visibility to the page refreshes the list if the last successful
   refresh was at least **30 seconds** ago. Simultaneous focus/visibility events share
   one in-flight request. Browser back/forward restoration also revalidates the list.
5. There is **no timer or background polling**. A continuously active page reflects
   another device's directory changes on manual Refresh or a later return to the page.
   Remote refresh never silently replaces an unsaved details form.
6. Every save/delete supplies the detail's existing `updated_at`. The service locks
   the company row, compares the timestamp, and rejects stale changes with HTTP 409.
   All UI writes, including contact-only edits, advance the company token. Reload
   details is the explicit way to obtain another employee's latest version. Direct
   SQL writers would also need to advance this token; no database trigger was added.

No service workers, localStorage, sessionStorage, persistent index, Redis, React,
HTMX download, external fonts, CDN assets or build pipeline. The browser requires
only the locally served CSS and two small ES modules (about **15 KB combined,
uncompressed**). Node is needed for development search tests, not to run the backend.

## Routes and module ownership

| Route | Purpose |
| --- | --- |
| `GET /companies` | Server-rendered directory and one embedded lightweight index. |
| `GET /api/companies` | Explicit/focus/post-write snapshot refresh; UUID/name only. |
| `GET /api/companies/{id}` | On-demand company, contacts and read-only source IDs. |
| `POST /api/companies` | Create a company and optional contacts. |
| `PUT /api/companies/{id}` | Complete editable state plus required `updated_at` and explicit contacts array. |
| `DELETE /api/companies/{id}` | Confirmed deletion using a JSON `updated_at` token. |
| `GET /static/companies/*` | Locally bundled module assets. |

Writes use JSON and `X-Jobmitra-UI: 1`; cross-origin writes are rejected. PUT is a
complete editor representation, not a partial PATCH. Removed contacts are explicit
through that complete list. Unknown, duplicate or cross-company contact IDs are
rejected. A missing contacts list cannot accidentally erase contacts. Source IDs,
company IDs, normalized name keys and creation timestamps are not editable inputs.

All implementation files are inside `modules/companies`, with one composition
change in `main.py`. Templates and assets live with the package so installed builds
can serve them without relying on the process working directory for asset lookup.

## Focused validation

```sh
node --test tests/company-search.test.mjs
JOBMITRA_RUN_UI_TESTS=1 .venv/bin/pytest -q tests/test_company_ui.py
```

- Six Node search checks passed: complete alphabetical initial results, exact/prefix/
  contains ranking, case-insensitive matching, empty/no-match queries, optional future
  search fields, no fetch/mutation and a 166-entry timing check. Mean pure search time
  observed locally was **0.046 ms** over 1,000 queries; this excludes DOM work and is
  an observation, not a performance guarantee.
- Eight focused Python UI/API tests passed. They cover local assets, same-origin
  writes, validation, one-query initial snapshot without contact/phone loading,
  company/contact CRUD, nullable addresses, ID preservation, duplicate-name rollback,
  stale edits/deletes, contact ownership, read-only source IDs and escaped names.
- Database-backed tests use synthetic rows in an outer transaction against the
  existing schema. Each request commits only a savepoint; the outer transaction
  rolls back all fixtures and edits. No test migrations or schema creation.
- A pre-existing corrupted installed FastAPI `testclient.py` initially blocked
  collection. The locked FastAPI 0.143.1 package was restored from the local cache;
  no dependency versions or application dependencies were changed. The existing
  upstream Starlette/httpx test-client deprecation warning remains.
- Browser verification and final preservation checks are recorded in
  [Phase 1B validation](phase-1b-validation.md). Only focused UI/search tests were run.

Stop after Phase 1B. No Excel import, JD work or unrelated module/schema change.
