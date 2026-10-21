"""Private immutable document storage; no fallback root and no filename-based paths."""

import hashlib
import os
import re
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4
from xml.etree import ElementTree

from jobmitra.core.workflow import WorkflowError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str


class DocumentStorage(Protocol):
    def save(self, stream: BinaryIO, filename: str) -> StoredFile: ...
    def path(self, key: str) -> Path: ...
    def remove(self, key: str) -> None: ...


def safe_filename(filename):
    if (
        not filename
        or len(filename) > 180
        or filename in (".", "..")
        or any(c in filename for c in "/\\:")
        or any(ord(c) < 32 or ord(c) == 127 for c in filename)
    ):
        raise WorkflowError("Use a plain PDF or DOCX filename without path characters.")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx"):
        raise WorkflowError("Only PDF and DOCX files are accepted.")
    return suffix


def verify_content(path, suffix, limit):
    with path.open("rb") as handle:
        signature = handle.read(8)
        if suffix == ".pdf":
            handle.seek(max(0, path.stat().st_size - 2048))
            if not signature.startswith(b"%PDF-") or b"%%EOF" not in handle.read():
                raise WorkflowError("The file is not a recognizable PDF.")
            return PDF
    try:
        with zipfile.ZipFile(path) as archive:
            items = archive.infolist()
            names = {item.filename for item in items}
            if (
                len(items) > 2000
                or len(names) != len(items)
                or sum(item.file_size for item in items) > limit * 10
            ):
                raise ValueError
            if any(
                item.flag_bits & 1
                or item.filename.startswith("/")
                or ".." in Path(item.filename).parts
                or "\\" in item.filename
                or item.filename.lower().endswith("vbaproject.bin")
                for item in items
            ):
                raise ValueError
            for name in ("[Content_Types].xml", "word/document.xml"):
                if archive.getinfo(name).file_size > limit * 2:
                    raise ValueError
                data = archive.read(name)
                if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                    raise ValueError
                ElementTree.fromstring(data)
            types = archive.read("[Content_Types].xml")
            if (
                b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                not in types
            ):
                raise ValueError
        return DOCX
    except (
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        RuntimeError,
        ElementTree.ParseError,
        EOFError,
        NotImplementedError,
        zlib.error,
    ):
        raise WorkflowError("The file is not a supported, unencrypted DOCX document.") from None


class LocalDocumentStorage:
    def __init__(self, root, max_bytes):
        if root is None:
            raise WorkflowError(
                "Private document storage is not configured. Set JOBMITRA_DOCUMENT_STORAGE_ROOT.",
                503,
            )
        self.root = Path(root)
        if (
            not self.root.is_absolute()
            or self.root.is_symlink()
            or any(part.lower() in ("static", "templates") for part in self.root.parts)
        ):
            raise WorkflowError("Private storage must be an absolute non-static directory.", 503)
        if not self.root.is_dir():
            raise WorkflowError(
                "Configured private storage is missing. Create or mount it before uploading.", 503
            )
        self.root = self.root.resolve()
        if any(part.lower() in ("static", "templates") for part in self.root.parts):
            raise WorkflowError("Private storage must not resolve inside static assets.", 503)
        self.max_bytes = max_bytes

    def path(self, key):
        if not re.fullmatch(r"[0-9a-f]{32}\.(pdf|docx)", key):
            raise WorkflowError("Invalid document storage reference.", 404)
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise WorkflowError("Invalid document storage reference.", 404)
        return path

    def save(self, stream, filename):
        suffix = safe_filename(filename)
        key = uuid4().hex + suffix
        final = self.path(key)
        descriptor, temporary = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        temporary = Path(temporary)
        digest, size = hashlib.sha256(), 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                while chunk := stream.read(65536):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise WorkflowError("File exceeds the configured upload limit.", 413)
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size:
                raise WorkflowError("The uploaded file is empty.")
            content_type = verify_content(temporary, suffix, self.max_bytes)
            # Atomic publication without replacing any existing immutable version.
            os.link(temporary, final)
            return StoredFile(key, content_type, size, digest.hexdigest())
        finally:
            temporary.unlink(missing_ok=True)

    def remove(self, key):
        self.path(key).unlink(missing_ok=True)
