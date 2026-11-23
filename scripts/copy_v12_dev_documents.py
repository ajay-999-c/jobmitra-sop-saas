"""Copy only verified document bytes to separate PostgreSQL development storage.

No database writes, path rewriting, original deletion or missing-file fabrication.
Source-root overrides support a verified portable manifest on Windows.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import text
from stage_v12_postgres import require, sha_file

from jobmitra.core.config import Settings
from jobmitra.modules.ats_v2 import proposal_storage, resume_storage
from jobmitra.modules.ats_v2.postgres import build_postgres_engine, validate_postgres


def copy_documents(settings, proof_path, manifest_path, resume_source=None, proposal_source=None):
    proof = json.loads(proof_path.read_text())
    require(
        sha_file(manifest_path) == proof["backup_verification"]["document_manifest_sha256"],
        "Private document manifest checksum mismatch",
    )
    documents = json.loads(manifest_path.read_text())
    engine = build_postgres_engine(settings)
    result = {
        "copied": 0,
        "skipped_existing_identical": 0,
        "unresolved_historical": 0,
        "metadata_only": 0,
    }
    try:
        validate_postgres(engine)
        for document in documents:
            table, record = document["table"], document["record"]
            require(
                table
                in {"candidate_resumes", "company_proposals", "company_proposal_signed_documents"},
                "Unknown document manifest table",
            )
            with engine.connect() as conn:
                target = dict(
                    conn.execute(text(f"SELECT * FROM {table} WHERE id=:id"), {"id": record["id"]})
                    .mappings()
                    .one()
                )
            require(
                all(target.get(k) == v for k, v in record.items() if k != "physical_file"),
                "Development document metadata does not match the verified snapshot",
            )
            physical = record["physical_file"]
            if not physical["exists"]:
                if record.get("legacy_source_table") in {
                    "candidate_resumes",
                    "candidate_documents",
                }:
                    result["unresolved_historical"] += 1
                else:
                    result["metadata_only"] += 1
                continue
            resume = table == "candidate_resumes"
            source = Path((resume_source if resume else proposal_source) or physical["source_root"])
            destination = (
                settings.ats_v2_resume_storage_root
                if resume
                else settings.unified_v12_proposal_storage_root
            )
            require(destination is not None, "Configure separate private development storage")
            destination = destination.expanduser().absolute()
            source = source.expanduser().absolute()
            require(
                not destination.resolve().is_relative_to(source.resolve())
                and not source.resolve().is_relative_to(destination.resolve()),
                "Development storage must be disjoint from the original document root",
            )
            key = record.get("storage_path") or record.get("pdf_key") or record.get("storage_key")
            if resume:
                blob = resume_storage.read(source, key, 100 * 1024 * 1024 + 1)
            else:
                blob = proposal_storage.read(source, key, 10 * 1024 * 1024 + 1)
            require(
                len(blob) == physical["size"]
                and hashlib.sha256(blob).hexdigest() == physical["sha256"],
                "Source document byte/hash mismatch",
            )
            if (destination / key).exists():
                existing = (
                    resume_storage.read(destination, key, 100 * 1024 * 1024 + 1)
                    if resume
                    else proposal_storage.read(destination, key, 10 * 1024 * 1024 + 1)
                )
                require(existing == blob, "Existing development document conflicts; no overwrite")
                result["skipped_existing_identical"] += 1
            else:
                if resume:
                    resume_storage.publish(destination, key, blob)
                else:
                    proposal_storage.publish(destination, key, blob)
                result["copied"] += 1
            actual = (
                resume_storage.read(destination, key, 100 * 1024 * 1024 + 1)
                if resume
                else proposal_storage.read(destination, key, 10 * 1024 * 1024 + 1)
            )
            require(actual == blob, "Published development document reconciliation failed")
        return result
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-proof", required=True, type=Path)
    parser.add_argument("--document-manifest", required=True, type=Path)
    parser.add_argument("--source-resume-root", type=Path)
    parser.add_argument("--source-proposal-root", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = copy_documents(
        Settings(),
        args.source_proof,
        args.document_manifest,
        args.source_resume_root,
        args.source_proposal_root,
    )
    os.umask(0o077)
    args.report.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
