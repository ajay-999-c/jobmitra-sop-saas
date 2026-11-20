# V12 approved UI integration — current handoff

Resumed on 20 November 2026 at the user’s request. The initial Jinja HTTP 500 is fixed.
The approved UI is integrated and tested against isolated SQLite/resume copies.

Primary report: [verification, API mapping, pass/fail matrix and screenshots](v12-approved-ui-verification.md).
Control inventory: [expanded source element matrix](v12-approved-control-matrix.md).
Initial baseline: [before corrections](v12-ui-parity-before.md).

Preview: `http://127.0.0.1:8768/workspace-v12/companies`.
Runtime script: `runtime/v12-parity/serve_approved.py`; private copy
`runtime/v12-parity/approved-preview.sqlite3`, private resumes in the same runtime directory.
Editing is locked for review. Never repoint this process at production. Browser session `v12-integrated` uses synthetic QA identities.
Private access keys remain only in `runtime/v12-development/preview-access.json`.
No production deployment/migration or Git commit/push has occurred.

Original HTML remains immutable, SHA-256
`a4c9a21cef040457fce8c4872d09d490962f5b98301703d7e1287fdcbf32340e`.
Generated artifacts rebuild with:

```
node scripts/build_approved_v12.mjs /Users/mac/.npm/_npx/31e32ef8478fbf80/node_modules/playwright/lib/transform/babelBundle.js
```

Regression logs, field-level preview reconciliation, read-only production safety comparison,
control inventory, fixtures and access-independent snapshots are in ignored `runtime/v12-parity/`.
Screenshots are in `output/playwright/v12-{approved,after}-*`.

Remaining boundaries: approved message content needed for Not Joined / Selection Cancelled
email templates; staff/domain/Foundit SQLite migration deferred; manual milestone controls
are not transmission, invoice or payment services. Seven historic unavailable resume files
remain exceptions. See the report for precise limits and identity/cutover requirements.

Continue only on `feature/unified-workspace-v12`. Preserve HEAD `2e0c7bc`, retained stash,
all original references, production SQLite V2, PostgreSQL and the processor database.
Do not commit, push, migrate live data or deploy without the user’s next instruction.
