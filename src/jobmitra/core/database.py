from collections.abc import Iterator
from time import perf_counter

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session

from jobmitra.core.config import Settings


class Base(DeclarativeBase):
    """Future module models share this metadata; Phase 0 defines no tables."""


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_pre_ping=True,
        echo=False,
        hide_parameters=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "sslmode": settings.db_sslmode,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )


def get_session(request: Request) -> Iterator[Session]:
    # No implicit commit: future services own their transaction boundaries.
    with Session(request.app.state.engine) as session:
        yield session


def check_database(engine: Engine) -> float:
    """Return SELECT 1 latency including checkout, pre-ping and connection if needed."""
    started = perf_counter()
    with engine.connect() as connection:
        if connection.scalar(text("SELECT 1")) != 1:
            raise RuntimeError("Unexpected database health-check result")
    return (perf_counter() - started) * 1000


def benchmark_database(engine: Engine, iterations: int) -> list[float]:
    """Time repeated SELECT 1 round trips on one checked-out connection."""
    if not 1 <= iterations <= 10000:
        raise ValueError("iterations must be between 1 and 10000")
    samples = []
    with engine.connect() as connection:
        connection.scalar(text("SELECT 1"))  # Warm up; excluded from samples.
        for _ in range(iterations):
            started = perf_counter()
            if connection.scalar(text("SELECT 1")) != 1:
                raise RuntimeError("Unexpected database benchmark result")
            samples.append((perf_counter() - started) * 1000)
    return samples
