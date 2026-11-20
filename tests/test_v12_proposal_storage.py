"""Proposal storage only: real POSIX checks, mocked Windows policy, opt-in native Windows."""

import ctypes
import hashlib
import os
import subprocess
from contextlib import contextmanager
from pathlib import PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from jobmitra.modules.ats_v2 import proposal_documents as docs
from jobmitra.modules.ats_v2 import proposal_storage as storage
from jobmitra.modules.ats_v2 import proposal_windows as win
from jobmitra.modules.ats_v2.common import AtsError

KEY = "00000000-0000-0000-0000-000000000001.pdf"
BLOB = b"%PDF-synthetic-private-bytes\n%%EOF"
ACTOR = "S-1-5-21-100-200-300-1001"
ROOT = PureWindowsPath(r"C:\private\proposals")
GUID = r"\\?\Volume{00000000-0000-0000-0000-000000000001}"


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX filesystem test")
@pytest.mark.parametrize(
    "attack",
    [
        "ancestor_symlink",
        "root_symlink",
        "leaf_symlink",
        "hardlink",
        "public_root",
        "public_file",
        "fifo",
    ],
)
def test_posix_unsafe_paths_fail_closed_without_modifying_targets(tmp_path, attack):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    victim = outside / KEY
    victim.write_bytes(BLOB)
    victim.chmod(0o600)
    if attack == "ancestor_symlink":
        (tmp_path / "shortcut").symlink_to(outside, target_is_directory=True)
        root = tmp_path / "shortcut" / "nested"
    elif attack == "root_symlink":
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
    elif attack == "leaf_symlink":
        (root / KEY).symlink_to(victim)
    elif attack == "hardlink":
        os.link(victim, root / KEY)
    elif attack == "public_root":
        root.chmod(0o755)
    elif attack == "public_file":
        (root / KEY).write_bytes(BLOB)
        (root / KEY).chmod(0o644)
    else:
        os.mkfifo(root / KEY, 0o600)
    with pytest.raises((AtsError, OSError)):
        storage.read(root, KEY, 1000)
    with pytest.raises((AtsError, OSError)):
        storage.publish(root, KEY, b"replacement")
    assert victim.read_bytes() == BLOB
    assert not (outside / "nested").exists()


@pytest.mark.skipif(os.name != "posix", reason="Real POSIX filesystem test")
def test_posix_exclusive_creation_hash_size_and_cleanup(tmp_path, monkeypatch):
    root = tmp_path / "private"
    path = storage.publish(root, KEY, BLOB)
    checksum = hashlib.sha256(BLOB).hexdigest()
    assert docs._read(root, KEY, checksum, len(BLOB)) == BLOB
    with pytest.raises(AtsError):
        storage.publish(root, KEY, b"overwrite")
    assert path.read_bytes() == BLOB
    for size, digest in [(len(BLOB) + 1, checksum), (len(BLOB), "0" * 64)]:
        with pytest.raises(AtsError):
            docs._read(root, KEY, digest, size)
    next_key = str(uuid4()) + ".pdf"
    monkeypatch.setattr(storage.os, "fsync", Mock(side_effect=OSError("simulated disk failure")))
    with pytest.raises(AtsError):
        storage.publish(root, next_key, BLOB)
    assert not (root / next_key).exists()
    assert path.read_bytes() == BLOB


@pytest.mark.parametrize(
    "key",
    [
        "../outside.pdf",
        r"..\outside.pdf",
        "C:other.pdf",
        "/tmp/other.pdf",
        KEY + ":stream",
        KEY + " ",
        "bad.pdf",
        None,
    ],
)
def test_traversal_and_alternate_streams_rejected(tmp_path, key):
    with pytest.raises(AtsError):
        storage.publish(tmp_path / "private", key, BLOB)
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize(
    "root",
    [
        r"\\server\share\proposals",
        r"\\?\C:\private",
        r"C:relative",
        "C:\\",
        r"C:\private\..\other",
        r"C:\private\name.",
        r"C:\private\name ",
        r"C:\private\stream:ads",
        r"C:\private\NUL",
    ],
)
def test_windows_device_unc_and_ambiguous_paths_refused(root):
    with pytest.raises(AtsError):
        win.path_parts(root)


@pytest.mark.parametrize(
    "owner,protected,entries",
    [
        ("S-1-1-0", True, [(0, 1, ACTOR)]),
        (ACTOR, False, [(0, 1, ACTOR)]),
        (ACTOR, True, []),
        (ACTOR, True, [(0, 1, "S-1-1-0")]),
        (ACTOR, True, [(0, 1, "S-1-5-32-545")]),
        (ACTOR, True, [(5, 1, ACTOR)]),
    ],
)
def test_windows_public_or_unknown_acl_fails_closed(owner, protected, entries):
    with pytest.raises(AtsError):
        win.private_acl(owner, protected, entries, ACTOR)


def test_windows_private_acl_and_structure_sizes():
    win.private_acl(
        ACTOR,
        True,
        [
            (0, 0x1F01FF, ACTOR),
            (0, 0x1F01FF, win.SYSTEM),
            (0, 0x1F01FF, win.ADMINS),
            (1, 1, "S-1-1-0"),
        ],
        ACTOR,
    )
    assert ctypes.sizeof(win.Info) == 52
    assert ctypes.sizeof(win.SecurityAttributes) == (
        24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12
    )


@pytest.mark.parametrize(
    "attributes,links,directory",
    [
        (win.REPARSE, 1, False),
        (win.DIRECTORY | win.REPARSE, 1, True),
        (0, 2, False),
        (win.DIRECTORY, 1, False),
        (0, 1, True),
    ],
)
def test_windows_handle_metadata_rejects_junctions_hardlinks_and_wrong_types(
    attributes, links, directory
):
    api = object.__new__(win.Win32)

    def information(handle, output):
        info = ctypes.cast(output, ctypes.POINTER(win.Info)).contents
        info.attributes, info.links = attributes, links
        return True

    api.k = SimpleNamespace(GetFileType=lambda h: 1, GetFileInformationByHandle=information)
    with pytest.raises(AtsError):
        api.info(10, directory=directory)


def test_windows_native_open_requests_no_follow_no_overwrite_and_no_delete_sharing():
    api = object.__new__(win.Win32)
    calls = []
    api.k = SimpleNamespace(CreateFileW=lambda *args: calls.append(args) or 123, CloseHandle=Mock())

    @contextmanager
    def security():
        yield win.SecurityAttributes()

    api.security = security
    with api.open("directory", directory=True):
        pass
    with api.open("document", create=True):
        pass
    with api.open("document"):
        pass
    directory, created, read = calls
    assert directory[2] == 1 and directory[4] == 3
    assert directory[5] & win.OPEN_REPARSE and directory[5] & win.BACKUP
    assert created[2] == 0 and created[4] == 1 and created[3] is not None
    assert created[1] & win.DELETE and created[5] & win.WRITE_THROUGH
    assert read[2] == 1 and read[4] == 3 and read[5] & win.OPEN_REPARSE
    assert api.k.CloseHandle.call_count == 3


class FakeWindowsApi:
    """API contract simulation, never presented as native Windows verification."""

    def __init__(self, fail=None):
        self.fail = fail
        self.files = {}
        self.events = []
        self.held = []

    @contextmanager
    def open(self, path, directory=False, create=False, delete=False):
        path = str(path)
        self.events.append(("open", path, directory, create, delete))
        if create:
            if path in self.files:
                raise OSError("exists")
            self.files[path] = b""
        elif not directory and path not in self.files:
            raise OSError("missing")
        self.held.append(path)
        try:
            yield path
        finally:
            self.held.remove(path)
            self.events.append(("close", path))

    def info(self, handle, directory=False):
        if self.fail in {"junction", "leaf_reparse"} and (
            directory if self.fail == "junction" else not directory
        ):
            raise AtsError("Synthetic reparse point", 503)

    def volume(self, handle):
        if self.fail == "fat":
            raise AtsError("No persistent ACL support", 503)

    def final(self, handle):
        if self.fail == "redirect" and not handle.endswith("proposals") and handle.endswith(".pdf"):
            return GUID + "\\outside\\" + KEY
        return GUID if handle == "C:\\" else handle

    def mkdir(self, path):
        self.events.append(("mkdir", path))

    def private(self, handle):
        if self.fail == "acl":
            raise AtsError("Public ACL", 503)

    def write(self, handle, blob):
        assert len(self.held) == 4  # Volume, parent, private root, exact document handle.
        self.files[handle] = blob
        if self.fail == "write":
            raise OSError("disk failure")

    def read(self, handle, limit):
        return self.files[handle][:limit]

    def delete(self, handle):
        assert handle in self.held
        self.events.append(("delete", handle))
        del self.files[handle]


def test_windows_missing_posix_flags_and_exact_byte_round_trip(monkeypatch, tmp_path):
    api = FakeWindowsApi()
    store = win.WindowsStore(api)
    # Exercise WindowsStore, while the outer dispatch uses an existing native temp path.
    # Native path validation is independently covered above and on Windows below.
    monkeypatch.setattr(win, "path_parts", lambda root: ("C:\\", ("private", "proposals")))
    monkeypatch.setattr(storage, "PLATFORM", "nt")
    monkeypatch.setattr(storage, "_windows", lambda: store)
    for name in ["O_NOFOLLOW", "O_DIRECTORY"]:
        monkeypatch.delattr(storage.os, name, raising=False)
    root = tmp_path / "private"
    storage.publish(root, KEY, BLOB)
    assert docs._read(root, KEY, hashlib.sha256(BLOB).hexdigest(), len(BLOB)) == BLOB
    with pytest.raises(AtsError):
        storage.publish(root, KEY, b"overwrite")
    assert storage.read(root, KEY, 1000) == BLOB
    storage.remove(root, KEY)
    assert api.files == {} and api.held == []


@pytest.mark.parametrize("failure", ["junction", "leaf_reparse", "redirect", "fat", "acl", "write"])
def test_windows_failed_publish_is_closed_and_cleans_exact_created_handle(failure):
    api = FakeWindowsApi(failure)
    with pytest.raises(AtsError):
        win.WindowsStore(api).publish(ROOT, KEY, BLOB)
    assert api.files == {} and api.held == []


@pytest.mark.skipif(os.name != "nt", reason="Requires native Windows; not a Mac simulation")
def test_native_windows_acl_round_trip_and_junction_refusal(tmp_path):
    root = tmp_path / "proposals"
    path = storage.publish(root, KEY, BLOB)
    assert docs._read(root, KEY, hashlib.sha256(BLOB).hexdigest(), len(BLOB)) == BLOB
    with pytest.raises(AtsError):
        storage.publish(root, KEY, b"overwrite")
    assert path.read_bytes() == BLOB
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = root / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True
    )
    assert result.returncode == 0
    try:
        with pytest.raises(AtsError):
            storage.publish(junction, str(uuid4()) + ".pdf", BLOB)
        assert not list(outside.iterdir())
    finally:
        junction.rmdir()


def test_windows_native_io_preserves_binary_bytes_across_short_writes():
    api = object.__new__(win.Win32)
    blob = BLOB + b"\x00\xff\x00binary\r\n"
    written = bytearray()

    def write(handle, buffer, size, count, overlapped):
        size = max(1, size // 2)
        written.extend(ctypes.string_at(buffer, size))
        ctypes.cast(count, ctypes.POINTER(win.D)).contents.value = size
        return True

    def read(handle, buffer, size, count, overlapped):
        ctypes.memmove(buffer, blob, len(blob))
        ctypes.cast(count, ctypes.POINTER(win.D)).contents.value = len(blob)
        return True

    flush = Mock(return_value=True)
    api.k = SimpleNamespace(WriteFile=write, ReadFile=read, FlushFileBuffers=flush)
    api.write(123, blob)
    assert bytes(written) == blob
    assert api.read(123, 1000) == blob
    flush.assert_called_once_with(123)


@pytest.mark.parametrize(
    "protected,null_acl,ace_type",
    [(True, False, 0), (False, False, 0), (True, True, 0), (True, False, 5)],
)
def test_windows_security_descriptor_marshalling_and_fail_closed(protected, null_acl, ace_type):
    api = object.__new__(win.Win32)
    acl = win.Acl()
    acl.count = 1
    ace = ctypes.create_string_buffer(20)
    ctypes.c_ubyte.from_buffer(ace).value = ace_type
    ctypes.c_uint16.from_buffer(ace, 2).value = 20
    win.D.from_buffer(ace, 4).value = 0x1F01FF
    api.actor = ACTOR
    freed = Mock()
    api.k = SimpleNamespace(LocalFree=freed)

    def security(handle, kind, flags, owner, group, dacl, sacl, descriptor):
        assert (kind, flags) == (1, 5)
        ctypes.cast(owner, ctypes.POINTER(win.P)).contents.value = 123
        ctypes.cast(dacl, ctypes.POINTER(win.P)).contents.value = (
            None if null_acl else ctypes.addressof(acl)
        )
        ctypes.cast(descriptor, ctypes.POINTER(win.P)).contents.value = 456
        return 0

    def control(descriptor, output, revision):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint16)).contents.value = (
            0x1000 if protected else 0
        )
        return True

    def get_ace(dacl, index, output):
        ctypes.cast(output, ctypes.POINTER(win.P)).contents.value = ctypes.addressof(ace)
        return True

    api.a = SimpleNamespace(
        GetSecurityInfo=security,
        GetSecurityDescriptorControl=control,
        GetAce=get_ace,
        IsValidSid=lambda p: True,
        GetLengthSid=lambda p: 12,
    )
    api.sid = lambda p: ACTOR
    if protected and not null_acl and ace_type == 0:
        api.private(10)
    else:
        with pytest.raises(AtsError):
            api.private(10)
    assert freed.call_count == 1
