import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool
from sqlmodel import SQLModel

# Make sure all models can be imported when alembic runs standalone.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import every SQL model so they register with SQLModel.metadata before
# autogenerate or migration execution reads it.
from models.sql.chat_history_message import ChatHistoryMessageModel  # noqa: F401, E402
from models.sql.generation_feedback import GenerationFeedback  # noqa: F401, E402
from models.sql.image_asset import ImageAsset  # noqa: F401, E402
from models.sql.presentation import PresentationModel  # noqa: F401, E402
from models.sql.slide import SlideModel  # noqa: F401, E402
from models.sql.user import User  # noqa: F401, E402
from utils.schema_names import (  # noqa: E402
    LEGACY_VERSION_TABLE,
    SCHEMA_VERSION_TABLE,
    version_table_name,
)

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = SQLModel.metadata

# alembic.ini sets this so Config validates; treat it as "unset" for URL resolution.
_CLI_PLACEHOLDER_DB_URL = "sqlite:///placeholder"


def _get_url() -> str:
    """
    Prefer the URL injected by migrations.py via config.set_main_option,
    falling back to the DATABASE_URL environment variable or a local SQLite DB.
    """
    configured = alembic_config.get_main_option("sqlalchemy.url")
    if configured and configured != _CLI_PLACEHOLDER_DB_URL:
        return configured

    from utils.db_utils import get_database_url_and_connect_args, to_sync_sqlalchemy_url

    url, _ = get_database_url_and_connect_args()
    return to_sync_sqlalchemy_url(url)


def run_migrations_offline() -> None:
    """Generate SQL script without connecting to the database."""
    url = _get_url()
    if url.startswith("oracle"):
        raise RuntimeError("Use python -m dbschema.oracle_v1 for the frozen Oracle SQL baseline; offline historical migrations do not support Oracle")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table=SCHEMA_VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live database."""
    configuration = dict(alembic_config.get_section(alembic_config.config_ini_section) or {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    try:
        with connectable.begin() as connection:
            options = dict(connection=connection, target_metadata=target_metadata,
                           compare_type=True, version_table=SCHEMA_VERSION_TABLE)
            context.configure(**options)
            # Alembic marks current/history inspection with dont_mutate. Read
            # their existing tracker without bootstrapping or creating tables.
            readonly = context.get_context().opts.get("dont_mutate", False)
            existing = version_table_name(inspect(connection))
            if connection.dialect.name == "oracle" and not readonly:
                from dbschema.oracle_bootstrap import prepare_upgrade, validate_runtime_schema
                from dbschema.oracle_v1 import REVISION
                opts = context.get_context().opts
                operation = getattr(opts.get("fn"), "__name__", "")
                destination = opts.get("destination_rev")
                if operation == "upgrade" and destination in {"head", "heads", REVISION}:
                    prepare_upgrade(connection)
                elif operation == "downgrade" and destination == REVISION:
                    validate_runtime_schema(connection)
                else:
                    raise RuntimeError("Oracle supports upgrade head and inspection; historical downgrade/stamp cannot bypass its baseline")
            if readonly:
                options["version_table"] = existing or SCHEMA_VERSION_TABLE
            else:
                # Python's sqlite3 legacy transaction mode otherwise commits DDL
                # before its first DML. Start a real transaction so a failed
                # rename rolls back the tracker and every application table.
                if connection.dialect.name == "sqlite":
                    if not connection.connection.driver_connection.in_transaction:
                        connection.exec_driver_sql("BEGIN")
                if existing and existing.casefold() == LEGACY_VERSION_TABLE.casefold():
                    quote = connection.dialect.identifier_preparer.quote_identifier
                    connection.exec_driver_sql(
                        f"ALTER TABLE {quote(existing)} RENAME TO {quote(SCHEMA_VERSION_TABLE)}"
                    )
            context.configure(**options)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
