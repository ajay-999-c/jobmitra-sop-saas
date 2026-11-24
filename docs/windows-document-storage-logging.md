# Actual NSSM document-storage failures

These diagnostics run inside the existing application when a document route
returns 503. They do not fix permissions, relax storage policy, create a test
schema, or generate diagnostic documents. No extra ENV flag or dependency is
required. After reviewing and deploying these changes, restart the Windows
application through the normal approved deployment procedure to load them.
Do not expect an already-running Python process to pick up changed modules.
No service was restarted during implementation on Mac.

## Shared code paths

Resume upload:
`AtsRoute -> resume_upload -> resumes.upload_resume -> resumes._publish ->
resume_storage.publish -> proposal_storage.ensure_private_directory` for the
root, category and candidate directory, then `proposal_storage.publish`.

Proposal generation:
`ProposalRoute/AtsRoute -> guard/ready -> proposal_documents.generate ->
proposal_pdf.render -> proposal_storage.publish`.

On Windows both dispatch to the same `WindowsStore` / `Win32` implementation in
`proposal_windows.py`. Signed proposals and file-backed parsed resumes reuse it.
Resume directories require the same private ACL policy as proposal directories.
Metadata/context/history reads do not prove that native filesystem writes work.

## Relevant 503 paths

| Layer | Conditions |
| --- | --- |
| ATS/V12 dependencies | Missing ATS engine; V12 schema version incompatible; SQLAlchemy failure during connection, transaction, metadata insert or commit. `AtsRoute` maps SQLAlchemyError (except IntegrityError, which remains 409) and OSError to the existing generic ATS storage 503. |
| Resume root | `resumes._root`: missing root, nonabsolute path, symlink/reparse ancestor, or public static/templates directory. Invalid resume keys/relative paths and ordinary upload validation remain 422/413, not permission failures. |
| Shared root/key checks | `proposal_storage.checked_root`: absent, relative, traversal or public-directory root. `checked_key`: invalid proposal document reference. Unsupported storage platforms also fail 503. |
| Windows path | `path_parts`: UNC/device/nonlocal-drive paths, drive-relative paths, empty root, traversal, invalid/reserved names, alternate streams, trailing dots/spaces. |
| Native API availability | Win32 initialization/API binding fails. WindowsStore converts unavailable APIs to its existing 503. |
| Native filesystem | Directory creation/open, volume queries, token/SID/security descriptor queries, document open/create/read/write/flush/delete failures. Missing parents, denial, disk/share errors are examples of native errors to measure, not diagnoses. WindowsStore.document wraps OSError/AttributeError; raw OSError from directory preparation also reaches AtsRoute's generic 503. |
| Volume and handles | Nonlocal final volume, non-NTFS/no persistent ACLs, non-disk/wrong file type, reparse/junction, document hard-link count not one, canonical directory/document identity mismatch. |
| ACL | NULL/empty/unprotected DACL, owner outside process-user/SYSTEM/Administrators, unsupported/malformed ACE or SID, nonzero allow ACE for an untrusted SID. SYSTEM/Administrators Full Control alone does not prove acceptable ownership. |
| Proposal configuration | `proposal_documents.ready`: disabled feature/missing root, or proposal extension unavailable. |
| Proposal replay/download | `_read`: unavailable PDF bytes or size/SHA-256 mismatch. Existing retries can therefore fail before a new write. |

POSIX ownership/type/permission checks and OS errors also produce 503 on that
platform; no POSIX security check was removed. Other statuses, PDF templates,
business validation, transaction/cleanup rules and response bodies are unchanged.
The legacy `workflow_session` database 503 and the main non-API 503 HTML handler
are separate mechanisms; these two APIs use AtsRoute's JSON responses.

An unprotected resume root would be rejected if the native validator observes
that state. Whether this is the currently failing stage, and why the protected
proposal root fails, requires the new native Windows logs.

## Why there was no traceback

AtsRoute catches AtsError and SQLAlchemyError/OSError and constructs JSON without
logging them. These are handled responses, so Uvicorn's unhandled-error logger
does not print an exception. WindowsStore wrappers also use `raise ... from None`
to keep raw OS details out of the HTTP response. Cleanup helpers deliberately
suppress uncertain cleanup errors. Access logging only shows status codes.

## What the new log contains

Each failing document request emits `document_storage_failure` on `uvicorn.error`
(stderr) immediately before the existing 503 response is constructed. It records:

- A generated event ID, operation and route template (no actual entity IDs).
- Effective configured base storage root; document/candidate leaf paths are not logged.
- Storage step, directory depth and failing function/validation stage.
- Process token SID, directory/document ACL scope, protected flag, owner SID and
  owner-allowlist result. `null` means unavailable/not reached, not a passed check.
- Static policy reason, original exception type, errno, native API and Windows
  error code/description when available.
- Sanitized traceback: exception types plus code basenames, functions and line
  numbers, without source lines, locals, exception messages, SQL, parameters,
  filenames, credentials, headers, contact data or document contents.

Only code filenames appear in traceback frames. GetSecurityInfo's direct return
code and CreateFileW's error before descriptor cleanup are captured independently
of potentially stale GetLastError. The original exception/HTTP behavior is retained.
The first failure is preserved before cleanup, so secondary cleanup errors cannot
replace it. Request-scoped ContextVars cover threadpool handlers without mixing
concurrent requests. A failed log sink cannot change the HTTP response.

## Collect the actual Windows service log

After approved deployment/restart, run PowerShell as Administrator:

```powershell
Get-CimInstance Win32_Service -Filter "Name='JobmitraV12'" |
  Select-Object Name, State, StartName, ProcessId

$p = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\JobmitraV12\Parameters'
$p | Select-Object AppDirectory, AppStdout, AppStderr

$stderr = $p.AppStderr
if ([string]::IsNullOrWhiteSpace($stderr)) {
  throw 'NSSM stderr capture is not configured. Configure its I/O Error path first.'
}
if (-not [System.IO.Path]::IsPathRooted($stderr)) {
  $stderr = Join-Path $p.AppDirectory $stderr
}
Get-Content -LiteralPath $stderr -Tail 200 -Wait |
  Select-String -SimpleMatch 'document_storage_failure'
```

If stderr is unset, configure NSSM's **I/O -> Error (stderr)** to a dedicated
existing private log directory writable by LocalSystem, then apply it with the
normal approved service restart. Leave document roots, ACLs, service identity,
database configuration and stdout settings unchanged. Do not grant Everyone
permissions or log database connection strings. No NSSM change is made by this code.

Collect one matching line when the user next performs each intended failing
action: Resume Upload and Prepare Proposal. Do not create synthetic records in
the shared office schema merely to test logging. Share only the filtered JSON
lines, not ENV files, request bodies, complete logs or PDFs. Press Ctrl+C to stop
tailing; this does not stop the service. Native Windows results remain pending;
Mac API simulations do not establish Windows/NSSM/NTFS correctness.
