"""Run Stage 2 checks in a disposable PostgreSQL cluster with TCP disabled."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import psycopg

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = str(PROJECT / ".venv/bin/python")


@contextmanager
def isolated_postgres():
    server = shutil.which("postgres")
    candidates = [
        Path(os.environ.get("JOBMITRA_TEST_PG_BIN", "/nonexistent")),
        Path(server).parent if server else Path("/nonexistent"),
        Path("/opt/homebrew/opt/postgresql@18/bin"),
        Path("/usr/local/opt/postgresql@18/bin"),
    ]
    folder = next(
        (
            path
            for path in candidates
            if all((path / name).is_file() for name in ("postgres", "initdb", "pg_ctl"))
        ),
        None,
    )
    if folder is None:
        raise RuntimeError("Set JOBMITRA_TEST_PG_BIN to PostgreSQL 18 server binaries")
    initdb, pg_ctl = str(folder / "initdb"), str(folder / "pg_ctl")
    version = subprocess.run(
        [initdb, "--version"], capture_output=True, text=True, check=True
    ).stdout
    if "18." not in version:
        raise RuntimeError("PostgreSQL 18 tools required")
    with TemporaryDirectory(prefix="jobmitra-stage2-", dir="/private/tmp") as temporary:
        root = Path(temporary)
        root.chmod(0o700)
        data, socket = root / "data", root / "socket"
        socket.mkdir(mode=0o700)
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("JOBMITRA_", "PG"))
        }
        env.update(
            JOBMITRA_DB_HOST=str(socket),
            JOBMITRA_DB_PORT="5432",
            JOBMITRA_DB_NAME="jobmitra_dev",
            JOBMITRA_DB_USER="stage2_test",
            JOBMITRA_DB_PASSWORD="",
            JOBMITRA_DB_SSLMODE="disable",
            JOBMITRA_AI_ENABLED="false",
            JOBMITRA_OFFICE_TIMEZONE="Asia/Kolkata",
            JOBMITRA_STAGE2_DISPOSABLE="1",
            JOBMITRA_RUN_SCHEMA_TESTS="1",
        )
        subprocess.run(
            [
                initdb,
                "-D",
                str(data),
                "-U",
                "stage2_test",
                "-A",
                "trust",
                "--encoding=UTF8",
                "--no-locale",
            ],
            env=env,
            capture_output=True,
            check=True,
        )
        started = False
        try:
            options = shlex.join(["-k", str(socket), "-p", "5432", "-c", "listen_addresses="])
            subprocess.run(
                [
                    pg_ctl,
                    "-D",
                    str(data),
                    "-l",
                    str(root / "server.log"),
                    "-o",
                    options,
                    "-w",
                    "start",
                ],
                env=env,
                capture_output=True,
                check=True,
                timeout=30,
            )
            started = True
            with psycopg.connect(
                host=str(socket), port=5432, dbname="postgres", user="stage2_test", autocommit=True
            ) as connection:
                connection.execute("CREATE DATABASE jobmitra_dev")
                assert connection.execute("SHOW listen_addresses").fetchone()[0] == ""
            print(
                "Isolated PostgreSQL 18: private Unix socket; TCP disabled; no Windows connection.",
                flush=True,
            )
            yield env
        finally:
            if started:
                subprocess.run(
                    [pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"],
                    env=env,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-migration", action="store_true")
    parser.add_argument(
        "--serve", action="store_true", help="Serve the isolated app on 127.0.0.1:8765"
    )
    parser.add_argument(
        "--pytest-args", nargs=argparse.REMAINDER, help="Focused pytest paths/options"
    )
    args = parser.parse_args()
    with isolated_postgres() as env:
        if args.generate_migration:
            if list((PROJECT / "migrations/versions").glob("0002*")):
                raise RuntimeError(
                    "Stage 2 migration already exists; will not generate another revision"
                )
            code = (
                "from alembic import command; from alembic.config import Config; "
                "c=Config('alembic.ini'); command.upgrade(c,'0001_company_management'); "
                "command.revision(c,autogenerate=True,rev_id='0002_jd_tracking',"
                "message='Add JD tracking')"
            )
            return subprocess.run([PYTHON, "-c", code], cwd=PROJECT, env=env).returncode
        if args.serve:
            code = (
                "from alembic import command; from alembic.config import Config; "
                "command.upgrade(Config('alembic.ini'),'head')"
            )
            subprocess.run([PYTHON, "-c", code], cwd=PROJECT, env=env, check=True)
            return subprocess.run(
                [
                    PYTHON,
                    "-m",
                    "uvicorn",
                    "jobmitra.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8765",
                ],
                cwd=PROJECT,
                env=env,
            ).returncode
        return subprocess.run(
            [
                PYTHON,
                "-m",
                "pytest",
                "-q",
                *(
                    args.pytest_args
                    if args.pytest_args is not None
                    else [
                        "tests/test_stage2.py",
                        "tests/test_company_schema.py",
                        "tests/test_company_migration.py",
                    ]
                ),
            ],
            cwd=PROJECT,
            env=env,
        ).returncode


if __name__ == "__main__":
    sys.exit(main())
