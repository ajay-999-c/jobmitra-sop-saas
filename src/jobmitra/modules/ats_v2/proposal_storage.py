"""Private immutable proposal bytes; platform-specific handle/ACL enforcement."""

import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from .common import AtsError

# Explicit dispatch is also the seam for Windows API simulations on macOS.
PLATFORM = os.name


def checked_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9-]{36}\.pdf", key):
        raise AtsError("Invalid private document reference.", 503)
    return key


def checked_root(root):
    if root is None:
        raise AtsError("Configure private proposal storage.", 503)
    root = Path(root)
    if (
        not root.is_absolute()
        or ".." in root.parts
        or {"static", "templates"} & {p.casefold() for p in root.parts}
    ):
        raise AtsError("Proposal storage requires an absolute private directory.", 503)
    return root


def _private(info, directory=False):
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not correct_type
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or (not directory and info.st_nlink != 1)
    ):
        raise AtsError("Proposal storage ownership or permissions are unsafe.", 503)


@contextmanager
def _posix_root(root, create=False):
    """Walk via directory descriptors: no ancestor/leaf symlinks or path races."""
    fd = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(root.anchor, flags)
        for part in root.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        _private(os.fstat(fd), directory=True)
        yield fd
    except (OSError, AttributeError):
        raise AtsError("Private proposal storage is unavailable or unsafe.", 503) from None
    finally:
        if fd is not None:
            os.close(fd)


def _windows():
    from .proposal_windows import WindowsStore

    return WindowsStore()


def publish(root, key, blob):
    root, key = checked_root(root), checked_key(key)
    if PLATFORM == "nt":
        _windows().publish(root, key, blob)
    elif PLATFORM == "posix":
        with _posix_root(root, create=True) as directory:
            fd = None
            try:
                fd = os.open(
                    key,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory,
                )
                _private(os.fstat(fd))
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(blob)
                    stream.flush()
                    os.fsync(fd)
                os.fsync(directory)
            except Exception:
                if fd is not None:
                    # Unlink only the inode created by this operation, via the pinned directory.
                    current = os.stat(key, dir_fd=directory, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (
                        os.fstat(fd).st_dev,
                        os.fstat(fd).st_ino,
                    ):
                        os.unlink(key, dir_fd=directory)
                raise
            finally:
                if fd is not None:
                    os.close(fd)
    else:
        raise AtsError("Secure proposal storage is unavailable on this platform.", 503)
    return root / key


def read(root, key, limit):
    root, key = checked_root(root), checked_key(key)
    if PLATFORM == "nt":
        return _windows().read(root, key, limit)
    if PLATFORM != "posix":
        raise AtsError("Secure proposal storage is unavailable on this platform.", 503)
    with _posix_root(root) as directory:
        fd = os.open(
            key, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(fd, "rb") as stream:
            _private(os.fstat(stream.fileno()))
            return stream.read(limit)


def remove(root, key):
    """Only for proven-unreferenced keys, never historical/uncertain database references."""
    root, key = checked_root(root), checked_key(key)
    if PLATFORM == "nt":
        _windows().remove(root, key)
    elif PLATFORM == "posix":
        with _posix_root(root) as directory:
            info = os.stat(key, dir_fd=directory, follow_symlinks=False)
            _private(info)
            os.unlink(key, dir_fd=directory)
            os.fsync(directory)
    else:
        raise AtsError("Secure proposal storage is unavailable on this platform.", 503)
