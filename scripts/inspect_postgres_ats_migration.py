"""Read-only source discovery; private snapshot, aggregate-only console output."""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from jobmitra.core.config import Settings  # noqa: E402
from jobmitra.core.database import build_engine  # noqa: E402
from jobmitra.modules.ats_v2.master_source import (  # noqa: E402
    read_source,
    write_private_json,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = args.output or PROJECT / "runtime/ats-master-migration" / f"source-{timestamp}.json"
    engine = build_engine(Settings())
    try:
        source = read_source(engine)
        written = write_private_json(path, source)
        print("Authenticated PostgreSQL SELECT 1 passed; source transaction was READ ONLY.")
        print("Discovered PostgreSQL schema:", source["schema"])
        for table, count in source["counts"].items():
            print(f"{table}: {count} rows")
        print("Private source snapshot saved:", written)
        print("No PostgreSQL or ATS records were modified.")
        return 0
    except Exception as error:
        # Raw exceptions may contain DB credentials or candidate values.
        print("Read-only discovery failed (" + type(error).__name__ + "). No import was performed.")
        print("Run this command in standalone macOS Terminal if the IDE cannot reach the LAN.")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
