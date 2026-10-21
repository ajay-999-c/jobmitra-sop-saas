from logging.config import fileConfig

from alembic import context

from jobmitra.core.config import get_settings
from jobmitra.core.database import Base, build_engine
from jobmitra.modules.companies.models import COMPANY_TABLES
from jobmitra.modules.stage2 import STAGE2_TABLES

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Never compare unmanaged tables, including extension-owned relations.
    return type_ != "table" or name in COMPANY_TABLES | STAGE2_TABLES


def run_migrations_offline():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_on_connection(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
        version_table_schema=context.config.attributes.get("version_table_schema"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    settings = get_settings()
    local_host = settings.db_host.startswith("/") or settings.db_host in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    approved_remote = context.get_x_argument(as_dictionary=True).get("allow_remote") == "true"
    if settings.db_name != "jobmitra_dev" or (not local_host and not approved_remote):
        raise RuntimeError(
            "Migrations require local isolation or an explicitly approved -x allow_remote=true run"
        )
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        run_on_connection(supplied_connection)
        return
    engine = build_engine(get_settings())
    try:
        with engine.connect() as connection:
            run_on_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
