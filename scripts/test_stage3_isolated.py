"""Stage 3 checks/preview with disposable PostgreSQL and private temporary storage."""

import argparse
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

from test_stage2_isolated import PROJECT, PYTHON, isolated_postgres


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate-migration", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    with (
        isolated_postgres() as env,
        TemporaryDirectory(prefix="jobmitra-stage3-files-", dir="/private/tmp") as files,
    ):
        os.chmod(files, 0o700)
        env["JOBMITRA_DOCUMENT_STORAGE_ROOT"] = files
        env["JOBMITRA_STAGE3_DISPOSABLE"] = "1"
        print("Stage 3: temporary private file root; all storage discarded on exit.", flush=True)
        if args.generate_migration:
            if list((PROJECT / "migrations/versions").glob("0004*")):
                raise RuntimeError("Revision 0004 already exists; refusing overwrite")
            code = (
                "from alembic import command; from alembic.config import Config; c=Config("
                "'alembic.ini'); command.upgrade(c,'0003_jd_work_focus'); command.revision"
                "(c,autogenerate=True,rev_id='0004_candidate_desk',message='Add paperless "
                "Candidate Desk')"
            )
            return subprocess.run([PYTHON, "-c", code], cwd=PROJECT, env=env).returncode
        if args.serve:
            code = (
                "from alembic import command; from alembic.config import Config; command.u"
                "pgrade(Config('alembic.ini'),'head')"
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
                    "8766",
                    "--no-access-log",
                ],
                cwd=PROJECT,
                env=env,
            ).returncode
        tests = args.pytest_args if args.pytest_args is not None else ["tests/test_stage3.py"]
        return subprocess.run(
            [PYTHON, "-m", "pytest", "-q", *tests], cwd=PROJECT, env=env
        ).returncode


if __name__ == "__main__":
    sys.exit(main())
