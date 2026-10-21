import os

import pytest
from fastapi.testclient import TestClient

from jobmitra.core.config import Settings
from jobmitra.core.database import benchmark_database, build_engine, check_database
from jobmitra.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("JOBMITRA_RUN_DB_TESTS") != "1", reason="Set JOBMITRA_RUN_DB_TESTS=1 to opt in"
    ),
]


def test_live_connection_and_pool_return():
    engine = build_engine(Settings())
    try:
        assert check_database(engine) >= 0
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_live_repeated_queries_and_pool_return():
    engine = build_engine(Settings())
    try:
        assert len(benchmark_database(engine, 10)) == 10
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_live_api_readiness():
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health/ready").status_code == 200
