from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI

from migrations import migrate_database_on_startup
from services.chart_capture_store import sweep_stale_captures
from services.table_capture_store import sweep_stale_captures as sweep_stale_table_captures
from services.database import create_db_and_tables, dispose_engines
from utils.db_utils import database_is_configured
from utils.get_env import (
    get_app_data_directory_env,
)
from utils.model_availability import (
    check_llm_and_image_provider_api_or_model_availability,
)

logger = logging.getLogger(__name__)


def _configure_application_logging() -> None:
    """Honor LOG_LEVEL (default INFO) so template/export diagnostics are visible."""
    raw = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, raw, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.handlers:
        return

    logger_cursor: logging.Logger | None = logging.getLogger("uvicorn.error")
    visible_handlers: list[logging.Handler] = []
    while logger_cursor is not None:
        visible_handlers.extend(logger_cursor.handlers)
        if not logger_cursor.propagate:
            break
        logger_cursor = logger_cursor.parent

    for handler in visible_handlers:
        root_logger.addHandler(handler)

    if not root_logger.handlers:
        logging.basicConfig(level=level)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Initializes the application data directory, runs Alembic migrations when
    MIGRATE_DATABASE_ON_STARTUP=true, creates any missing tables, and checks the Azure OpenAI
    and image-provider configuration.
    """
    _configure_application_logging()
    from services.asset_storage import get_asset_storage
    get_asset_storage()  # Validate storage configuration without a live network call.
    app_data_dir = (get_app_data_directory_env() or "").strip()
    if app_data_dir:
        os.makedirs(app_data_dir, exist_ok=True)
    sweep_stale_captures()
    sweep_stale_table_captures()
    if database_is_configured():
        await migrate_database_on_startup()
        await create_db_and_tables()
    await check_llm_and_image_provider_api_or_model_availability()
    yield
    # Shutdown: release all database connections to prevent stale/leaked pools.
    await dispose_engines()
