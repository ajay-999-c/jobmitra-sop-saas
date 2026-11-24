# Jobmitra V12 Windows deployment and private document storage

## Confirmed resolution

The Windows operator confirmed that the resume-upload and proposal-generation
failures were resolved. Application diagnostics identified
`validation_reason=untrusted_owner`. The NSSM service `JobmitraV12` runs as
**LocalSystem**, whose process-user SID is **`S-1-5-18`**. The document folders
were owned by a SID outside the storage validator's allowlist. Making the managed
storage folders **SYSTEM-owned** resolved that ownership failure.

Full Control permissions and ownership are different checks. A protected DACL
granting SYSTEM and Administrators Full Control can still fail if the owner is
an individual administrator's SID. Membership in Administrators does not make
that person's SID the Builtin Administrators SID (`S-1-5-32-544`).

SYSTEM ownership is the deployment standard here. The unchanged application
validator also accepts the actual process-user SID and Builtin Administrators
as owners. This resolution did not require changing its allowlist, disabling
ACL validation, altering PDF templates, or migrating any database.

This resolution supersedes the incident's earlier "native Windows results
pending" status in the diagnostic investigation notes. Retain the diagnostic
logging from commit `e1096d0` (or later) for future failures.

This is an operator-confirmed Windows resolution, not a claim that Codex accessed
Windows or executed the commands below. This documentation-only update does not
reapply permissions, reconfigure NSSM, or restart a service.

## Required NTFS state

- Use local **NTFS** storage with persistent ACL support. `D:` must exist.
- Keep resumes at **`D:\JobmitraData\resumes`** and proposals at
  **`D:\JobmitraData\proposals`**; do not combine the two roots.
- Set the managed folder owner to **SYSTEM** (`S-1-5-18`).
- Protect each validated storage directory/file DACL: inheritance from its parent
  is disabled (`AreAccessRulesProtected=True`). The application creates its own
  new private leaves with a protected DACL.
- Use standard Allow entries granting SYSTEM and Builtin Administrators Full
  Control. Do not retain other explicit Allow entries, including read-only
  entries for Users, Authenticated Users, Everyone or individual users.
- Keep all path ancestors free of junctions/reparse points. Document files must
  be ordinary single-link files; traversal, alternate streams, UNC/device paths,
  hard links and canonical-path changes remain rejected.

An inheritable `(OI)(CI)` rule on a **protected** folder is compatible with this
setup: it describes propagation to children, not inheritance from the parent.
Each leaf that the application validates must still satisfy its own private ACL
check. A healthy root does not certify every historical file below it.

## Final storage layout

The confirmed operational roots are `resumes` and `proposals`. The following is
the deployment layout, including standard log filenames and an optional legacy
document root. Log filenames are configuration choices, not independently
verified current NSSM registry values; inspect the actual values before changing
an existing service.

```text
D:\JobmitraData\
  resumes\
    original\candidate_<canonical-id>\<generated-key>.pdf or .docx
    altered\candidate_<canonical-id>\<generated-key>.pdf or .docx or .html
    parsed\candidate_<canonical-id>\<generated-key>.json
    imports\...                     preserved imported keys, where present
    <legacy-relative-directories>\... preserved historical keys, where present
  proposals\
    <proposal-uuid>.pdf              generated proposal
    <signed-document-uuid>.pdf       uploaded signed copy, separate immutable file
  legacy-documents\                 only if configured for legacy workflows
  logs\
    jobmitra-stdout.log              standard NSSM output destination
    jobmitra-stderr.log              standard NSSM error/diagnostic destination
```

Generated and signed proposals use the same proposal root and separate UUID
keys; there is no required `signed` subdirectory or separate signed-storage ENV
variable. Parsed JSON files use the resume root. Historical JSON/text-only
records can remain metadata-only. Preserve all existing keys, files, references
and checksums; this layout is not an instruction to relocate old documents.

## PowerShell: owner and protected permissions

Use **Administrator PowerShell**, during a planned setup/repair window with the
service quiesced and verified document/metadata backups available. Do not rerun
repairs on the already healthy installation. These commands act only on the
listed managed directories; they do not recurse through existing documents or
change the `D:\` volume-root ACL. Inheritable ACE changes can affect children
that currently inherit, so review existing trees before applying them.

```powershell
$ErrorActionPreference = 'Stop'
$volume = Get-Volume -DriveLetter D -ErrorAction Stop
if ($volume.FileSystem -ne 'NTFS') { throw 'D: must be local NTFS storage.' }

$systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$adminSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$paths = @(
  'D:\JobmitraData',
  'D:\JobmitraData\resumes',
  'D:\JobmitraData\proposals',
  'D:\JobmitraData\logs'
)
# Add D:\JobmitraData\legacy-documents only if that root is actually required.

foreach ($path in $paths) {
  if (!(Test-Path -LiteralPath $path)) {
    New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
  }
  $item = Get-Item -LiteralPath $path -Force
  if (!$item.PSIsContainer -or
      ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Refusing non-directory or reparse point: $path"
  }

  # Numeric SIDs avoid localized account-name differences. Check native exit status.
  & icacls.exe $path /setowner '*S-1-5-18'
  if ($LASTEXITCODE -ne 0) { throw "SYSTEM ownership failed: $path" }

  # A fresh DACL avoids leaving unrelated explicit Allow entries behind.
  # Do not set Owner on this object: icacls has already set the real owner.
  $acl = [System.Security.AccessControl.DirectorySecurity]::new()
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($sid in @($systemSid, $adminSid)) {
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
      $sid,
      [System.Security.AccessControl.FileSystemRights]::FullControl,
      [System.Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit',
      [System.Security.AccessControl.PropagationFlags]::None,
      [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
  }
  Set-Acl -LiteralPath $path -AclObject $acl

  $after = Get-Acl -LiteralPath $path
  if ($after.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-18' -or
      !$after.AreAccessRulesProtected) {
    throw "Owner/protection verification failed: $path"
  }
  $after | Format-List Path, Owner, AreAccessRulesProtected, AccessToString
}
```

For an existing directory whose DACL is **already verified correct**, the
targeted ownership-only correction is:

```powershell
icacls.exe 'D:\JobmitraData\resumes' /setowner '*S-1-5-18'
if ($LASTEXITCODE -ne 0) { throw 'Resume ownership correction failed.' }
icacls.exe 'D:\JobmitraData\proposals' /setowner '*S-1-5-18'
if ($LASTEXITCODE -ne 0) { throw 'Proposal ownership correction failed.' }
```

Do not use `/reset`, broad recursive ownership changes, or Everyone grants as a
substitute for diagnosis. `/grant:r` alone does not remove other trustees'
explicit grants. Inspect a failing historical file/directory separately and
apply any approved repair only to that identified object. Permission commands
change security metadata, not document bytes or PostgreSQL rows.
See Microsoft's [icacls reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)
and [Set-Acl reference](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/set-acl?view=powershell-5.1).

## Private environment configuration

Retain the existing private PostgreSQL username/password. The supported settings
below belong in the private file actually loaded by the service, such as
`.env.v12.postgres`, or its existing service environment. Never commit that file
or print the complete service environment.

```dotenv
JOBMITRA_LOCAL_V12=0
JOBMITRA_V12_BACKEND=postgresql
JOBMITRA_V12_POSTGRES_DEVELOPMENT=true
JOBMITRA_V12_POSTGRES_SCHEMA=jobmitra_v12_dev_20261123_integration
JOBMITRA_V12_POSTGRES_TRUSTED_LAN=true
JOBMITRA_DB_HOST=192.168.1.51
JOBMITRA_DB_PORT=5432
JOBMITRA_DB_NAME=jobmitra_dev
JOBMITRA_DB_SSLMODE=disable
JOBMITRA_ATS_V2_ENABLED=true
JOBMITRA_UNIFIED_V12_ENABLED=true
JOBMITRA_UNIFIED_V12_PROPOSALS_ENABLED=true
JOBMITRA_UNIFIED_V12_LOCAL_DIRECT_EDITING=false
JOBMITRA_OFFICE_LAN_ENABLED=true
JOBMITRA_OFFICE_LAN_CIDRS=192.168.1.0/24,127.0.0.1/32,::1/128
JOBMITRA_OFFICE_LAN_HOSTS=
JOBMITRA_ATS_V2_RESUME_STORAGE_ROOT=D:/JobmitraData/resumes
JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT=D:/JobmitraData/proposals
# Only set this if the corresponding legacy document root is actually in use:
# JOBMITRA_DOCUMENT_STORAGE_ROOT=D:/JobmitraData/legacy-documents
JOBMITRA_RESUME_PROCESSING_ENABLED=false
JOBMITRA_AI_ENABLED=false
JOBMITRA_OFFICE_TIMEZONE=Asia/Kolkata
```

`JOBMITRA_DB_USER` and `JOBMITRA_DB_PASSWORD` remain required private credentials;
they are deliberately omitted above. The recorded office subnet is
`192.168.1.0/24`; retain only the verified office allowlist and confirm Windows'
address/mask with `ipconfig`. The existing non-TLS database exception applies only
to the confirmed trusted office LAN. PostgreSQL selection fails closed without
SQLite fallback. This shared office schema must not receive synthetic write
tests or provisioning/migration commands.

Office LAN mode preserves password-free operator/supervisor workflows behind
the network boundary. Local direct-editing mode must remain false for an office
bind; keep same-origin, eligibility, transaction and upload validations enabled.
Service/machine environment values override dotenv. In particular remove or
correct a conflicting `JOBMITRA_LOCAL_V12=1` through the existing reviewed
deployment process, without dumping credentials. See [Office LAN policy](v12-office-lan.md)
and the [PostgreSQL runbook](v12-windows-postgresql-validation.md).

## NSSM startup configuration

Use the existing service **JobmitraV12**, identity **LocalSystem** and the checkout's
existing virtual environment. Example checkout:
`C:\Users\PC\Documents\jobmitra-saas\jobmitra-sop-saas`.

| NSSM setting | Required configuration |
| --- | --- |
| Application | `C:\Users\PC\Documents\jobmitra-saas\jobmitra-sop-saas\.venv\Scripts\python.exe` |
| AppDirectory | `C:\Users\PC\Documents\jobmitra-saas\jobmitra-sop-saas` |
| ObjectName | `LocalSystem` |
| Startup | Automatic, using the existing service installation |
| AppStdout | Standard layout: `D:\JobmitraData\logs\jobmitra-stdout.log` |
| AppStderr | Standard layout: `D:\JobmitraData\logs\jobmitra-stderr.log` |

AppParameters when using the separate private ENV file:

```text
-B -m uvicorn jobmitra.main:app --app-dir src --host 0.0.0.0 --port 8002 --workers 1 --no-access-log --no-proxy-headers --env-file "C:/Users/PC/Documents/jobmitra-saas/jobmitra-sop-saas/.env.v12.postgres"
```

If the established deployment uses checkout-root `.env` instead, omit the
`--env-file` pair; do not load a different file accidentally. Keep Python,
AppDirectory and the ENV file in the same reviewed checkout. NSSM does not need
an activated interactive shell or `uv run`. Keep the existing trusted-office
firewall scope; do not expose port 8002 publicly.

Inspect the effective service configuration without exposing credentials:

```powershell
Get-CimInstance Win32_Service -Filter "Name='JobmitraV12'" |
  Select-Object Name, State, StartMode, StartName, ProcessId
$p = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\JobmitraV12\Parameters'
$p | Select-Object Application, AppDirectory, AppStdout, AppStderr
```

For a planned log-path setup using the standard layout, configure only after
verifying that the private logs directory exists and LocalSystem can write it:

```powershell
nssm set JobmitraV12 AppStdout 'D:\JobmitraData\logs\jobmitra-stdout.log'
nssm set JobmitraV12 AppStderr 'D:\JobmitraData\logs\jobmitra-stderr.log'
nssm set JobmitraV12 AppStdoutCreationDisposition 4
nssm set JobmitraV12 AppStderrCreationDisposition 4
```

Preserve existing log files and append behavior. Retain already valid alternate
paths rather than moving or overwriting logs. Changes to service settings, ENV
or Python code require a planned `Restart-Service -Name JobmitraV12`; they must
survive Windows restart via the existing automatic service. Do not reinstall
the service or change its identity as an ownership workaround. See the
[NSSM configuration reference](https://nssm.cc/usage).

## Diagnostics and troubleshooting

The committed diagnostic logging implementation remains enabled. The
`uvicorn.error` logger writes sanitized `document_storage_failure` JSON to
**AppStderr**; `--no-access-log` does not disable it. Standard destinations are
listed above, but the actual NSSM registry value is authoritative:

```powershell
$p = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\JobmitraV12\Parameters'
$stderr = $p.AppStderr
if ([string]::IsNullOrWhiteSpace($stderr)) { throw 'NSSM stderr capture is not configured.' }
if (![IO.Path]::IsPathRooted($stderr)) { $stderr = Join-Path $p.AppDirectory $stderr }
Get-Content -LiteralPath $stderr -Tail 200 -Wait |
  Select-String -SimpleMatch 'document_storage_failure'
```

1. Confirm the deployed revision, service identity and the ENV file/overrides in
   use. `LocalSystem` must correspond to process SID `S-1-5-18`; an interactive
   Administrator test has a different user SID.
2. Read the matching log's operation, root, storage step, failing function,
   `validation_reason`, `process_sid`, `owner_sid`, `owner_valid` and
   `acl_protected`. `untrusted_owner` identifies the resolved incident's cause.
   A null field means validation did not reach that measurement.
3. Verify actual owner SID and protected flag with `Get-Acl`; do not infer them
   from the Full Control display alone. Check each specifically failing nested
   directory/file and its ancestors for reparse points.
4. For `unprotected_dacl`, `untrusted_allow_ace`, unsupported ACE, path, hard-link,
   volume or native error-code failures, investigate that logged condition.
   Do not assume every 503 is ownership: missing configuration, metadata/database
   failures and checksum mismatches also have distinct paths.
5. If no event appears, verify the logging commit is deployed, Python was restarted,
   and AppStderr is configured/writable. A caught 503 will not automatically
   produce an unhandled Uvicorn exception traceback.
6. Check live health without modifying records:

   ```powershell
   Invoke-RestMethod 'http://127.0.0.1:8002/health/ready'
   Invoke-RestMethod 'http://127.0.0.1:8002/api/ats-v2/health'
   Invoke-RestMethod 'http://127.0.0.1:8002/api/v12/access'
   ```

   Expect readiness success, `storage=postgresql`, and Office LAN editing access
   without authentication. Open `http://<verified-office-server-IP>:8002/` for V12.
7. Verify the intended resume/proposal workflow, download, history and SHA checks
   against authorized records. Keep synthetic write tests isolated from shared
   office data. Git updates do not transfer document bytes: Mac/Windows sharing
   a schema still need coordinated, checksum-verified physical-file storage.

For a separate read-only check under the actual LocalSystem identity, follow
the [standalone diagnostic instructions](windows-proposal-storage-diagnostics.md).
For complete failure coverage, sanitization details and log collection, see
[application storage diagnostics](windows-document-storage-logging.md).
No credentials, candidate details or document contents belong in shared logs.
