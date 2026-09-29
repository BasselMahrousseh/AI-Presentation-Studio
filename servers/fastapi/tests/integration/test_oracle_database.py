"""Opt-in real Oracle lifecycle, using an EMPTY dedicated disposable schema.

Set STUDIO_TEST_ORACLE_URL and STUDIO_TEST_ORACLE_ALLOW_DDL=yes. Its connected
user must start GENAI_TEST_STUDIO_. The fixture refuses any existing objects and
only drops the seven tables it created. No Azure or other live service calls.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from dbschema.oracle_bootstrap import validate_runtime_schema
from dbschema.oracle_v1 import PREDECESSOR, REVISION, TRACKER, build_metadata
from models.sql.chat_history_message import ChatHistoryMessageModel
from models.sql.generation_feedback import GenerationFeedback
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.user import User
from utils.db_utils import to_sync_sqlalchemy_url


@pytest.fixture
def oracle_database():
    url = os.getenv("STUDIO_TEST_ORACLE_URL")
    if not url or os.getenv("STUDIO_TEST_ORACLE_ALLOW_DDL") != "yes":
        pytest.skip("Requires an explicitly opted-in, empty disposable Oracle schema")
    engine = create_engine(to_sync_sqlalchemy_url(url), hide_parameters=True)
    with engine.connect() as connection:
        username = connection.exec_driver_sql("SELECT USER FROM dual").scalar_one()
        if not username.startswith("GENAI_TEST_STUDIO_"):
            pytest.fail("Oracle test schema user must start GENAI_TEST_STUDIO_")
        if connection.exec_driver_sql("SELECT object_name FROM user_objects").first():
            pytest.fail("Oracle tests require an empty disposable schema; refusing to touch existing objects")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", to_sync_sqlalchemy_url(url).replace("%", "%%"))
    try:
        yield config, engine
    finally:
        # Only known, initially absent objects created by this test are removed.
        with engine.begin() as connection:
            for table in reversed(build_metadata(include_tracker=True).sorted_tables):
                if inspect(connection).has_table(table.name):
                    quoted = connection.dialect.identifier_preparer.quote_identifier(table.name)
                    connection.exec_driver_sql(f"DROP TABLE {quoted} CASCADE CONSTRAINTS PURGE")
        engine.dispose()


def test_oracle_fresh_upgrade_sync_async_crud_and_rerun(oracle_database):
    config, engine = oracle_database
    command.current(config)
    command.heads(config)
    assert not inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with engine.connect() as connection: validate_runtime_schema(connection)
    uid, pid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    instant = datetime(2026, 9, 29, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=4)))
    payload = {"html": "<p>مرحبا</p>", "list": [None, True, "", 1.5]}
    with Session(engine) as session:
        session.add(User(id=uid, username="oracle-test", hashed_password="!external", created_at=instant))
        session.flush()
        session.add(PresentationModel(id=pid, owner_id=uid, version="v2-standard", content="", n_slides=0,
                                     language="en", outlines=payload, created_at=instant, updated_at=instant))
        session.flush()
        session.add_all([
            SlideModel(id=sid, owner_id=uid, presentation=pid, layout_group="smart", layout="html", index=0, content=payload),
            ImageAsset(owner_id=uid, path="/app_data/owned/test/image.png", extras=payload),
            ChatHistoryMessageModel(owner_id=uid, presentation_id=pid, conversation_id=uuid.uuid4(),
                                    position=1, role="user", content="", tool_calls=["kept"]),
            GenerationFeedback(owner_id=uid, presentation_id=pid, stage="deck", generation_id=uuid.uuid4(),
                               rating=1, reasons=["kept"], context=payload),
        ])
        session.commit()
        session.expire_all()
        deck = session.get(PresentationModel, pid)
        assert deck.owner_id == uid and deck.content == "" and deck.outlines == payload
        assert deck.created_at == instant.astimezone(timezone.utc)
        deck.is_favorite = True
        session.commit()
        assert session.scalars(select(PresentationModel).where(PresentationModel.is_favorite == True)).one().id == pid  # noqa: E712
    command.upgrade(config, "head")
    with pytest.raises(RuntimeError, match="historical|baseline"):
        command.downgrade(config, PREDECESSOR)

    async def async_crud():
        url = engine.url.set(drivername="oracle+oracledb_async")
        async_engine = create_async_engine(url, hide_parameters=True)
        try:
            async with async_sessionmaker(async_engine, expire_on_commit=False)() as session:
                deck = await session.get(PresentationModel, pid)
                assert deck.outlines == payload
                deck.title = "Async kept"
                await session.commit()
        finally:
            await async_engine.dispose()
    asyncio.run(async_crud())
    with Session(engine) as session:
        deck = session.get(PresentationModel, pid)
        assert deck.title == "Async kept"
        session.delete(deck)
        session.commit()
        assert session.get(SlideModel, sid) is None
        feedback = session.scalars(select(GenerationFeedback)).one()
        assert feedback.presentation_id is None


def test_oracle_resume_after_table_ddl_before_indexes(oracle_database):
    config, engine = oracle_database
    metadata = build_metadata(include_tracker=True)
    with engine.begin() as connection:
        metadata.tables[TRACKER].create(connection)
        connection.execute(metadata.tables[TRACKER].insert().values(version_num=PREDECESSOR))
        connection.execute(CreateTable(metadata.tables["GENAI_WORKSPACE_STUDIO_USER"]))
    command.upgrade(config, "head")
    with engine.connect() as connection: validate_runtime_schema(connection)
    command.upgrade(config, "head")


def test_oracle_partial_collision_fails_without_stamping_head(oracle_database):
    config, engine = oracle_database
    tracker = build_metadata(include_tracker=True).tables[TRACKER]
    with engine.begin() as connection:
        tracker.create(connection)
        connection.execute(tracker.insert().values(version_num=PREDECESSOR))
        connection.exec_driver_sql('CREATE TABLE "GENAI_WORKSPACE_STUDIO_USER" (id RAW(32) PRIMARY KEY)')
    with pytest.raises(RuntimeError, match="incompatible"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(select(tracker.c.version_num)).scalar_one() == PREDECESSOR
