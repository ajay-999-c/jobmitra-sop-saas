"""Portable, pinned-handle resume bytes; no rewriting of legacy storage keys."""

import re
from pathlib import Path, PurePosixPath

from . import proposal_storage
from .common import AtsError


def key(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-f0-9-]{32,36}\.(pdf|docx|html|json)", value
    ):
        raise AtsError("Invalid private resume key.", 422)
    return value


def parts(root, relative):
    root = proposal_storage.checked_root(root)
    if not isinstance(relative, str) or "\\" in relative:
        raise AtsError("Invalid private resume path.", 422)
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or len(path.parts) != 3
        or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", part) for part in path.parts[:-1])
    ):
        raise AtsError("Invalid private resume path.", 422)
    return root, path.parts[:-1], key(path.name)


def publish(root, relative, blob):
    root, directories, name = parts(root, relative)
    proposal_storage.ensure_private_directory(root)
    for directory in directories:
        root /= directory
        proposal_storage.ensure_private_directory(root)
    return proposal_storage.publish(root, name, blob, key_validator=key)


def read(root, relative, limit=10 * 1024 * 1024 + 1):
    root, directories, name = parts(root, relative)
    return proposal_storage.read(root / Path(*directories), name, limit, key_validator=key)


def remove(root, relative):
    root, directories, name = parts(root, relative)
    proposal_storage.remove(root / Path(*directories), name, key_validator=key)
