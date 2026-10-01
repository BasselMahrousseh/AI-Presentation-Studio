"""Exercise naming cutover only against temporary SQLite databases."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import uuid

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

import migrations
from models.sql.chat_history_message import ChatHistoryMessageModel  # noqa: F401
from models.sql.generation_feedback import GenerationFeedback
from models.sql.image_asset import ImageAsset  # noqa: F401
from models.sql.presentation import PresentationModel
from models.sql.presentation_operation import PresentationOperation
from models.sql.slide import SlideModel  # noqa: F401
from models.sql.user import User  # noqa: F401
from utils.schema_names import (
    LEGACY_VERSION_TABLE, SCHEMA_VERSION_TABLE, TABLE_RENAMES, ACTIVE_TABLES,
    validate_create_all_schema, validate_identifier_case, version_table,
)


def config_for(path):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    return config


@pytest.fixture
def db(tmp_path):
    config = config_for(tmp_path / "studio.db")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    yield config, engine
    engine.dispose()


def tracker_revision(engine, name=SCHEMA_VERSION_TABLE):
    with engine.connect() as connection:
        return connection.execute(select(version_table(name).c.version_num)).scalar_one()


def legacy_tracker(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql(f'ALTER TABLE "{SCHEMA_VERSION_TABLE}" RENAME TO alembic_version')


def snapshot(engine, renamed=False):
    with engine.connect() as connection:
        return {old: connection.exec_driver_sql(f'SELECT * FROM "{new if renamed else old}" ORDER BY id').all()
                for old, new in TABLE_RENAMES.items()}


def seed_legacy(engine):
    """All six tables, a self-linked deck and JSON retain their original values."""
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql('''INSERT INTO "user"
            (id, username, external_subject, hashed_password, is_active, is_superuser, is_verified, auth_version, created_at)
            VALUES ('11111111111111111111111111111111', 'alice', 'alice', '!external', 1, 0, 1, 1, '2026-09-29')''')
        connection.exec_driver_sql('''INSERT INTO presentations
            (id, owner_id, version, content, n_slides, language, created_at, updated_at, generation_mode, is_favorite, outlines)
            VALUES ('22222222222222222222222222222222', '11111111111111111111111111111111',
                    'v2-standard', 'kept', 1, 'en', '2026-09-29', '2026-09-29', 'smart', 1, '{"slides":["kept"]}')''')
        connection.exec_driver_sql('''INSERT INTO presentations
            (id, owner_id, source_presentation_id, version, content, n_slides, language, created_at, updated_at, generation_mode, is_favorite)
            VALUES ('33333333333333333333333333333333', '11111111111111111111111111111111',
                    '22222222222222222222222222222222', 'v2-standard', 'child', 1, 'en', '2026-09-29', '2026-09-29', 'smart', 0)''')
        connection.exec_driver_sql('''INSERT INTO slides
            (id, owner_id, presentation, layout_group, layout, "index", content)
            VALUES ('44444444444444444444444444444444', '11111111111111111111111111111111',
                    '22222222222222222222222222222222', 'smart', 'html', 0, '{"text":"kept"}')''')
        connection.exec_driver_sql('''INSERT INTO imageasset (id, owner_id, created_at, is_uploaded, path)
            VALUES ('55555555555555555555555555555555', '11111111111111111111111111111111', '2026-09-29', 1, '/kept.png')''')
        connection.exec_driver_sql('''INSERT INTO chat_history_messages
            (id, owner_id, presentation_id, conversation_id, position, role, content, created_at)
            VALUES ('66666666666666666666666666666666', '11111111111111111111111111111111',
                    '22222222222222222222222222222222', '77777777777777777777777777777777', 1, 'user', 'kept', '2026-09-29')''')
        connection.exec_driver_sql('''INSERT INTO generation_feedback
            (id, owner_id, presentation_id, stage, generation_id, rating, reasons, created_at, updated_at)
            VALUES ('88888888888888888888888888888888', '11111111111111111111111111111111',
                    '22222222222222222222222222222222', 'deck', '99999999999999999999999999999999', 1, '["kept"]', '2026-09-29', '2026-09-29')''')


def test_metadata_has_only_canonical_tables_and_foreign_keys():
    assert set(SQLModel.metadata.tables) == set(ACTIVE_TABLES)
    assert all(fk.column.table.name in TABLE_RENAMES.values()
               for table in SQLModel.metadata.tables.values() for fk in table.foreign_keys)


def test_fresh_upgrade_and_rerun_have_only_canonical_tables(db):
    config, engine = db
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == {*ACTIVE_TABLES, SCHEMA_VERSION_TABLE}
    assert tracker_revision(engine) == migrations.REVISION_HEAD
    command.upgrade(config, "head")
    assert tracker_revision(engine) == migrations.REVISION_HEAD


def test_legacy_upgrade_preserves_rows_indexes_fks_and_downgrade(db):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    seed_legacy(engine)
    before = snapshot(engine)
    indexes = {name: inspect(engine).get_indexes(name) for name in TABLE_RENAMES}
    legacy_tracker(engine)
    command.upgrade(config, "head")
    assert snapshot(engine, renamed=True) == before
    assert LEGACY_VERSION_TABLE not in inspect(engine).get_table_names()
    assert tracker_revision(engine) == migrations.REVISION_HEAD
    for old, new in TABLE_RENAMES.items():
        assert inspect(engine).get_indexes(new) == indexes[old]
        assert all(fk["referred_table"] in TABLE_RENAMES.values() for fk in inspect(engine).get_foreign_keys(new))
    with Session(engine) as session:
        deck = session.get(PresentationModel, uuid.UUID("2" * 32))
        assert deck.content == "kept" and deck.owner_id == uuid.UUID("1" * 32)
        assert deck.outlines == {"slides": ["kept"]}
        assert session.get(GenerationFeedback, uuid.UUID("8" * 32)).rating == 1
    command.downgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    assert snapshot(engine) == before
    assert tracker_revision(engine) == migrations.REVISION_WEB_SEARCH_MODE
    command.upgrade(config, "head")
    assert snapshot(engine, renamed=True) == before


def test_renamed_foreign_keys_still_enforce_cascade_and_set_null(db):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    seed_legacy(engine)
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql('UPDATE "GENAI_WORKSPACE_SLIDE" SET owner_id = \'missing\'')
        connection.exec_driver_sql('DELETE FROM "GENAI_WORKSPACE_PRESENTATION" WHERE id = ?', ("2" * 32,))
        assert connection.exec_driver_sql('SELECT count(*) FROM "GENAI_WORKSPACE_SLIDE"').scalar_one() == 0
        assert connection.exec_driver_sql('SELECT count(*) FROM "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE"').scalar_one() == 0
        assert connection.exec_driver_sql('SELECT source_presentation_id FROM "GENAI_WORKSPACE_PRESENTATION"').scalar_one() is None
        assert connection.exec_driver_sql('SELECT presentation_id FROM "GENAI_WORKSPACE_STUDIO_FEEDBACK"').scalar_one() is None
        connection.exec_driver_sql('DELETE FROM "GENAI_WORKSPACE_STUDIO_USER"')
        for name in TABLE_RENAMES.values():
            assert connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one() == 0
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize("conflict", ["table", "view", "lowercase", "tracker"])
def test_collision_preflight_leaves_legacy_schema_and_tracker_untouched(db, conflict):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    legacy_tracker(engine)
    with engine.begin() as connection:
        if conflict == "view":
            connection.exec_driver_sql('CREATE VIEW "GENAI_WORKSPACE_PRESENTATION" AS SELECT id FROM presentations')
        else:
            name = (SCHEMA_VERSION_TABLE if conflict == "tracker" else
                    "genai_workspace_presentation" if conflict == "lowercase" else "GENAI_WORKSPACE_PRESENTATION")
            connection.exec_driver_sql(f'CREATE TABLE "{name}" (id TEXT)')
    before = set(inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="exists|trackers"):
        command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == before
    assert tracker_revision(engine, LEGACY_VERSION_TABLE) == migrations.REVISION_WEB_SEARCH_MODE


def test_missing_source_is_rejected_before_any_rename(db):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE imageasset")
    before = set(inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="source table imageasset"):
        command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) == before
    assert tracker_revision(engine) == migrations.REVISION_WEB_SEARCH_MODE


def test_sqlite_failure_after_first_rename_rolls_back_tables_and_tracker(db, monkeypatch):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    seed_legacy(engine)
    legacy_tracker(engine)
    before = snapshot(engine)
    original = Operations.rename_table
    calls = []

    def failing_rename(self, old, new, **kwargs):
        calls.append(old)
        if len(calls) == 2:
            raise RuntimeError("injected migration failure")
        return original(self, old, new, **kwargs)

    monkeypatch.setattr(Operations, "rename_table", failing_rename)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        command.upgrade(config, "head")
    assert snapshot(engine) == before
    assert SCHEMA_VERSION_TABLE not in inspect(engine).get_table_names()
    assert tracker_revision(engine, LEGACY_VERSION_TABLE) == migrations.REVISION_WEB_SEARCH_MODE


def test_current_and_heads_do_not_rename_legacy_tracker(db):
    config, engine = db
    command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
    legacy_tracker(engine)
    command.current(config)
    command.heads(config)
    assert SCHEMA_VERSION_TABLE not in inspect(engine).get_table_names()
    assert tracker_revision(engine, LEGACY_VERSION_TABLE) == migrations.REVISION_WEB_SEARCH_MODE


@pytest.mark.parametrize("canonical", [False, True])
def test_runtime_stamps_complete_unversioned_schema_without_parallel_tables(db, monkeypatch, canonical):
    config, engine = db
    if canonical:
        SQLModel.metadata.create_all(engine)
    else:
        command.upgrade(config, migrations.REVISION_WEB_SEARCH_MODE)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP TABLE "{SCHEMA_VERSION_TABLE}"')
    monkeypatch.setattr(migrations, "get_database_url_and_connect_args", lambda: (str(engine.url), {}))
    migrations._run_migrations()
    assert set(inspect(engine).get_table_names()) == {*ACTIVE_TABLES, SCHEMA_VERSION_TABLE}
    assert tracker_revision(engine) == migrations.REVISION_HEAD


@pytest.mark.parametrize("kind", ["legacy", "retired", "mixed", "partial", "view"])
def test_create_all_refuses_legacy_or_partial_schema(db, kind):
    _, engine = db
    with engine.begin() as connection:
        if kind in {"legacy", "mixed"}:
            connection.exec_driver_sql("CREATE TABLE presentations (id TEXT)")
        if kind == "retired":
            connection.exec_driver_sql("CREATE TABLE provider_settings (id TEXT)")
        if kind in {"mixed", "partial"}:
            connection.exec_driver_sql('CREATE TABLE "GENAI_WORKSPACE_STUDIO_USER" (id TEXT)')
        if kind == "view":
            connection.exec_driver_sql('CREATE VIEW "GENAI_WORKSPACE_PRESENTATION" AS SELECT 1 AS id')
        before = set(inspect(connection).get_table_names())
        with pytest.raises(RuntimeError):
            validate_create_all_schema(connection, SQLModel.metadata)
        assert set(inspect(connection).get_table_names()) == before


def test_create_all_accepts_empty_and_current_schema(db):
    _, engine = db
    with engine.begin() as connection:
        validate_create_all_schema(connection, SQLModel.metadata)
        SQLModel.metadata.create_all(connection)
        validate_create_all_schema(connection, SQLModel.metadata)


def test_create_all_refuses_missing_columns_in_complete_canonical_schema(db):
    _, engine = db
    with engine.begin() as connection:
        for name in TABLE_RENAMES.values():
            connection.exec_driver_sql(f'CREATE TABLE "{name}" (id TEXT)')
        with pytest.raises(RuntimeError, match="Outdated Studio table"):
            validate_create_all_schema(connection, SQLModel.metadata)


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_mysql_folded_names_require_case_insensitive_server(mode):
    connection = SimpleNamespace(
        dialect=mysql.dialect(),
        exec_driver_sql=lambda sql: SimpleNamespace(scalar_one=lambda: mode),
    )
    inspector = SimpleNamespace(bind=connection)
    if mode == 0:
        with pytest.raises(RuntimeError, match="identifier casing"):
            validate_identifier_case(inspector, SCHEMA_VERSION_TABLE, SCHEMA_VERSION_TABLE.lower())
    else:
        validate_identifier_case(inspector, SCHEMA_VERSION_TABLE, SCHEMA_VERSION_TABLE.lower())


@pytest.mark.parametrize("dialect", [postgresql.dialect(), mysql.dialect()])
def test_orm_and_tracker_identifiers_are_quoted_for_server_databases(dialect):
    quote = dialect.identifier_preparer.quote_identifier
    assert quote("GENAI_WORKSPACE_PRESENTATION") in str(select(PresentationModel).compile(dialect=dialect))
    assert quote(SCHEMA_VERSION_TABLE) in str(select(version_table(SCHEMA_VERSION_TABLE)).compile(dialect=dialect))


def rename_revision():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/f8c2d4e6a0b3_workspace_table_names.py"
    spec = importlib.util.spec_from_file_location("workspace_names_revision", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


def test_mysql_rename_uses_one_quoted_statement(monkeypatch):
    revision = rename_revision()
    statements = []
    connection = SimpleNamespace(dialect=mysql.dialect(), exec_driver_sql=statements.append)
    monkeypatch.setattr(revision, "_preflight", lambda conn, pairs: pairs)
    monkeypatch.setattr(revision.op, "get_context", lambda: SimpleNamespace(as_sql=False))
    monkeypatch.setattr(revision.op, "get_bind", lambda: connection)
    revision.upgrade()
    assert statements == ["RENAME TABLE " + ", ".join(f"`{old}` TO `{new}`" for old, new in TABLE_RENAMES.items())]


def test_postgres_rename_identifiers_are_quoted():
    from alembic.ddl.base import RenameTable
    from sqlalchemy.sql.elements import quoted_name

    for old, new in TABLE_RENAMES.items():
        sql = str(RenameTable(quoted_name(old, True), quoted_name(new, True)).compile(dialect=postgresql.dialect()))
        assert sql == f'ALTER TABLE "{old}" RENAME TO "{new}"'


def test_rename_revision_requires_online_inspection():
    revision = rename_revision()
    context = MigrationContext.configure(url="sqlite://", opts={"as_sql": True})
    with Operations.context(context), pytest.raises(RuntimeError, match="online migration"):
        revision.upgrade()
