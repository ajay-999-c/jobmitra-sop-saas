# JD workspace checksum portability

The PostgreSQL workspace manifest uses SHA-256 of `workspace_v1.sql`, with only
CRLF pairs converted to LF. The original LF checksum is preserved:

```text
e1acaa21f455ef40b36da87aa9cab794130514caf93d9a01cda0a60bb0835d59
```

LF, CRLF and mixed checkouts now agree. SQL statements, comments, whitespace,
encoding and lone carriage returns remain significant. No alternative checksum
is accepted, and a real SQL change still fails startup validation. The same digest
function is used when installing and validating the PostgreSQL workspace extension.
`.gitattributes` also pins `workspace_v1.sql` to `text eol=lf` for future checkouts.

This application update requires no migration or stored-manifest update. Keep
the existing office database and checksum unchanged. Update the feature branch
with `git pull --ff-only origin feature/unified-workspace-v12`, synchronize the
existing virtual environment with `uv sync --locked`, then restart `JobmitraV12`.
Do not reset local changes, rewrite SQL files or run the migration runner again.

## Focused verification

`tests/test_workspace_manifest.py` checks LF/CRLF/mixed compatibility with the
original checksum and rejects changes to SQL behavior, whitespace, comments and
lone carriage returns. Its separately opted-in integration checks use the real
application lifespan and office database through read-only PostgreSQL connections.
They verify startup and GET endpoints with both LF and CRLF representations,
unchanged manifest contents, and startup rejection of modified SQL. Gmail is
disabled. These are Mac PostgreSQL-client tests with Windows-style bytes, not
native Windows/NSSM test results.

```sh
JOBMITRA_OFFICE_MANIFEST_READONLY_TESTS=1 .venv/bin/python -m pytest -q tests/test_workspace_manifest.py
```

## Other checksum implementations reviewed

- `postgres.version_digest()` hashes the exact bytes of `postgres_runtime.sql`
  and `postgres_rules.sql`. Both files already have `-text` attributes, preserving
  their historical bytes under Windows checkout conversion. Their manifest
  contract remains unchanged; manual edits still fail validation.
- The sealed staging importer hashes `001_stage.sql` and `001_source_contract.json`
  as files. Both already have `-text` attributes. Backup/document hashes and
  canonical data fingerprints intentionally retain exact-byte/data semantics.
- The SQLite workspace extension still hashes `workspace_v1_sqlite.sql` as raw
  bytes in `workspace_store.apply_sqlite()` and `database._check()`. That file has
  no explicit line-ending attribute, so the same checkout portability risk exists
  there. It is outside this PostgreSQL correction. Its stored hashes may have been
  created from either representation; changing that contract needs a separate
  compatibility review without rewriting existing SQLite manifests.
