"""Focused diagnostic tests. Native Windows API behavior is simulated on macOS."""

import ctypes
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/diagnose_windows_proposal_storage.py"
spec = importlib.util.spec_from_file_location("windows_proposal_diagnostic", SCRIPT)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
GUID = r"\\?\Volume{00000000-0000-0000-0000-000000000001}"
ROOT = PureWindowsPath(r"D:\JobmitraData\proposals")
KEY = "00000000-0000-0000-0000-000000000001.pdf"


def acl(owner=diag.win.SYSTEM, protected=True):
    return {
        "owner_sid": owner,
        "protected": protected,
        "null_dacl": False,
        "policy_entries": [(0, 0x1F01FF, diag.win.SYSTEM)],
        "rules": [],
    }


class FakeApi(diag.win.Win32):
    """Use real Win32.info and private_acl with an in-memory API boundary."""

    def __init__(self, attack=None):
        self.actor = diag.win.SYSTEM
        self.attack = attack
        self.events = []
        self.files = {}
        self.created = set()
        self.held = []
        self.k = SimpleNamespace(
            GetFileType=lambda h: 1,
            GetFileInformationByHandle=self.information,
            CreateDirectoryW=self.create_directory,
            GetVolumeInformationByHandleW=self.volume_information,
        )

    @contextmanager
    def security(self):
        yield diag.win.SecurityAttributes()

    @contextmanager
    def open(self, path, directory=False, create=False, delete=False):
        path = str(path)
        self.events.append(("open", path, directory, create, delete))
        if create:
            if path in self.files:
                raise OSError(183, "already exists")
            self.files[path] = b""
        elif not directory and path not in self.files:
            raise OSError(2, "not found")
        self.held.append(path)
        try:
            yield path
        finally:
            self.held.remove(path)

    def information(self, handle, pointer):
        info = ctypes.cast(pointer, ctypes.POINTER(diag.win.Info)).contents
        info.attributes = 0 if handle.endswith(".pdf") else diag.win.DIRECTORY
        if self.attack == "reparse" and handle.endswith("proposals"):
            info.attributes |= diag.win.REPARSE
        info.links = 2 if self.attack == "hardlink" and handle.endswith(".pdf") else 1
        info.volume, info.index_low = 10, sum(map(ord, handle))
        return True

    def volume_information(self, handle, label, length, serial, max_name, flags, name, size):
        ctypes.cast(flags, ctypes.POINTER(diag.win.D)).contents.value = 8
        name.value = "NTFS"
        return True

    def final(self, handle):
        return GUID if handle == "D:\\" else handle

    def private(self, handle):
        owner = "S-1-5-21-100-1001" if self.attack == "owner" else self.actor
        diag.win.private_acl(owner, True, [(0, 1, self.actor)], self.actor)

    def create_directory(self, path, attributes):
        self.events.append(("mkdir", path))
        if self.attack == "collision":
            return False
        assert path not in self.created
        self.created.add(path)
        return True

    def mkdir(self, path):
        # The application deliberately accepts an existing leaf without changing its ACL.
        if path not in self.created:
            self.create_directory(path, None)

    def write(self, handle, blob):
        self.events.append(("write", handle))
        self.files[handle] = blob

    def read(self, handle, limit):
        self.events.append(("read", handle))
        return self.files[handle][:limit]

    def delete(self, handle):
        assert handle in self.held
        self.events.append(("delete", handle))
        if handle.endswith(".pdf"):
            del self.files[handle]
        else:
            assert not any(path.startswith(handle + "\\") for path in self.files)
            self.created.remove(handle)


def test_configuration_uses_actual_fields_and_never_displays_credentials(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "JOBMITRA_DB_PASSWORD=TOP_SECRET_NEVER_PRINT\n"
        "JOBMITRA_UNIFIED_V12_PROPOSALS_ENABLED=true\n"
        "JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT=D:/JobmitraData/proposals\n"
    )
    monkeypatch.delenv("JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("JOBMITRA_UNIFIED_V12_PROPOSALS_ENABLED", raising=False)
    settings, summary = diag.configuration(env_file=env)
    assert str(settings.unified_v12_proposal_storage_root).replace("\\", "/") == (
        "D:/JobmitraData/proposals"
    )
    assert settings.unified_v12_proposals_enabled
    assert "TOP_SECRET" not in str(summary)
    assert "db_password" not in type(settings).model_fields


def test_nssm_overrides_dotenv_and_ignores_interactive_user_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT=C:/wrong-dotenv\n")
    monkeypatch.setenv("JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT", "C:/wrong-interactive")
    service = {
        "account": "LocalSystem",
        "env_file": str(env),
        "environment": {"JOBMITRA_UNIFIED_V12_PROPOSAL_STORAGE_ROOT": "D:/JobmitraData/proposals"},
    }
    monkeypatch.setattr(diag, "nssm_configuration", lambda name: service)
    settings, summary = diag.configuration(service="JobmitraV12")
    assert str(settings.unified_v12_proposal_storage_root).startswith("D:")
    assert "environment" not in summary["nssm"]


def test_real_acl_policy_identifies_untrusted_owner_even_with_protected_system_acl(capsys):
    owner = "S-1-5-21-100-1001"
    report = diag.Report()
    result = report.check(
        "owner",
        lambda: diag.win.private_acl(
            owner,
            True,
            [(0, 0x1F01FF, diag.win.SYSTEM), (0, 0x1F01FF, diag.win.ADMINS)],
            diag.win.SYSTEM,
        ),
    )
    assert result is diag.FAILED
    assert "requires a protected private ACL" in capsys.readouterr().out


def test_suppressed_native_exception_context_is_reported(capsys):
    def wrapped():
        try:
            raise OSError(32, "sharing violation")
        except OSError:
            raise diag.win.AtsError(
                "Windows private proposal storage is unavailable or unsafe."
            ) from None

    report = diag.Report()
    report.check("wrapped", wrapped)
    output = capsys.readouterr().out
    assert '"errno": 32' in output
    assert "sharing violation" in output
    assert "Windows private proposal storage" in output


def test_getsecurityinfo_direct_code_preserved_when_getlasterror_is_stale(monkeypatch, capsys):
    monkeypatch.setattr(diag.c, "get_last_error", lambda: 0, raising=False)
    monkeypatch.setattr(diag.c, "set_last_error", lambda value: None, raising=False)
    monkeypatch.setattr(
        diag.c, "FormatError", lambda value: f"Windows error {value}", raising=False
    )
    api = object.__new__(diag.TracedWin32)
    api.a = SimpleNamespace(GetSecurityInfo=Mock(return_value=5))
    api.bind(api.a, "GetSecurityInfo", [], diag.win.D)
    report = diag.Report()
    report.api = api
    report.check("Win32.private", lambda: api.private(123))
    output = capsys.readouterr().out
    assert '"windows_error_code": 5' in output
    assert '"GetLastError": 0' in output
    assert "GetSecurityInfo" in output


def test_directory_and_document_checks_do_not_write_or_read_contents(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(diag, "acl_details", lambda api, handle: acl())
    report = diag.Report()
    diag.validate_directory(api, ROOT, report)
    store = diag.win.WindowsStore(api)
    api.files[str(PureWindowsPath(GUID) / "JobmitraData" / "proposals" / KEY)] = (
        b"PRIVATE_CONTENT_MUST_NOT_BE_READ"
    )
    result = diag.validate_document(store, ROOT, KEY)
    assert result["contents_read"] is False and result["hard_links"] == 1
    assert report.failures == 0
    assert not any(event[0] in {"write", "read", "delete", "mkdir"} for event in api.events)
    assert all(not event[3] and not event[4] for event in api.events if event[0] == "open")
    assert not api.held


def test_default_main_is_read_only_and_sampling_keeps_ancestors_pinned(monkeypatch, capsys):
    api = FakeApi()
    api.files[str(PureWindowsPath(GUID) / "JobmitraData" / "proposals" / KEY)] = b"SECRET_PDF_BYTES"

    @contextmanager
    def scan(root):
        assert len(api.held) == 3  # Drive, JobmitraData, proposals remain pinned.
        yield iter([SimpleNamespace(name=KEY)])

    monkeypatch.setattr(diag, "os", SimpleNamespace(name="nt", scandir=scan))
    monkeypatch.setattr(diag, "TracedWin32", lambda: api)
    monkeypatch.setattr(diag.storage, "checked_root", lambda root: ROOT)
    monkeypatch.setattr(diag, "acl_details", lambda api, handle: acl())
    settings = SimpleNamespace(
        unified_v12_proposals_enabled=True,
        unified_v12_proposal_storage_root=ROOT,
        ats_v2_resume_storage_root=PureWindowsPath(r"D:\JobmitraData\resumes"),
    )
    monkeypatch.setattr(
        diag, "configuration", lambda *args: (settings, {"nssm": {"account": "LocalSystem"}})
    )
    assert diag.main([]) == 0
    output = capsys.readouterr().out
    assert "mode=read-only" in output
    assert "SECRET_PDF_BYTES" not in output
    assert not any(event[0] in {"write", "read", "delete", "mkdir"} for event in api.events)
    assert not api.held


def test_acl_inspection_reports_inherited_and_explicit_rules(monkeypatch):
    api = object.__new__(diag.win.Win32)
    descriptor = diag.win.Acl()
    descriptor.count = 2
    buffers = [ctypes.create_string_buffer(20) for _ in range(2)]
    for index, ace in enumerate(buffers):
        ctypes.c_ubyte.from_buffer(ace).value = 0
        ctypes.c_ubyte.from_buffer(ace, 1).value = 0x10 if index else 0x03
        ctypes.c_uint16.from_buffer(ace, 2).value = 20
        diag.win.D.from_buffer(ace, 4).value = 0x1F01FF

    def security(handle, kind, flags, owner, group, dacl, sacl, out):
        ctypes.cast(owner, ctypes.POINTER(diag.win.P)).contents.value = 123
        ctypes.cast(dacl, ctypes.POINTER(diag.win.P)).contents.value = ctypes.addressof(descriptor)
        ctypes.cast(out, ctypes.POINTER(diag.win.P)).contents.value = 456
        return 0

    def control(sd, out, revision):
        ctypes.cast(out, ctypes.POINTER(ctypes.c_uint16)).contents.value = 0x1000
        return True

    def get_ace(dacl, index, out):
        ctypes.cast(out, ctypes.POINTER(diag.win.P)).contents.value = ctypes.addressof(
            buffers[index]
        )
        return True

    freed = Mock()
    api.k = SimpleNamespace(LocalFree=freed)
    api.a = SimpleNamespace(
        GetSecurityInfo=security,
        GetSecurityDescriptorControl=control,
        GetAce=get_ace,
        IsValidSid=lambda sid: True,
        GetLengthSid=lambda sid: 12,
    )
    monkeypatch.setattr(api, "sid", lambda sid: diag.win.SYSTEM)
    result = diag.acl_details(api, 1)
    assert result["protected"] and result["owner_sid"] == diag.win.SYSTEM
    assert [rule["inherited"] for rule in result["rules"]] == [False, True]
    assert result["policy_entries"] == [(0, 0x1F01FF, diag.win.SYSTEM)] * 2
    freed.assert_called_once()


@pytest.mark.parametrize("attack", ["reparse", "owner", "hardlink"])
def test_actual_application_validation_refuses_unsafe_objects(attack):
    api = FakeApi(attack)
    store = diag.win.WindowsStore(api)
    api.files[str(PureWindowsPath(GUID) / "JobmitraData" / "proposals" / KEY)] = b"private"
    with pytest.raises(diag.win.AtsError):
        diag.validate_document(store, ROOT, KEY)
    assert not any(event[0] in {"write", "read", "delete", "mkdir"} for event in api.events)
    assert not api.held


def test_probe_round_trip_and_cleanup_are_confined_to_new_disposable_directory():
    api = FakeApi()
    existing = str(PureWindowsPath(GUID) / "JobmitraData" / "proposals" / KEY)
    api.files[existing] = b"historical proposal must remain intact"
    report = diag.Report()
    diag.write_probe(diag.win.WindowsStore(api), ROOT, report)
    assert report.failures == 0
    assert api.files == {existing: b"historical proposal must remain intact"}
    assert not api.created and not api.held
    for event in api.events:
        if event[0] in {"write", "read", "delete", "mkdir"}:
            assert "\\jobmitra-storage-diagnostic-" in event[1]


def test_probe_collision_fails_without_using_or_deleting_existing_directory(monkeypatch):
    monkeypatch.setattr(diag.c, "get_last_error", lambda: 183, raising=False)
    api = FakeApi("collision")
    with pytest.raises(OSError) as error:
        diag.write_probe(diag.win.WindowsStore(api), ROOT, diag.Report())
    assert error.value.errno == 183
    assert not api.files and not api.held
    assert not any(event[0] in {"write", "read", "delete"} for event in api.events)


@pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows fail-closed check")
def test_native_diagnostic_refuses_to_claim_mac_simulation_is_windows(capsys):
    assert diag.main([]) == 1
    assert "Native Windows is required" in capsys.readouterr().out
