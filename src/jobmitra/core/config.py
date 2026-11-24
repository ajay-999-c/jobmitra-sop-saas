from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class _V12BackendChoice(BaseSettings):
    """Read one selector without requiring legacy credentials for SQLite preview."""

    model_config = SettingsConfigDict(
        env_prefix="JOBMITRA_", env_file_encoding="utf-8", extra="ignore"
    )
    v12_backend: str | None = None
    office_lan_enabled: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="JOBMITRA_", env_file=PROJECT_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    db_host: str
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str
    db_user: str
    db_password: SecretStr
    db_sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    db_connect_timeout: int = Field(default=5, ge=1, le=60)
    db_pool_size: int = Field(default=3, ge=1, le=10)
    db_max_overflow: int = Field(default=0, ge=0, le=5)
    db_pool_timeout: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=5000, ge=1)
    document_storage_root: Path | None = None
    document_max_bytes: int = Field(default=12 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    resume_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    ai_enabled: bool = False
    resume_processing_enabled: bool = False
    resume_processing_repo: Path | None = None
    resume_processing_python: Path | None = None
    resume_processing_database: Path | None = None
    ats_v2_enabled: bool = False
    ats_v2_database: Path | None = None
    ats_v2_resume_storage_root: Path | None = None
    unified_v12_enabled: bool = False
    v12_backend: Literal["sqlite", "postgresql"] = "sqlite"
    v12_postgres_development: bool = False
    v12_postgres_trusted_lan: bool = False
    v12_postgres_schema: str | None = None
    unified_v12_local_direct_editing: bool = False
    office_lan_enabled: bool = False
    office_lan_cidrs: str = ""
    office_lan_hosts: str = ""
    unified_v12_proposals_enabled: bool = False
    unified_v12_proposal_storage_root: Path | None = None
    unified_v12_operator_token: SecretStr | None = None
    unified_v12_supervisor_token: SecretStr | None = None
    office_timezone: str = "Asia/Kolkata"

    @field_validator("office_timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Use a valid IANA office timezone") from None
        return value

    @property
    def database_url(self) -> URL:
        # URL.create handles special characters without manual escaping.
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    import os

    from .local_v12 import default_local_startup, local_settings

    # Explicit PostgreSQL selection must never enter the automatic SQLite profile.
    backend = os.environ.get("JOBMITRA_V12_BACKEND")
    if backend is None and PROJECT_ENV_FILE.is_file():
        backend = _V12BackendChoice(_env_file=PROJECT_ENV_FILE).v12_backend
    if backend not in {None, "sqlite", "postgresql"}:
        raise RuntimeError("Choose a supported V12 backend explicitly.")
    if _V12BackendChoice(_env_file=PROJECT_ENV_FILE).office_lan_enabled:
        if os.environ.get("JOBMITRA_LOCAL_V12") == "1":
            raise RuntimeError("Office LAN mode conflicts with the local SQLite profile.")
        return Settings()
    if backend == "postgresql":
        if os.environ.get("JOBMITRA_LOCAL_V12") == "1":
            raise RuntimeError("Choose PostgreSQL or the SQLite local profile explicitly.")
        return Settings()
    mode = os.environ.get("JOBMITRA_LOCAL_V12")
    if mode == "1" or (mode is None and default_local_startup()):
        return local_settings()
    return Settings()
