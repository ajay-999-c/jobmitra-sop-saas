"""Provision isolated V12 development; optionally clone the sealed PostgreSQL snapshot.

Source proof is the private final report from the verified staging migration.
The sealed schema and public tables are read and fingerprinted, never altered.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from stage_v12_postgres import public_fingerprint, require, row_sha

from jobmitra.core.config import Settings
from jobmitra.modules.ats_v2.postgres import (
    SQL_FILES,
    TABLES,
    checked_schema,
    validate_configuration,
    version_digest,
)

METADATA = {"backend_versions", "development_source_records"}
AUDITED_TABLES = TABLES - {t for t in TABLES if t.startswith("v_")} - METADATA
COPY_ORDER = [
    "candidates",
    "companies",
    "job_descriptions",
    "jd_interview_rounds",
    "jd_candidates",
    "candidate_resumes",
    "candidate_activities",
    "recruitment_events",
    "company_audit_events",
    "candidate_profile_versions",
    "company_proposals",
    "company_proposal_signed_documents",
    "company_proposal_status_events",
]
AUDITED_MASTERS = {
    "candidates",
    "companies",
    "job_descriptions",
    "jd_interview_rounds",
    "jd_candidates",
    "candidate_resumes",
    "candidate_activities",
}


def sealed_fingerprint(conn, proof):
    require(public_fingerprint(conn) == proof["public_after"], "Legacy public fingerprint drift")
    guards = conn.execute("""SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='jobmitra_v12_stage'
        AND t.tgname='freeze_snapshot' AND t.tgenabled='O'""").fetchone()[0]
    require(guards == 16, "Sealed snapshot guard mismatch")
    summary = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for table in sorted(AUDITED_TABLES):
            rows = cur.execute(
                sql.SQL("SELECT * FROM jobmitra_v12_stage.{}").format(sql.Identifier(table))
            ).fetchall()
            actual = {str(r["id"]): row_sha(r) for r in rows}
            expected = dict(
                conn.execute(
                    "SELECT source_pk,target_sha256 FROM "
                    "jobmitra_v12_stage.source_identity_map WHERE table_name=%s",
                    (table,),
                ).fetchall()
            )
            require(
                actual == expected and len(rows) == proof["application_counts"][table],
                f"Sealed source checksum mismatch: {table}",
            )
            summary[table] = actual
    summary["__metadata__"] = {}
    for table in ["migration_versions", "source_identity_map", "document_manifest"]:
        payloads = [
            r[0]
            for r in conn.execute(
                sql.SQL("SELECT row_to_json(t)::text FROM jobmitra_v12_stage.{} t").format(
                    sql.Identifier(table)
                )
            )
        ]
        summary["__metadata__"][table] = {
            "count": len(payloads),
            "sha256": hashlib.sha256("\n".join(sorted(payloads)).encode()).hexdigest(),
        }
    return summary


def clone_snapshot(conn, schema):
    """Server-side PG -> PG copy; no SQLite is opened and no audit is synthesized."""
    for table in COPY_ORDER:
        columns = [
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='jobmitra_v12_stage' AND table_name=%s "
                "ORDER BY ordinal_position",
                (table,),
            )
        ]
        names = sql.SQL(",").join(map(sql.Identifier, columns))
        conn.execute(
            sql.SQL(
                "INSERT INTO {}.{} ({}) SELECT {} FROM jobmitra_v12_stage.{} ORDER BY id"
            ).format(
                sql.Identifier(schema), sql.Identifier(table), names, names, sql.Identifier(table)
            )
        )
        with conn.cursor(row_factory=dict_row) as cur:
            actual = cur.execute(
                sql.SQL("SELECT {} FROM {}.{}").format(
                    names, sql.Identifier(schema), sql.Identifier(table)
                )
            ).fetchall()
        expected = dict(
            conn.execute(
                "SELECT source_pk,target_sha256 FROM "
                "jobmitra_v12_stage.source_identity_map WHERE table_name=%s",
                (table,),
            )
        )
        require(
            {str(r["id"]): row_sha(r) for r in actual} == expected,
            f"PostgreSQL clone field reconciliation failed: {table}",
        )
        sequence = conn.execute(
            "SELECT pg_get_serial_sequence(%s,'id')", (schema + "." + table,)
        ).fetchone()[0]
        if sequence:
            maximum = max([r["id"] for r in actual], default=0)
            conn.execute(
                "SELECT setval(%s::regclass,%s,false)",
                (sequence, max(maximum + 1, 4294967296 if table == "candidates" else 1)),
            )
    conn.execute(
        sql.SQL(
            "INSERT INTO {}.development_source_records "
            "SELECT * FROM jobmitra_v12_stage.source_identity_map"
        ).format(sql.Identifier(schema))
    )


def provision(conn, schema, *, clone_verified_stage=False):
    """Transaction is caller-owned; any failure rolls back all new objects."""
    checked_schema(schema)
    require(
        conn.execute("SELECT has_database_privilege(current_database(),'CREATE')").fetchone()[0],
        "Role lacks schema provisioning permission",
    )
    require(
        not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone(),
        "Development schema already exists; no overwrite permitted",
    )
    package = Path(__file__).resolve().parents[1] / "src/jobmitra/modules/ats_v2"
    for name in SQL_FILES:
        conn.execute((package / name).read_text().replace("__V12_SCHEMA__", schema), prepare=False)
    if clone_verified_stage:
        clone_snapshot(conn, schema)
    for table in sorted(AUDITED_TABLES | METADATA):
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE INSERT OR UPDATE OR DELETE ON {}.{} "
                "FOR EACH ROW EXECUTE FUNCTION {}.guard_record()"
            ).format(
                sql.Identifier("v12_guard_" + table),
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(schema),
            )
        )
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER v12_no_truncate BEFORE TRUNCATE ON {}.{} "
                "FOR EACH STATEMENT EXECUTE FUNCTION {}.guard_record()"
            ).format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(schema))
        )
    for table in sorted(AUDITED_MASTERS):
        conn.execute(
            sql.SQL(
                "CREATE TRIGGER {} AFTER INSERT OR UPDATE ON {}.{} "
                "FOR EACH ROW EXECUTE FUNCTION {}.audit_record()"
            ).format(
                sql.Identifier("v12_audit_" + table),
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(schema),
            )
        )
    conn.execute(
        sql.SQL("INSERT INTO {}.backend_versions VALUES (1,%s,'ISOLATED_DEVELOPMENT')").format(
            sql.Identifier(schema)
        ),
        (version_digest(),),
    )
    counts = {}
    for table in AUDITED_TABLES:
        count = conn.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        ).fetchone()[0]
        if not clone_verified_stage:
            require(count == 0, "Empty development provisioning must not import records")
        counts[table] = count
    return counts


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-proof", required=True, type=Path)
    p.add_argument("--trusted-office-lan", action="store_true")
    p.add_argument(
        "--clone-verified-stage",
        action="store_true",
        help="Server-side copy from sealed PG snapshot; never reads SQLite",
    )
    args = p.parse_args()
    settings = Settings()
    validate_configuration(settings)
    require(
        settings.db_sslmode == "verify-full" or args.trusted_office_lan,
        "Require verified TLS or an explicitly confirmed trusted office LAN",
    )
    proof = json.loads(args.source_proof.read_text())
    require(
        proof["public_full_data_unchanged"] and proof["all_13_tables_field_checksums_match"],
        "Verified staging proof is required",
    )
    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        sslmode="disable" if args.trusted_office_lan else settings.db_sslmode,
        connect_timeout=5,
        autocommit=True,
        options="-c timezone=UTC -c lock_timeout=10000 -c statement_timeout=30000",
    ) as conn:
        identity = conn.execute(
            "SELECT host(inet_server_addr()),inet_server_port(),"
            "current_database(),current_user,version()"
        ).fetchone()
        require(list(identity) == proof["server"], "Source proof/server identity mismatch")
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY, ISOLATION LEVEL REPEATABLE READ")
            before = sealed_fingerprint(conn, proof)
        with conn.transaction():
            counts = provision(
                conn, settings.v12_postgres_schema, clone_verified_stage=args.clone_verified_stage
            )
            require(
                sealed_fingerprint(conn, proof) == before,
                "Protected snapshot changed during provisioning",
            )
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY, ISOLATION LEVEL REPEATABLE READ")
            require(sealed_fingerprint(conn, proof) == before, "Post-provision protected drift")
    os.umask(0o077)
    result = {
        "development_schema": settings.v12_postgres_schema,
        "application_rows": sum(counts.values()),
        "table_counts": counts,
        "source": "POSTGRESQL_STAGE_SERVER_SIDE_COPY" if args.clone_verified_stage else "EMPTY",
        "public_and_sealed_snapshot_unchanged": True,
        "definition_sha256": version_digest(),
    }
    out = args.source_proof.parent / (settings.v12_postgres_schema + "-provision.json")
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
