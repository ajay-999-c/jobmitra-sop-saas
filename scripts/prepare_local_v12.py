"""Explicit copy-only V12 setup. No empty initialization or production cutover."""

import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from pydantic import ValidationError

from jobmitra.core.config import Settings
from jobmitra.core.local_v12 import LOCAL_ROOT
from jobmitra.modules.ats_v2 import profile_store, proposal_store, registration_store
from jobmitra.modules.ats_v2.database import build_ats_engine, upgrade_unified, validate
from jobmitra.modules.ats_v2.master_import import local_state, preserve_existing


def ordinary(path):
    for part in [path, *path.parents]:
        info = part.lstat()
        if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RuntimeError("Setup refuses symbolic links, junctions and reparse points.")


def private_directory(path):
    if os.name == "nt":
        from jobmitra.modules.ats_v2.proposal_windows import Win32

        api = Win32()
        with api.security() as security:
            api.check(api.k.CreateDirectoryW(str(path), ctypes.byref(security)))
        with api.open(path, directory=True) as handle:
            api.info(handle, directory=True)
            api.volume(handle)
            api.private(handle)
    else:
        path.mkdir(mode=0o700)


def write_private(path, chunks):
    if os.name == "nt":
        from jobmitra.modules.ats_v2.proposal_windows import Win32

        api = Win32()
        with api.open(path, create=True) as handle:
            for chunk in chunks:
                api.write(handle, chunk)
    else:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            for chunk in chunks:
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())


def copy_files(source, target):
    private_directory(target)
    copied = {}
    if source is None:
        return copied

    def unreadable(error):
        raise RuntimeError(
            "A source document directory could not be read; setup stopped."
        ) from error

    for current, directories, files in os.walk(source, followlinks=False, onerror=unreadable):
        current = Path(current)
        for name in directories:
            directory = current / name
            ordinary(directory)
            private_directory(target / directory.relative_to(source))
        for name in files:
            path = current / name
            ordinary(path)
            if not path.is_file():
                raise RuntimeError("Source storage contains a non-regular document.")
            destination = target / path.relative_to(source)
            with path.open("rb") as stream:
                write_private(destination, iter(lambda: stream.read(1024 * 1024), b""))
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            if digest != hashlib.sha256(path.read_bytes()).hexdigest():
                raise RuntimeError("A source document changed during copying; setup stopped.")
            copied[str(path.relative_to(source))] = digest
    return copied


def prepare(source, roots, target=LOCAL_ROOT):
    source, target = Path(source), Path(target)
    if not source.is_absolute() or not source.is_file():
        raise RuntimeError("Provide the actual existing populated Windows ATS SQLite path.")
    ordinary(source)
    if target.exists() or target.is_symlink():
        raise RuntimeError("Local V12 destination already exists; nothing was overwritten.")
    for path in roots.values():
        if path is not None:
            if not path.is_absolute() or not path.is_dir():
                raise RuntimeError("A configured source document directory is missing or relative.")
            ordinary(path)
            if target.resolve().is_relative_to(path.resolve()):
                raise RuntimeError(
                    "The development copy must be outside its source document roots."
                )
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        original.execute("PRAGMA query_only=ON")
        version = original.execute("PRAGMA user_version").fetchone()[0]
        appid = original.execute("PRAGMA application_id").fetchone()[0]
        if version not in {2, 3} or appid != 1246576980:
            raise RuntimeError(
                "Source must be the recognized ATS V2 or V3 database; no copy created."
            )
        if not original.execute(
            "SELECT (SELECT count(*) FROM candidates)+(SELECT count(*) FROM companies)"
        ).fetchone()[0]:
            raise RuntimeError("Source is empty; this setup only copies existing populated data.")
        resume_files = original.execute(
            "SELECT count(*) FROM candidate_resumes WHERE storage_path IS NOT NULL"
        ).fetchone()[0]
        proposals = original.execute(
            "SELECT 1 FROM sqlite_master WHERE name='company_proposals'"
        ).fetchone()
        if resume_files and roots.get("resumes") is None:
            raise RuntimeError(
                "Existing resume versions require their configured source storage root."
            )
        if (
            proposals
            and original.execute("SELECT count(*) FROM company_proposals").fetchone()[0]
            and roots.get("proposal-documents") is None
        ):
            raise RuntimeError("Existing proposals require their configured source storage root.")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ordinary(target.parent)
        private_directory(target)  # Exclusive creation; never reuse an old/partial destination.
        write_private(target / ".preparing", [b"Incomplete local data copy. Do not start V12 yet."])
        database = target / "ats-v3.sqlite3"
        write_private(database, [])
        with sqlite3.connect(database) as copy:
            original.backup(copy)  # WAL-aware committed snapshot; source remains read-only.
    engine = build_ats_engine(database)
    try:
        validate(engine)
        with engine.connect() as conn:
            before = local_state(conn)
            original_tables = {}
            for name in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).scalars():
                quoted = '"' + name.replace('"', '""') + '"'
                columns = [
                    row[1] for row in conn.exec_driver_sql("PRAGMA table_info(" + quoted + ")")
                ]
                original_tables[name] = (
                    columns,
                    sorted(map(repr, conn.exec_driver_sql("SELECT * FROM " + quoted).fetchall())),
                )
        if version == 2:
            upgrade_unified(engine)  # Only the newly reserved development copy.
        for extension in [profile_store, proposal_store, registration_store]:
            extension.install(engine)
        validate(engine)
        with engine.connect() as conn:
            preserve_existing(conn, before)
            for name, (columns, rows) in original_tables.items():

                def quote(value):
                    return '"' + value.replace('"', '""') + '"'

                selected = ",".join(quote(column) for column in columns)
                actual = conn.exec_driver_sql("SELECT " + selected + " FROM " + quote(name))
                if sorted(map(repr, actual.fetchall())) != rows:
                    raise RuntimeError("An original row changed in the development copy.")
            if (
                conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok"
                or conn.exec_driver_sql("PRAGMA foreign_key_check").first()
            ):
                raise RuntimeError("Development-copy integrity verification failed.")
        documents = {name: copy_files(path, target / name) for name, path in roots.items()}
        report = {
            "source": str(source),
            "source_version": version,
            "development_copy": str(database),
            "version": 3,
            "original_rows_preserved": True,
            "source_opened_read_only": True,
            "counts": {name: len(rows) for name, rows in before.items()},
            "documents": documents,
        }
        write_private(target / "preparation-report.json", [json.dumps(report, indent=2).encode()])
        (target / ".preparing").unlink()  # Startup is allowed only after every verification passes.
        return report
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-config",
        action="store_true",
        required=True,
        help="Read existing Windows SQLite/document paths from its own .env",
    )
    parser.parse_args()
    try:
        config = Settings()
    except ValidationError:
        parser.error("Existing Windows .env configuration is incomplete; no data was copied.")
    if config.ats_v2_database is None:
        parser.error(
            "No ATS SQLite source is configured. Set JOBMITRA_ATS_V2_DATABASE to the real "
            "populated database; do not initialize an empty replacement."
        )
    roots = {
        "resumes": config.ats_v2_resume_storage_root,
        "proposal-documents": config.unified_v12_proposal_storage_root,
        "legacy-documents": config.document_storage_root,
    }
    try:
        result = prepare(config.ats_v2_database, roots)
    except (OSError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps({k: v for k, v in result.items() if k != "documents"}, indent=2))


if __name__ == "__main__":
    main()
