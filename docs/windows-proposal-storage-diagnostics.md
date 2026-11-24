# Windows proposal storage diagnostic

Copy `scripts/diagnose_windows_proposal_storage.py` to the matching Windows
checkout. From its project directory, run:

```powershell
.\.venv\Scripts\python.exe -B scripts\diagnose_windows_proposal_storage.py --nssm-service JobmitraV12
```

Default execution is read-only. It opens no database, reads no PDF contents,
changes no ACL or service, creates no report file and suppresses Python bytecode
writes. Only storage-related configuration fields are selected; database
credentials and capability tokens are never printed.

`--nssm-service` reads the current service identity, AppDirectory, explicit
`--env-file` argument, machine storage environment and NSSM AppEnvironment /
AppEnvironmentExtra overrides from the registry. It intentionally excludes the
interactive user's environment. `AppEnvironment` replacement semantics and
`AppEnvironmentExtra` overrides are respected. Current registry/files cannot
prove which environment an already-running service inherited at its last start.
If deployment uses a separate ENV-loading wrapper instead of these mechanisms,
pass its actual file explicitly with `--env-file C:\path\to\private.env` and
review any wrapper-specific overrides separately. Without `--nssm-service`, the
script uses the current Python process environment and the normal project ENV.

## Match the LocalSystem process identity

An elevated Administrator is not LocalSystem. For this service the diagnostic
must print `S-1-5-18` and pass `Match NSSM LocalSystem identity`. An Administrator
run can usefully identify some path failures but cannot verify service access.

Using the official Microsoft Sysinternals PsExec utility, from an elevated CMD:

```cmd
PsExec64.exe -s -i cmd.exe
```

Accept Microsoft's EULA if prompted. In the new LocalSystem CMD:

```cmd
whoami /user
cd /d C:\Users\PC\Documents\jobmitra-saas\jobmitra-sop-saas
.venv\Scripts\python.exe -B scripts\diagnose_windows_proposal_storage.py --nssm-service JobmitraV12
```

Close that CMD when finished. This does not change JobmitraV12's identity,
parameters or running state. PsExec uses its own temporary helper service; do not
change JobmitraV12 to run the diagnostic. No PostgreSQL credentials are needed.
PsExec is an optional administrator tool, not an application/script dependency.
Reference: https://learn.microsoft.com/en-us/sysinternals/downloads/psexec

## Interpret results

Each executed check prints PASS or FAIL. Failures include the exception type,
message, suppressed underlying exception chain, native API name, native error
code and Windows error description where available. In particular GetSecurityInfo
returns its error code directly; the diagnostic captures it even if GetLastError
contains a different/stale value. No application implementation is patched.

The script calls the real `checked_root`, `path_parts`, `Win32` identity,
security-descriptor, volume, info, final-path and private-ACL functions,
`private_acl`, `WindowsStore.root` and, for an existing UUID.pdf,
`WindowsStore.document` / `checked_key`. The supplementary ACL inspection displays
the owner SID, protection flag, ACE masks, trustees and explicit/inherited flags;
authorization decisions still use the application's actual functions.

`Windows proposal storage requires a protected private ACL` can mean an untrusted
owner SID, an unprotected DACL, or an empty DACL. Full Control for SYSTEM and
Administrators alone does not establish an acceptable owner. The owner-policy
check deliberately controls the other inputs while calling actual `private_acl`
to distinguish this case. It does not approve the complete ACL by itself.

Reparse points and junctions stop traversal. Canonical paths are reported from
pinned handles rather than resolving through an unsafe junction. Root failure
prevents document/probe access. No existing document is repaired or replaced.
Without `--document-key`, one existing UUID.pdf is sampled, without reading its
contents. No documents means file checks are explicitly NOT RUN. Supply
`--document-key <actual-UUID.pdf>` to inspect a particular historical file.
This is not a full inventory of every historical document. Exit code 1 indicates
one or more failures; exit code 0 means the executed checks passed, not that
unexecuted I/O operations have been verified.

## Optional isolated write probe

Append `--write-probe` only when deliberately testing writes. All preceding
checks must pass, including the LocalSystem identity check when applicable.
The script exclusively creates a randomly named `jobmitra-storage-diagnostic-*`
child of the validated root with the actual private security descriptor. A name
collision fails instead of reusing an existing directory. It exercises real
WindowsStore publish, read, SHA-256/exact-byte comparison and removal against
synthetic bytes in that child. It never generates a company proposal or writes
PostgreSQL metadata.

Cleanup removes only the fresh test key and the identity-checked empty disposable
directory using native handles; it never recursively deletes, moves documents,
repairs ACLs or changes the real root. Cleanup errors are FAIL results. A process
interruption or uncertain identity can leave the uniquely named probe directory
for inspection; the script does not force recovery. Do not use this option to
bypass a failed root/ACL check.

Native Windows results remain necessary. The focused automated tests run on Mac
are API simulations and cannot establish native NTFS or NSSM correctness.
