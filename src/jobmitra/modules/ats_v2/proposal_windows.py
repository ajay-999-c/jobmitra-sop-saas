"""Windows 10 local-NTFS proposal storage using pinned handles and private DACLs.

No pywin32 dependency, ACL shell parsing, permissive flag fallback or ACL repair.
Unknown ACLs, UNC/device paths, reparse points and unavailable APIs fail closed.
"""

import ctypes as c
import os
import re
from contextlib import ExitStack, contextmanager
from pathlib import PureWindowsPath

from .common import AtsError
from .proposal_storage import checked_key

D = c.c_uint32
P = c.c_void_p
B = c.c_int32
READ_CONTROL, DELETE = 0x20000, 0x10000
READ, WRITE = 0x80000000, 0x40000000
OPEN_REPARSE, BACKUP, WRITE_THROUGH = 0x200000, 0x2000000, 0x80000000
DIRECTORY, REPARSE = 0x10, 0x400
SYSTEM, ADMINS = "S-1-5-18", "S-1-5-32-544"


class Info(c.Structure):
    _fields_ = [
        (name, D)
        for name in (
            "attributes",
            "created_low",
            "created_high",
            "access_low",
            "access_high",
            "write_low",
            "write_high",
            "volume",
            "size_high",
            "size_low",
            "links",
            "index_high",
            "index_low",
        )
    ]


class SecurityAttributes(c.Structure):
    _fields_ = [("length", D), ("descriptor", P), ("inherit", B)]


class Acl(c.Structure):
    _fields_ = [
        ("revision", c.c_ubyte),
        ("reserved", c.c_ubyte),
        ("size", c.c_uint16),
        ("count", c.c_uint16),
        ("reserved2", c.c_uint16),
    ]


def path_parts(root):
    path = PureWindowsPath(str(root))
    if not re.fullmatch(r"[A-Za-z]:", path.drive) or path.root != "\\":
        raise AtsError("Windows proposals require an absolute local NTFS directory.", 503)
    parts = path.parts[1:]
    if not parts or any(
        part in {".", ".."}
        or part.endswith((".", " "))
        or ":" in part
        or re.search(r'[<>"|?*\x00-\x1f]', part)
        or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
        for part in parts
    ):
        raise AtsError("Windows proposal storage path is unsafe.", 503)
    return path.anchor, parts


def private_acl(owner, protected, entries, actor):
    """Accept only standard allow/deny ACEs for the actor, SYSTEM and administrators."""
    allowed = {actor, SYSTEM, ADMINS}
    if owner not in allowed or not protected or not entries:
        raise AtsError("Windows proposal storage requires a protected private ACL.", 503)
    for kind, mask, sid in entries:
        if kind not in {0, 1} or (kind == 0 and mask and sid not in allowed):
            raise AtsError("Windows proposal storage ACL grants untrusted access.", 503)


class Win32:
    """Small native API boundary; declarations use pointer-sized HANDLEs and Win32 DWORDs."""

    def __init__(self):
        if os.name != "nt":
            raise AtsError("Native Windows storage APIs are unavailable.", 503)
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.a = c.WinDLL("advapi32", use_last_error=True)
        self.bind(self.k, "CreateFileW", [c.c_wchar_p, D, D, P, D, D, P], P)
        self.bind(self.k, "CloseHandle", [P], B)
        self.bind(self.k, "LocalFree", [P], P)
        self.bind(self.k, "GetCurrentProcess", [], P)
        self.bind(self.k, "GetFileType", [P], D)
        self.bind(self.k, "GetFileInformationByHandle", [P, P], B)
        self.bind(self.k, "GetFinalPathNameByHandleW", [P, c.c_wchar_p, D, D], D)
        self.bind(self.k, "GetVolumeInformationByHandleW", [P, P, D, P, P, P, P, D], B)
        self.bind(self.k, "CreateDirectoryW", [c.c_wchar_p, P], B)
        self.bind(self.k, "WriteFile", [P, P, D, P, P], B)
        self.bind(self.k, "ReadFile", [P, P, D, P, P], B)
        self.bind(self.k, "FlushFileBuffers", [P], B)
        self.bind(self.k, "SetFileInformationByHandle", [P, D, P, D], B)
        self.bind(self.a, "OpenProcessToken", [P, D, P], B)
        self.bind(self.a, "GetTokenInformation", [P, D, P, D, P], B)
        self.bind(self.a, "ConvertSidToStringSidW", [P, P], B)
        self.bind(
            self.a,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            [c.c_wchar_p, D, P, P],
            B,
        )
        self.bind(self.a, "GetSecurityInfo", [P, D, D, P, P, P, P, P], D)
        self.bind(self.a, "GetSecurityDescriptorControl", [P, P, P], B)
        self.bind(self.a, "GetAce", [P, D, P], B)
        self.bind(self.a, "IsValidSid", [P], B)
        self.bind(self.a, "GetLengthSid", [P], D)
        self.actor = self.current_sid()

    @staticmethod
    def bind(dll, name, args, result):
        function = getattr(dll, name)  # Missing APIs fail closed, never weaken flags.
        function.argtypes, function.restype = args, result

    @staticmethod
    def check(ok):
        if not ok:
            raise OSError(c.get_last_error(), "Windows private storage operation failed")

    def sid(self, pointer):
        self.check(self.a.IsValidSid(pointer))
        text = P()
        self.check(self.a.ConvertSidToStringSidW(pointer, c.byref(text)))
        try:
            return c.wstring_at(text)
        finally:
            self.k.LocalFree(text)

    def current_sid(self):
        token, size = P(), D()
        self.check(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)))
        try:
            self.a.GetTokenInformation(token, 1, None, 0, c.byref(size))
            buffer = c.create_string_buffer(size.value)
            self.check(self.a.GetTokenInformation(token, 1, buffer, size, c.byref(size)))
            return self.sid(P.from_buffer(buffer))
        finally:
            self.k.CloseHandle(token)

    @contextmanager
    def security(self):
        descriptor = P()
        sddl = f"D:P(A;OICI;FA;;;{self.actor})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        self.check(
            self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, c.byref(descriptor), None
            )
        )
        try:
            yield SecurityAttributes(c.sizeof(SecurityAttributes), descriptor, False)
        finally:
            self.k.LocalFree(descriptor)

    @contextmanager
    def open(self, path, directory=False, create=False, delete=False):
        access = READ_CONTROL | (0x80 if directory else READ)
        if create:
            access |= WRITE | DELETE
        if delete:
            access |= DELETE
        flags = OPEN_REPARSE | (BACKUP if directory else 0) | (WRITE_THROUGH if create else 0)
        with self.security() as security:
            handle = self.k.CreateFileW(
                str(path),
                access,
                0 if create or delete else 1,
                c.byref(security) if create else None,
                1 if create else 3,
                flags,
                None,
            )
        if handle == P(-1).value or handle is None:
            self.check(False)
        try:
            yield handle
        finally:
            self.k.CloseHandle(handle)

    def mkdir(self, path):
        with self.security() as security:
            if not self.k.CreateDirectoryW(str(path), c.byref(security)):
                if c.get_last_error() != 183:  # Existing roots are validated, never re-ACL'd.
                    self.check(False)

    def info(self, handle, directory=False):
        info = Info()
        self.check(self.k.GetFileType(handle) == 1)
        self.check(self.k.GetFileInformationByHandle(handle, c.byref(info)))
        if info.attributes & REPARSE or bool(info.attributes & DIRECTORY) != directory:
            raise AtsError(
                "Windows proposal storage refuses reparse points or wrong file types.", 503
            )
        if not directory and info.links != 1:
            raise AtsError("Windows proposal storage refuses hard-linked documents.", 503)
        return info

    def final(self, handle):
        buffer = c.create_unicode_buffer(32768)
        length = self.k.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 1)
        self.check(0 < length < len(buffer))
        path = buffer.value
        if not path.startswith("\\\\?\\Volume{"):
            raise AtsError("Windows proposal storage requires a local volume.", 503)
        return path.rstrip("\\")

    def volume(self, handle):
        flags = D()
        name = c.create_unicode_buffer(32)
        self.check(
            self.k.GetVolumeInformationByHandleW(
                handle, None, 0, None, None, c.byref(flags), name, len(name)
            )
        )
        if name.value != "NTFS" or not flags.value & 8:
            raise AtsError("Windows proposals require local NTFS with persistent ACLs.", 503)

    def private(self, handle):
        owner, dacl, descriptor = P(), P(), P()
        result = self.a.GetSecurityInfo(
            handle, 1, 5, c.byref(owner), None, c.byref(dacl), None, c.byref(descriptor)
        )
        self.check(result == 0)
        try:
            control, revision = c.c_uint16(), D()
            self.check(
                self.a.GetSecurityDescriptorControl(descriptor, c.byref(control), c.byref(revision))
            )
            if not dacl:
                raise AtsError("Windows proposal storage refuses a NULL DACL.", 503)
            entries = []
            for index in range(c.cast(dacl, c.POINTER(Acl)).contents.count):
                ace = P()
                self.check(self.a.GetAce(dacl, index, c.byref(ace)))
                kind = c.c_ubyte.from_address(ace.value).value
                size = c.c_uint16.from_address(ace.value + 2).value
                if kind not in {0, 1} or size < 16:
                    raise AtsError("Unsupported Windows proposal ACL entry.", 503)
                sid = P(ace.value + 8)
                self.check(self.a.IsValidSid(sid))
                self.check(8 + self.a.GetLengthSid(sid) <= size)
                entries.append((kind, D.from_address(ace.value + 4).value, self.sid(sid)))
            private_acl(self.sid(owner), bool(control.value & 0x1000), entries, self.actor)
        finally:
            self.k.LocalFree(descriptor)

    def write(self, handle, blob):
        buffer = c.create_string_buffer(blob)
        offset = 0
        while offset < len(blob):
            count = D()
            self.check(
                self.k.WriteFile(
                    handle, c.byref(buffer, offset), len(blob) - offset, c.byref(count), None
                )
            )
            self.check(count.value > 0)
            offset += count.value
        self.check(self.k.FlushFileBuffers(handle))

    def read(self, handle, limit):
        buffer, count = c.create_string_buffer(limit), D()
        self.check(self.k.ReadFile(handle, buffer, limit, c.byref(count), None))
        return buffer.raw[: count.value]

    def delete(self, handle):
        flag = c.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile, BOOLEAN (one byte).
        self.check(self.k.SetFileInformationByHandle(handle, 4, c.byref(flag), c.sizeof(flag)))


class WindowsStore:
    def __init__(self, api=None):
        try:
            self.api = api or Win32()
        except (OSError, AttributeError):
            raise AtsError("Secure Windows proposal storage APIs are unavailable.", 503) from None

    @contextmanager
    def root(self, root, create=False):
        anchor, parts = path_parts(root)
        with ExitStack() as handles:
            # Share READ only: held ancestor handles deny write/delete/rename while traversing.
            handle = handles.enter_context(self.api.open(anchor, directory=True))
            self.api.info(handle, directory=True)
            self.api.volume(handle)
            canonical = self.api.final(handle)
            for index, part in enumerate(parts):
                expected = canonical + "\\" + part
                if create and index == len(parts) - 1:
                    # Parents must already exist. Only the new root gets an explicit private DACL.
                    self.api.mkdir(expected)
                handle = handles.enter_context(self.api.open(expected, directory=True))
                self.api.info(handle, directory=True)
                canonical = self.api.final(handle)
                if canonical.casefold() != expected.casefold():
                    raise AtsError("Windows proposal directory identity changed.", 503)
            self.api.private(handle)
            yield canonical

    @contextmanager
    def document(self, root, key, create=False, delete=False):
        key = checked_key(key)
        try:
            with self.root(root, create=create) as canonical:
                expected = canonical + "\\" + key
                with self.api.open(expected, create=create, delete=delete) as handle:
                    try:
                        self.api.info(handle)
                        self.api.private(handle)
                        if self.api.final(handle).casefold() != expected.casefold():
                            raise AtsError("Windows proposal document identity changed.", 503)
                        yield handle
                    except Exception:
                        if create:
                            self.api.delete(handle)  # Delete this exact newly created handle only.
                        raise
        except (OSError, AttributeError):
            raise AtsError(
                "Windows private proposal storage is unavailable or unsafe.", 503
            ) from None

    def publish(self, root, key, blob):
        with self.document(root, key, create=True) as handle:
            self.api.write(handle, blob)

    def read(self, root, key, limit):
        with self.document(root, key) as handle:
            return self.api.read(handle, limit)

    def remove(self, root, key):
        with self.document(root, key, delete=True) as handle:
            self.api.delete(handle)
