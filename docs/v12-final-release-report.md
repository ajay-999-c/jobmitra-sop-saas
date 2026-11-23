# Final V12 PostgreSQL development release — 23 November 2026

The approved final UI adjustment changes only the generated header rule from
`justify-content:space-between` to `justify-content:flex-start`. The canonical
generator and `src/jobmitra/templates/v12/approved.html` agree. The original
standalone HTML remains byte-identical with SHA-256
`a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.
No Candidate Desk, Companies, JD workspace, Email Studio or proposal design was
changed by this final adjustment.

Desktop navigation follows the logo with the existing 20-pixel gap. Button order,
labels, active styling and dimensions remain intact. Browser measurements verified
the same header height as before (67 pixels at tested desktop sizes, 104 pixels
when wrapped), with no page/navigation overflow at widths 1465, 1024, 680, 390 and
320. All three routes, default `/`, refresh and back/forward passed. Screenshots:
[desktop](../output/playwright/v12-final-left-navigation-desktop.png) and
[mobile](../output/playwright/v12-final-left-navigation-mobile.png).
Screenshots are private ignored artifacts and are not included in Git.

## Unified resume parent

Inspection found that previous writes used `<candidate ID>/<kind>/...`, so the
requested category-first layout was not fully implemented. New native writes now
use the existing configurable `JOBMITRA_ATS_V2_RESUME_STORAGE_ROOT`:

```text
original/candidate_<ID>/<UUID>.pdf or .docx
altered/candidate_<ID>/<UUID>.pdf, .docx or .html
parsed/candidate_<ID>/<UUID>.json
```

New native JSON and PDF-extraction drafts preserve their exact UTF-8 JSON both in
the database and in an exclusively created private file. Downloads verify file
SHA/size and equality with preserved database bytes. Approval retains the original
draft reference, avoiding duplicate files. File publication failure rolls back
metadata; failed transactions remove only proven unreferenced new bytes and retain
files on uncertain commits. No database DDL changed for this adjustment.

The parsed PDF remains its canonical altered source; its extraction JSON lives
under `parsed/`. Existing metadata-only/legacy JSON APIs remain compatible. All
historical keys and seven unresolved references are retained. No original resume,
proposal, signed document or production directory was relocated, deleted or replaced.

## Focused release checks

| Check | Result |
| --- | --- |
| PostgreSQL adapter plus startup | 65 passed on the disposable private PostgreSQL cluster; includes 39 adapter cases and 26 startup cases |
| SQLite parsed documents, secure resume storage and approved adapters | 33 passed |
| New storage cases | Category-first keys, unchanged legacy keys, exact JSON/BOM bytes, tamper rejection, no-overwrite and failed-transaction cleanup passed on SQLite and PostgreSQL |
| Browser navigation | Default V12, three tabs, active state, refresh/back/forward and five responsive widths passed |
| Browser console/API | No console errors/warnings or failed API response statuses observed |
| Static checks | Python AST syntax, relevant Ruff, JavaScript syntax, generator consistency and Git whitespace passed |
| Previous Phase 3 evidence | 172 focused checks and 39 remote-development workflow checks retained; these were not unnecessarily repeated as a full suite |

The new release cases supplement and overlap earlier evidence; totals across
reports should not be added as unique tests. No complete regression suite was run.

The release verification again read the actual Windows PostgreSQL server and
confirmed full fingerprints of the 16 legacy public tables and all sealed snapshot
application/metadata rows. DDL, ownership and ACL dumps matched the pre-integration
backup byte for byte. All 16 staging freeze guards remain. Original SQLite V2/V3,
`.env`, the original HTML and 15 source-document hashes remain unchanged.

The application development schema remains isolated:
`jobmitra_dev.jobmitra_v12_dev_20261123_integration`. It contains 191 candidates,
140 companies, four JDs and 724 application rows after the earlier development
workflow checks. All 779 identity/classification entries and 187 candidate UUID
provenance mappings remain present; these counts do not describe production.
The protected stage still contains its verified 664 rows. All 58 trigger
responsibilities are documented in the [parity audit](v12-postgres-trigger-parity.md).

## Release contents and exclusions

The release includes the PostgreSQL runtime adapter, SQL resources, explicit
development configuration and startup checks, shared candidate/company/JD service
boundaries, portable document storage, versioned staging tooling/contracts, setup
and verified-copy scripts, focused tests, canonical UI generator/generated assets
and development/Windows documentation. The prior Phase 3 report lists its exact
service files. This final change additionally touches `parsed_router.py`,
`tests/test_v12_parsed_documents.py` and the generated approved template.

Only explicitly reviewed release paths are staged. The 15 unrelated historical
reference/prototype files remain untracked and preserved. Credentials, database
files, dumps, backups, resumes, parsed private artifacts, signed documents, logs,
runtime reports and generated screenshots remain excluded. Required existing
fonts, font licenses, logos and PDF/template assets remain tracked and unchanged.

`.gitattributes` preserves exact bytes for the manifest-pinned migration SQL,
contract, runtime SQL and approved reference. Generated assets/adapter inputs use
LF on Windows. The original staging SQL's existing trailing whitespace is retained
with a file-specific whitespace exception because changing it would invalidate
the sealed migration hash; other whitespace checks remain enabled.

The feature release is committed once with
`feat: finalize V12 PostgreSQL integration and navigation` and pushed normally to
`origin/feature/unified-workspace-v12`; verify the actual resulting commit and remote
hash in the release response. No amend, force push, main merge, retained-stash change
or production cutover is part of the release.

## Windows validation remains pending

No Windows SSH alias or active remote session was available. macOS verification
against a Windows-hosted PostgreSQL engine is not native Windows application/NTFS
validation. No native Windows result is claimed and no Windows storage root was
assumed to exist. Follow the [exact CMD runbook](v12-windows-postgresql-validation.md)
for clean-tree inspection, safe fetch/fast-forward pull, locked dependencies,
configuration, transfer and startup.

Transfer the 15 verified historical files and private manifests outside Git and
verify every identity, size and SHA. Preserve old relative keys. The common parent
is configurable; loopback direct editing deliberately requires isolated roots under
the checkout's runtime directory. An external inspected development NTFS root can
be used in capability-protected mode; global security is not relaxed.

Remaining gates: native Windows ACL/junction/hard-link and atomic-write checks,
PDF/DOCX/JSON processing, private file transfer, API workflow read-back, protected
data reconciliation, and separate production role/TLS/data/cutover approval. The
current no-TLS exception applies only to the previously confirmed private office
LAN. NSSM, firewall and production configuration remain untouched.
