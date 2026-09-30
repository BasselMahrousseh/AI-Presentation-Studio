from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, with_loader_criteria
from sqlmodel import SQLModel

from models.sql.chat_history_message import ChatHistoryMessageModel
from models.sql.generation_feedback import GenerationFeedback
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.user import User
from api.v1.auth.context import get_current_owner_id
from utils.schema_names import validate_create_all_schema
from utils.db_utils import get_database_url_and_connect_args, get_pool_kwargs
from utils.oracle_thick import open_thick_connection


database_url, connect_args = get_database_url_and_connect_args()
_database_dialect = make_url(database_url).get_backend_name()

# SQLite uses a file lock and ignores server pool settings.
_pool_kwargs = {} if _database_dialect == "sqlite" else get_pool_kwargs()

_engine_kwargs = {
    "connect_args": connect_args,
    "hide_parameters": True,
    **_pool_kwargs,
}
if _database_dialect == "oracle":
    async def _connect_oracle_thick():
        return await open_thick_connection(database_url)

    # This listener rejects thin mode (DPY-3001). The creator uses Instant Client.
    _engine_kwargs["async_creator"] = _connect_oracle_thick

sql_engine: AsyncEngine = create_async_engine(database_url, **_engine_kwargs)


if _database_dialect == "sqlite":
    @event.listens_for(sql_engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async_session_maker = async_sessionmaker(sql_engine, expire_on_commit=False)


_STRICT_OWNER_MODELS = (
    PresentationModel,
    SlideModel,
    ChatHistoryMessageModel,
    ImageAsset,
    GenerationFeedback,
)


@event.listens_for(Session, "do_orm_execute")
def _scope_owned_selects(execute_state) -> None:
    """Apply tenant criteria to every ORM SELECT performed during a request."""
    owner_id = get_current_owner_id()
    if (
        owner_id is None
        or not execute_state.is_select
        or execute_state.execution_options.get("skip_owner_scope")
    ):
        return

    statement = execute_state.statement
    for model in _STRICT_OWNER_MODELS:
        statement = statement.options(
            with_loader_criteria(
                model,
                lambda row: row.owner_id == owner_id,
                include_aliases=True,
            )
        )
    execute_state.statement = statement


@event.listens_for(Session, "before_flush")
def _stamp_new_owned_rows(session, _flush_context, _instances) -> None:
    owner_id = get_current_owner_id()
    if owner_id is None:
        return
    for instance in session.new:
        if isinstance(instance, _STRICT_OWNER_MODELS):
            instance.owner_id = owner_id


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def create_db_and_tables():
    """Create any missing tables from the current models. Startup does not run Alembic."""
    async with sql_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: validate_create_all_schema(sync_conn, SQLModel.metadata))
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(
                sync_conn,
                tables=[
                    PresentationModel.__table__,
                    SlideModel.__table__,
                    ChatHistoryMessageModel.__table__,
                    ImageAsset.__table__,
                    User.__table__,
                    GenerationFeedback.__table__,
                ],
            )
        )


async def dispose_engines():
    """Release every pooled connection during application shutdown."""
    await sql_engine.dispose()
