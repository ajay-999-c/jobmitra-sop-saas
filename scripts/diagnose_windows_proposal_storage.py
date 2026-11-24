"""Read-only Windows proposal-storage diagnostics; never imports the FastAPI app.

Run from the checkout with its virtualenv Python. --nssm-service reads current
NSSM registry configuration, not the running process's environment snapshot.
--env-file overrides automatic ENV-file selection. Only --write-probe creates
anything: a unique disposable child of the validated proposal root, never a
document in the real proposal namespace. No database is opened.
"""

import argparse
import ctypes as c
import hashlib
import json
import os
import re
import sys
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

# The default diagnostic must not even create application __pycache__ files.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError, create_model  # noqa: E402
from pydantic_settings import BaseSettings  # noqa: E402

from jobmitra.core.config import PROJECT_ENV_FILE, Settings  # noqa: E402
from jobmitra.modules.ats_v2 import proposal_storage as storage  # noqa: E402
from jobmitra.modules.ats_v2 import proposal_windows as win  # noqa: E402

FIELDS = (
    "unified_v12_proposal_storage_root",
    "ats_v2_resume_storage_root",
    "unified_v12_proposals_enabled",
    "v12_backend",
)
ENV_NAMES = {"JOBMITRA_" + field.upper(): field for field in FIELDS}
FAILED = object()


def error_details(error):
    """Include suppressed native contexts without dumping config/locals/secrets."""
    details, seen = [], set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ValidationError):
            message = error.errors(include_input=False, include_url=False)
        else:
            message = str(error)
        row = {"type": type(error).__name__, "message": message}
        for attribute in ("errno", "winerror", "status", "code"):
            value = getattr(error, attribute, None)
            if value is not None:
                row[attribute] = value
        code = getattr(error, "winerror", None) or getattr(error, "errno", None)
        if isinstance(code, int) and hasattr(c, "FormatError"):
            row["windows_message"] = c.FormatError(code).strip()
        details.append(row)
        error = error.__cause__ or error.__context__
    return details


class Report:
    def __init__(self):
        self.failures = 0
        self.api = None

    def check(self, label, action):
        if self.api is not None:
            self.api.failed_native = None
        try:
            value = action()
            print("PASS", label, json.dumps(value, ensure_ascii=True, default=str))
            return value
        except Exception as error:
            self.failures += 1
            details = {"exceptions": error_details(error)}
            if self.api is not None and self.api.failed_native:
                details["native_failure"] = self.api.failed_native
            print("FAIL", label, json.dumps(details, ensure_ascii=True, default=str))
            return FAILED


def require(condition, message):
    if not condition:
        raise RuntimeError(message)
    return message


class TracedWin32(win.Win32):
    """Observe the actual bound APIs; preserve every return value and last-error.

    GetSecurityInfo returns its error code directly. The application currently
    passes only its boolean success to check(), so GetLastError can be stale.
    Capture that direct code here without changing the application's behavior.
    """

    failed_native = None

    def bind(self, dll, name, args, result):
        super().bind(dll, name, args, result)
        function = getattr(dll, name)

        def traced(*values):
            value = function(*values)
            last_error = c.get_last_error()
            failed = (
                value is not None
                if name == "LocalFree"
                else value != 0
                if name == "GetSecurityInfo"
                else value in {None, c.c_void_p(-1).value}
                if name == "CreateFileW"
                else not value
            )
            if failed:
                code = int(value) if name == "GetSecurityInfo" else last_error
                self.failed_native = {
                    "api": name,
                    "return_value": value,
                    "GetLastError": last_error,
                    "windows_error_code": code,
                    "windows_message": c.FormatError(code).strip(),
                }
            c.set_last_error(last_error)
            return value

        setattr(dll, name, traced)


def nssm_configuration(service):
    """Read current machine + NSSM environment; never print the complete values."""
    import winreg

    def values(key):
        result = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            for index in range(winreg.QueryInfoKey(handle)[1]):
                name, value, kind = winreg.EnumValue(handle, index)
                result[name] = winreg.ExpandEnvironmentStrings(value) if kind == 2 else value
        return result

    if not re.fullmatch(r"[\w .-]+", service):
        raise ValueError("Invalid service name")
    base = rf"SYSTEM\CurrentControlSet\Services\{service}"
    identity = values(base).get("ObjectName")
    params = values(base + r"\Parameters")
    machine = values(r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")

    def selected(mapping):
        return {str(k).upper(): v for k, v in mapping.items() if str(k).upper() in ENV_NAMES}

    def entries(lines):
        return dict(line.split("=", 1) for line in (lines or []) if "=" in line)

    # AppEnvironment replaces the inherited environment; Extra overlays it.
    replacement = params.get("AppEnvironment")
    environment = selected(machine if replacement is None else entries(replacement))
    environment.update(selected(entries(params.get("AppEnvironmentExtra"))))
    match = re.search(r'--env-file(?:=|\s+)(?:"([^"]+)"|(\S+))', params.get("AppParameters", ""))
    directory = Path(params.get("AppDirectory") or ROOT)
    env_file = Path(match.group(1) or match.group(2)) if match else None
    if env_file is not None and not env_file.is_absolute():
        env_file = directory / env_file
    return {
        "service": service,
        "account": identity,
        "app_directory": str(directory),
        "env_file": str(env_file) if env_file else None,
        "environment": environment,
    }


def configuration(env_file=None, service=None):
    """Reuse the real Settings field definitions and dotenv/environment precedence.

    Select only storage-related fields so diagnostics need no DB credentials and
    cannot leak passwords through unrelated Settings validation errors.
    """
    service_info = nssm_configuration(service) if service else None
    if env_file is None and service_info and service_info["env_file"]:
        env_file = Path(service_info["env_file"])
    if env_file is not None and not env_file.is_file():
        raise FileNotFoundError(f"Explicit ENV file does not exist: {env_file}")

    class StorageSettings(BaseSettings):
        model_config = Settings.model_config

        @classmethod
        def settings_customise_sources(
            cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            if service_info is None:
                environment = env_settings
            else:

                def environment():
                    return {
                        ENV_NAMES[key]: value for key, value in service_info["environment"].items()
                    }

            return init_settings, environment, dotenv_settings, file_secret_settings

    model = create_model(
        "ProposalStorageSettings",
        __base__=StorageSettings,
        **{
            name: (Settings.model_fields[name].annotation, deepcopy(Settings.model_fields[name]))
            for name in FIELDS
        },
    )
    files = [PROJECT_ENV_FILE, env_file] if env_file else PROJECT_ENV_FILE
    settings = model(_env_file=files)
    summary = settings.model_dump(mode="json")
    summary["project_default_env_file"] = str(PROJECT_ENV_FILE)
    summary["explicit_env_file"] = str(env_file) if env_file else None
    if service_info:
        summary["nssm"] = {k: v for k, v in service_info.items() if k != "environment"}
        summary["nssm_storage_overrides"] = service_info["environment"]
        summary["configuration_note"] = (
            "Current registry/files; not a snapshot of the already-running service process."
        )
    return settings, summary


def acl_details(api, handle):
    """Inspect ACE flags for display, then let the real private_acl decide policy."""
    owner, dacl, descriptor = win.P(), win.P(), win.P()
    code = api.a.GetSecurityInfo(
        handle, 1, 5, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor)
    )
    if code:
        raise OSError(code, c.FormatError(code).strip())
    try:
        control, revision = c.c_uint16(), win.D()
        api.check(
            api.a.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision))
        )
        rows, policy_entries = [], []
        if dacl:
            for index in range(c.cast(dacl, c.POINTER(win.Acl)).contents.count):
                ace = win.P()
                api.check(api.a.GetAce(dacl, index, c.byref(ace)))
                kind = c.c_ubyte.from_address(ace.value).value
                flags = c.c_ubyte.from_address(ace.value + 1).value
                size = c.c_uint16.from_address(ace.value + 2).value
                row = {
                    "index": index,
                    "type": kind,
                    "flags": hex(flags),
                    "inherited": bool(flags & 0x10),
                    "size": size,
                }
                if kind in {0, 1} and size >= 16:
                    sid = win.P(ace.value + 8)
                    api.check(api.a.IsValidSid(sid))
                    api.check(8 + api.a.GetLengthSid(sid) <= size)
                    mask, trustee = win.D.from_address(ace.value + 4).value, api.sid(sid)
                    row.update(access="ALLOW" if kind == 0 else "DENY", mask=hex(mask), sid=trustee)
                    policy_entries.append((kind, mask, trustee))
                else:
                    row["unsupported_by_application"] = True
                    policy_entries.append((kind, 0, "unsupported"))
                rows.append(row)
        return {
            "owner_sid": api.sid(owner),
            "protected": bool(control.value & 0x1000),
            "control": hex(control.value),
            "null_dacl": not bool(dacl),
            "rules": rows,
            "policy_entries": policy_entries,
        }
    finally:
        api.k.LocalFree(descriptor)


def volume_details(api, handle):
    flags, name = win.D(), c.create_unicode_buffer(32)
    api.check(
        api.k.GetVolumeInformationByHandleW(
            handle, None, 0, None, None, c.byref(flags), name, len(name)
        )
    )
    return {"filesystem": name.value, "persistent_acls": bool(flags.value & 8)}


def validate_directory(api, root, report):
    """Pin ancestors using the same handles/path traversal as WindowsStore.root."""
    anchor, parts = win.path_parts(root)
    with ExitStack() as stack:
        canonical = None
        for index, part in enumerate((anchor, *parts)):
            expected = anchor if index == 0 else canonical + "\\" + part
            handle = report.check(
                f"Directory existence / open {expected}",
                lambda: stack.enter_context(api.open(expected, directory=True)),
            )
            if handle is FAILED:
                return
            raw = win.Info()
            report.check(
                f"Directory attributes {expected}",
                lambda: (
                    api.check(api.k.GetFileInformationByHandle(handle, c.byref(raw))),
                    {
                        "attributes": hex(raw.attributes),
                        "reparse_point": bool(raw.attributes & win.REPARSE),
                        "directory": bool(raw.attributes & win.DIRECTORY),
                        "links": raw.links,
                    },
                )[1],
            )
            info = report.check(
                f"Win32.info(directory=True) {expected}", lambda: api.info(handle, directory=True)
            )
            if info is FAILED:
                return  # Never descend through a rejected junction/reparse point.
            if index == 0:
                report.check("Filesystem details", lambda: volume_details(api, handle))
                report.check(
                    "Win32.volume (NTFS + persistent ACL policy)", lambda: api.volume(handle)
                )
            canonical = report.check(f"Win32.final {expected}", lambda: api.final(handle))
            if canonical is FAILED:
                return
            if index:
                identity = report.check(
                    f"Canonical directory identity {expected}",
                    lambda: require(
                        canonical.casefold() == expected.casefold(),
                        "Canonical path matches pinned parent",
                    ),
                )
                if identity is FAILED:
                    return
        acl = report.check(
            "Directory owner SID and explicit/inherited ACEs", lambda: acl_details(api, handle)
        )
        if acl is not FAILED:
            report.check(
                "Protected ACL flag",
                lambda: require(acl["protected"], "SE_DACL_PROTECTED (0x1000) is set"),
            )
            report.check(
                "Owner policy (actual private_acl, other inputs controlled)",
                lambda: win.private_acl(acl["owner_sid"], True, [(0, 1, api.actor)], api.actor),
            )
            report.check(
                "private_acl (actual directory owner + rules)",
                lambda: win.private_acl(
                    acl["owner_sid"], acl["protected"], acl["policy_entries"], api.actor
                ),
            )
        report.check("Win32.private (full native ACL validation)", lambda: api.private(handle))


def validate_document(store, root, key):
    storage.checked_key(key)
    with store.document(root, key, create=False) as handle:
        info = store.api.info(handle)
        return {
            "key": key,
            "hard_links": info.links,
            "contents_read": False,
            "canonical_path": store.api.final(handle),
            "acl": acl_details(store.api, handle),
        }


def first_document(store, root):
    # Keep the real traversal handles pinned while enumerating via the DOS path.
    # Otherwise validation and scandir would leave a directory-replacement gap.
    with store.root(root, create=False), os.scandir(root) as entries:
        for entry in entries:
            try:
                return storage.checked_key(entry.name)
            except win.AtsError:
                continue
    return None


def write_probe(store, root, report):
    """Exclusive new child only. Cleanup is handle/identity checked, never recursive."""
    api, key = store.api, str(uuid4()) + ".pdf"
    probe_name = "jobmitra-storage-diagnostic-" + uuid4().hex
    blob = b"%PDF-1.4\nJobmitra disposable storage diagnostic; no client data.\n%%EOF\n"
    created = False
    identity = None
    with store.root(root, create=False) as canonical:
        probe_path = canonical + "\\" + probe_name
        with api.security() as security:
            # Unlike mkdir(), this MUST fail if anything already occupies the name.
            api.check(api.k.CreateDirectoryW(probe_path, c.byref(security)))
        created = True
        directory = root / probe_name
        try:
            with api.open(probe_path, directory=True) as handle:
                info = api.info(handle, directory=True)
                identity = (info.volume, info.index_high, info.index_low)
                api.private(handle)
            report.check(
                "Probe publish (real WindowsStore.publish)",
                lambda: store.publish(directory, key, blob),
            )
            report.check(
                "Probe read / exact bytes / SHA-256",
                lambda: require(
                    store.read(directory, key, len(blob) + 1) == blob,
                    "Exact bytes; SHA-256 " + hashlib.sha256(blob).hexdigest(),
                ),
            )
        finally:
            if created and identity is not None:
                # Only our fresh key inside our fresh directory is ever removed.
                report.check(
                    "Probe file cleanup (real WindowsStore.remove)",
                    lambda: store.remove(directory, key),
                )

                def cleanup_directory():
                    with api.open(probe_path, directory=True, delete=True) as handle:
                        info = api.info(handle, directory=True)
                        require(
                            (info.volume, info.index_high, info.index_low) == identity,
                            "Disposable directory identity unchanged",
                        )
                        require(
                            api.final(handle).casefold() == probe_path.casefold(),
                            "Disposable directory canonical path unchanged",
                        )
                        api.private(handle)
                        api.delete(handle)  # Fails if nonempty; no recursive cleanup.

                report.check("Probe directory cleanup", cleanup_directory)
            else:
                print("FAIL Probe cleanup: identity could not be established; retained", probe_path)
                report.failures += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Use the same private ENV file as startup")
    parser.add_argument("--nssm-service", help="Read current NSSM storage ENV and service identity")
    parser.add_argument(
        "--document-key", help="Validate this existing UUID.pdf without reading contents"
    )
    parser.add_argument("--write-probe", action="store_true", help="Explicit disposable I/O probe")
    args = parser.parse_args(argv)
    report = Report()
    if (
        report.check(
            "Native Windows platform",
            lambda: require(
                os.name == "nt", "Native Windows is required; this is not a Windows simulation"
            ),
        )
        is FAILED
    ):
        return 1
    result = report.check(
        "Effective storage configuration", lambda: configuration(args.env_file, args.nssm_service)
    )
    if result is FAILED:
        return 1
    settings, summary = result
    print("PASS Configuration details", json.dumps(summary, ensure_ascii=True))
    report.check(
        "Proposal workflow enabled",
        lambda: require(settings.unified_v12_proposals_enabled, "Proposal workflow is enabled"),
    )
    root = report.check(
        "proposal_storage.checked_root",
        lambda: storage.checked_root(settings.unified_v12_proposal_storage_root),
    )
    if root is FAILED:
        return 1
    if report.check("proposal_windows.path_parts", lambda: win.path_parts(root)) is FAILED:
        return 1
    report.check(
        "Separate proposal/resume paths",
        lambda: require(
            settings.ats_v2_resume_storage_root is None
            or root != settings.ats_v2_resume_storage_root,
            "Configured proposal and resume paths are lexically distinct",
        ),
    )
    api = report.check("Win32 initialization / current_sid", TracedWin32)
    if api is FAILED:
        return 1
    report.api = api
    print("PASS Current process identity SID", api.actor)
    if str(summary.get("nssm", {}).get("account") or "").casefold() in {
        "localsystem",
        "nt authority\\system",
    }:
        report.check(
            "Match NSSM LocalSystem identity",
            lambda: require(
                api.actor == win.SYSTEM, "NSSM LocalSystem requires process SID S-1-5-18"
            ),
        )

    def security_descriptor():
        with api.security():
            return "Actual Win32.security descriptor constructed in memory; no ACL changed"

    report.check("Win32.security / SID conversion", security_descriptor)
    validate_directory(api, root, report)
    store = win.WindowsStore(api)

    def validate_root():
        with store.root(root, create=False) as canonical:
            return {"resolved_absolute_path": canonical, "read_only": True}

    root_result = report.check(
        "WindowsStore.root(create=False), exact application traversal", validate_root
    )
    if root_result is not FAILED:
        key = args.document_key or report.check(
            "Find existing UUID.pdf (names only)", lambda: first_document(store, root)
        )
        if key is not FAILED and key is not None:
            report.check(
                "WindowsStore.document: key, file type, reparse, hard-link, ACL, identity",
                lambda: validate_document(store, root, key),
            )
        elif key is None:
            print("NOT RUN Document checks: no UUID.pdf exists; no document was created or read.")
        if args.write_probe and not report.failures:
            report.check("Explicit isolated write probe", lambda: write_probe(store, root, report))
        elif args.write_probe:
            report.check(
                "Write probe safety gate",
                lambda: require(
                    False, "Refusing writes because a preceding diagnostic check failed"
                ),
            )
    elif args.write_probe:
        report.check(
            "Write probe safety gate",
            lambda: require(
                False, "Refusing writes because actual proposal root validation failed"
            ),
        )
    print(
        f"SUMMARY failures={report.failures}; mode="
        + ("explicit isolated write probe" if args.write_probe else "read-only")
    )
    return int(report.failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
