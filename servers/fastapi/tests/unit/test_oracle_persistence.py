"""Oracle configuration, codecs, frozen DDL and fail-closed bootstrap (no server)."""

from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import CheckConstraint, String, UniqueConstraint, create_engine, insert, select
from sqlalchemy.dialects import mysql, oracle, postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel

from dbschema import oracle_bootstrap as bootstrap
from dbschema.oracle_v1 import PREDECESSOR, REVISION, TRACKER, build_metadata, render_sql
from models.sql.chat_history_message import ChatHistoryMessageModel
from models.sql.generation_feedback import GenerationFeedback
from models.sql.image_asset import ImageAsset
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.user import User
from utils.db_utils import get_database_url_and_connect_args, to_sync_sqlalchemy_url
from utils.sql_types import PortableJSON, PortableUUID, UTCDateTime


@pytest.fixture
def clean_db_env(monkeypatch):
    for key in ("PERSISTENCE_MODE", "DATABASE_URL", "APP_DATA_DIRECTORY", "ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_oracle_mode_requires_complete_credentials_and_never_falls_back(clean_db_env):
    clean_db_env.setenv("PERSISTENCE_MODE", "oracle")
    with pytest.raises(ValueError, match="ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN"):
        get_database_url_and_connect_args()


def test_oracle_dsn_and_password_punctuation_survive_async_and_sync_urls(clean_db_env):
    clean_db_env.setenv("PERSISTENCE_MODE", "oracle")
    values = {"ORACLE_USER": "studio", "ORACLE_PASSWORD": "synthetic:p@ss/%?#word",
              "ORACLE_DSN": "db.invalid:1521/FREEPDB1?transport_connect_timeout=5"}
    for key, value in values.items(): clean_db_env.setenv(key, value)
    raw, args = get_database_url_and_connect_args()
    url = make_url(raw)
    assert url.password == values["ORACLE_PASSWORD"] and url.query["dsn"] == values["ORACLE_DSN"]
    assert url.drivername == "oracle+oracledb_async" and args == {}
    sync = make_url(to_sync_sqlalchemy_url(raw))
    assert sync.drivername == "oracle+oracledb" and sync.password == url.password
    # Inspect the driver's DBAPI kwargs without opening a connection.
    engine = create_engine(sync)
    try:
        _, kwargs = engine.dialect.create_connect_args(sync)
        assert kwargs["dsn"] == values["ORACLE_DSN"] and kwargs["password"] == url.password
    finally:
        engine.dispose()
    clean_db_env.setenv("DATABASE_URL", "sqlite:///:memory:")
    assert make_url(get_database_url_and_connect_args()[0]).drivername == "sqlite+aiosqlite"


@pytest.mark.parametrize("url, expected", [
    ("oracle+oracledb://u:p@db.invalid:1521?service_name=FREEPDB1", "service_name"),
    ("postgresql://u:p@db.invalid/db?sslmode=disable&command_timeout=30", "command_timeout"),
    ("mysql://u:p@db.invalid/db?charset=utf8mb4", "charset"),
])
def test_url_options_are_not_discarded(clean_db_env, url, expected):
    clean_db_env.setenv("DATABASE_URL", url)
    actual, _ = get_database_url_and_connect_args()
    assert expected in make_url(actual).query
    assert "sslmode" not in make_url(actual).query


def test_oracle_uuid_json_codecs_are_lossless():
    dialect = oracle.dialect()
    identifier = uuid.uuid4()
    uid = PortableUUID().dialect_impl(dialect)
    assert uid.bind_processor(dialect)(identifier) == identifier.bytes
    assert uid.result_processor(dialect, None)(identifier.bytes) == identifier
    data = {"unicode": "مرحبا", "list": [None, "", True, 1.5], "html": "<div>kept</div>"}
    codec = PortableJSON().dialect_impl(dialect)
    bound = codec.bind_processor(dialect)(data)
    assert codec.result_processor(dialect, None)(bound) == data
    assert codec.result_processor(dialect, None)(codec.bind_processor(dialect)(None)) is None
    with pytest.raises(ValueError): codec.bind_processor(dialect)({"nan": float("nan")})


def test_oracle_timestamp_retains_instant_and_fraction_without_session_timezone():
    kind = UTCDateTime()
    instant = datetime(2026, 9, 29, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=4)))
    bound = kind.process_bind_param(instant, oracle.dialect())
    assert bound == instant.astimezone(timezone.utc) and bound.hour == 8 and bound.microsecond == 123456
    fetched = kind.process_result_value(bound.replace(tzinfo=None), oracle.dialect())
    assert fetched == instant
    assert "SYS_EXTRACT_UTC" in str(select(PresentationModel.created_at).compile(dialect=oracle.dialect()))
    assert "FROM_TZ" in str(insert(PresentationModel).values(created_at=instant).compile(dialect=oracle.dialect()))


def test_runtime_dialect_is_not_inferred_from_password_substrings():
    env = dict(os.environ, STUDIO_ENV_FILE="", WORKSPACE_ENV_FILE="", PERSISTENCE_MODE="",
               DATABASE_URL="oracle+oracledb://synthetic:contains-sqlite@db.invalid:1521?service_name=FREEPDB1")
    result = subprocess.run([sys.executable, "-c", "from services import database as d; "
                             "assert d.sql_engine.dialect.name == 'oracle'; "
                             "assert d._pool_kwargs; "
                             "assert not hasattr(d, '_enable_sqlite_foreign_keys'); "
                             "assert d.sql_engine.sync_engine.hide_parameters"],
                            env=env, cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("dialect", [oracle.dialect(), sqlite.dialect(), postgresql.dialect(), mysql.dialect()])
def test_all_orm_tables_and_queries_compile_for_supported_dialects(dialect):
    for table in SQLModel.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert table.name in ddl
        str(select(table).compile(dialect=dialect))
    statement = select(PresentationModel).where(PresentationModel.is_favorite == True)  # noqa: E712
    assert "IS 1" not in str(statement.compile(dialect=dialect))
    sql = str(insert(PresentationModel).values(content="", language="en", n_slides=0, version="v2-standard").compile(dialect=dialect))
    assert ("EMPTY_CLOB()" in sql) == (dialect.name == "oracle")


def test_frozen_oracle_columns_match_runtime_and_ddl_has_native_types():
    metadata = build_metadata()
    assert set(metadata.tables) == set(SQLModel.metadata.tables)
    dialect = oracle.dialect()
    for name, table in metadata.tables.items():
        live = SQLModel.metadata.tables[name]
        assert set(table.c.keys()) == set(live.c.keys())
        for column in table.c:
            actual = live.c[column.name]
            assert str(column.type.compile(dialect=dialect)).replace("VARCHAR2", "VARCHAR") == str(actual.type.compile(dialect=dialect)).replace("VARCHAR2", "VARCHAR")
            assert column.nullable == actual.nullable
        assert {(i.name, tuple(c.name for c in i.columns), i.unique) for i in table.indexes} == {
            (i.name, tuple(c.name for c in i.columns), i.unique) for i in live.indexes}
    ddl = render_sql()
    assert ddl == render_sql() and ddl.count("CREATE TABLE ") == 7
    assert "RAW(16)" in ddl and "IS JSON" in ddl and "TIMESTAMP WITH TIME ZONE" in ddl
    assert f"VALUES ('{REVISION}')" in ddl and " DEFAULT true" not in ddl


def test_sqlite_round_trip_keeps_uuid_json_dates_and_empty_content():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    user_id, deck_id = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session:
        session.add(User(id=user_id, username="portable", hashed_password="!external"))
        session.add(PresentationModel(id=deck_id, owner_id=user_id, content="", n_slides=0,
                                     language="en", version="v2-standard", outlines={"unicode": "مرحبا"}))
        session.commit()
        session.expire_all()
        deck = session.get(PresentationModel, deck_id)
        assert deck.owner_id == user_id and deck.content == "" and deck.outlines == {"unicode": "مرحبا"}
        assert isinstance(deck.created_at, datetime)
    engine.dispose()


class FakeOracle:
    """Reflection fixture derived from the frozen spec, with injectable drift."""
    def __init__(self):
        self.dialect = oracle.dialect()
        self.metadata = build_metadata(include_tracker=True)
        self.present = set(self.metadata.tables)
        self.views = []
        self.extra_objects = []
        self.invalid = []
        self.versions = [REVISION]
        self.columns = {t.name: [dict(name=c.name, type=oracle.VARCHAR2(c.type.length) if isinstance(c.type, String) and not isinstance(c.type, oracle.CLOB) else c.type, nullable=c.nullable,
                                     default=str(c.server_default.arg) if c.server_default is not None else None)
                                for c in t.c] for t in self.metadata.tables.values()}
        self.indexes = {t.name: [dict(name=i.name, column_names=[c.name for c in i.columns], unique=i.unique)
                                for i in t.indexes] for t in self.metadata.tables.values()}
        self.bind = self
        self.writes = []

    def get_table_names(self): return [self.dialect.normalize_name(n) for n in sorted(self.present)]
    def get_view_names(self): return self.views
    def get_materialized_view_names(self): return []
    def get_columns(self, name): return self.columns[name]
    def get_pk_constraint(self, name): return dict(constrained_columns=[c.name for c in self.metadata.tables[name].primary_key.columns])
    def get_unique_constraints(self, name):
        return [dict(column_names=[c.name for c in c.columns]) for c in self.metadata.tables[name].constraints if isinstance(c, UniqueConstraint)]
    def get_foreign_keys(self, name):
        return [dict(constrained_columns=[f.parent.name for f in c.elements],
                     referred_table=self.dialect.normalize_name(c.elements[0].column.table.name),
                     referred_columns=[f.column.name for f in c.elements], options={"ondelete": c.ondelete})
                for c in self.metadata.tables[name].foreign_key_constraints]
    def get_check_constraints(self, name):
        return [dict(sqltext=str(c.sqltext)) for c in self.metadata.tables[name].constraints if isinstance(c, CheckConstraint)]
    def get_indexes(self, name): return self.indexes[name]
    def exec_driver_sql(self, sql):
        rows = [(name, "TABLE") for name in self.present] + self.extra_objects if "user_objects" in sql else self.invalid
        return SimpleNamespace(all=lambda: rows)
    def execute(self, sql):
        if sql.is_select: return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.versions))
        self.writes.append(sql)
        return None


def test_oracle_reflection_normalization_and_complete_schema():
    fake = FakeOracle()
    assert bootstrap.validate_schema(fake, inspector=fake) == ([], [])


@pytest.mark.parametrize("foreign_table", ["GENAI_WORKSPACE_SESSION", "ANOTHER_APPLICATION"])
@pytest.mark.parametrize("complete", [False, True])
def test_oracle_refuses_wrong_application_owner_before_bootstrap_or_runtime_validation(foreign_table, complete):
    fake = FakeOracle()
    if not complete:
        fake.present.clear()
    fake.present.add(foreign_table)
    with pytest.raises(RuntimeError, match="own Oracle schema"):
        bootstrap.validate_schema(fake, allow_partial=not complete, inspector=fake)
    assert not fake.writes


@pytest.mark.parametrize("drift", ["column", "type", "null", "default", "fk", "cross_owner_fk", "unique", "check", "index", "disabled", "view", "case", "synonym", "legacy"])
def test_oracle_preflight_rejects_schema_drift_before_any_write(drift):
    fake = FakeOracle()
    user = "GENAI_WORKSPACE_STUDIO_USER"
    if drift == "column": fake.columns[user].pop()
    if drift == "type": fake.columns[user][0]["type"] = oracle.RAW(32)
    if drift == "null": fake.columns[user][0]["nullable"] = True
    if drift == "default": fake.columns[user][-1]["default"] = "0"
    if drift == "fk": fake.get_foreign_keys = lambda name: []
    if drift == "cross_owner_fk":
        original = fake.get_foreign_keys
        fake.get_foreign_keys = lambda name: [dict(f, referred_schema="workspace_owner") for f in original(name)]
    if drift == "unique": fake.get_unique_constraints = lambda name: []
    if drift == "check": fake.get_check_constraints = lambda name: []
    if drift == "index": fake.indexes[user][0]["unique"] = False
    if drift == "disabled": fake.invalid.append((user, "disabled"))
    if drift == "view": fake.views.append(user)
    if drift == "case": fake.extra_objects.append((user.lower(), "TABLE"))
    if drift == "synonym": fake.extra_objects.append((user, "SYNONYM"))
    if drift == "legacy": fake.present.add("presentations")
    with pytest.raises(RuntimeError): bootstrap.validate_schema(fake, allow_partial=True, inspector=fake)
    assert fake.writes == []


def test_partial_oracle_baseline_reports_missing_tables_and_indexes():
    fake = FakeOracle()
    fake.present.remove("GENAI_WORKSPACE_SLIDE")
    fake.indexes["GENAI_WORKSPACE_STUDIO_USER"] = []
    tables, indexes = bootstrap.validate_schema(fake, allow_partial=True, inspector=fake)
    assert [t.name for t in tables] == ["GENAI_WORKSPACE_SLIDE"] and len(indexes) == 2
    with pytest.raises(RuntimeError): bootstrap.validate_schema(fake, inspector=fake)


@pytest.mark.parametrize("versions", [[], ["unknown"], [REVISION, PREDECESSOR]])
def test_oracle_never_guesses_unversioned_or_unknown_populated_schema(monkeypatch, versions):
    fake = FakeOracle()
    fake.versions = versions
    monkeypatch.setattr(bootstrap, "inspect", lambda conn: fake)
    with pytest.raises(RuntimeError): bootstrap.prepare_upgrade(fake)
    assert fake.writes == []


def test_oracle_marked_partial_schema_can_resume_but_head_cannot_hide_missing_tables(monkeypatch):
    fake = FakeOracle()
    fake.present.remove("GENAI_WORKSPACE_SLIDE")
    monkeypatch.setattr(bootstrap, "inspect", lambda conn: fake)
    fake.versions = [PREDECESSOR]
    bootstrap.prepare_upgrade(fake)
    fake.versions = [REVISION]
    with pytest.raises(RuntimeError): bootstrap.prepare_upgrade(fake)
    assert fake.writes == []
