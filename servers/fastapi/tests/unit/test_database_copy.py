"""Exercise migration safety with synthetic SQLite sources/targets only."""

from datetime import datetime, timezone
import hashlib
import os
import uuid

import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlmodel import SQLModel

from scripts.migrate_database import (
    MigrationError, TABLES, copy_records, destination_url, main, normalize_row, readonly_source,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)
NAMES = {table.name: table for table in TABLES}


def make_database(path):
    engine = create_engine("sqlite:///" + str(path))

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine, tables=list(TABLES))
    return engine


def records():
    owner, deck, slide, image, chat, feedback = [uuid.uuid4() for _ in range(6)]
    return {
        "GENAI_WORKSPACE_STUDIO_USER": dict(
            id=owner, username="ws:alice", external_subject="alice", hashed_password="!external",
            is_active=True, is_superuser=False, is_verified=True, auth_version=1, created_at=NOW,
        ),
        "GENAI_WORKSPACE_PRESENTATION": dict(
            id=deck, owner_id=owner, version="v1-standard", content="", n_slides=1, language="en",
            title="", outlines={"slides": [{"title": "مرحبا", "notes": ""}]},
            file_paths=[f"/app_data/uploads/users/{owner}/source.txt"],
            created_at=NOW, updated_at=NOW, generation_mode="smart",
        ),
        "GENAI_WORKSPACE_SLIDE": dict(
            id=slide, owner_id=owner, presentation=deck, layout_group="smart", layout="custom",
            index=0, content={"text": "مرحبا", "empty": ""}, properties={},
            html_content="<p>" + "Δ" * 5000 + "</p>", speaker_note="",
        ),
        "GENAI_WORKSPACE_IMAGE_ASSET": dict(
            id=image, owner_id=owner, path=f"/app_data/images/users/{owner}/image.png",
            is_uploaded=True, created_at=NOW,
        ),
        "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE": dict(
            id=chat, owner_id=owner, presentation_id=deck, conversation_id=uuid.uuid4(),
            position=1, role="user", content="", created_at=NOW, tool_calls=["kept"],
        ),
        "GENAI_WORKSPACE_STUDIO_FEEDBACK": dict(
            id=feedback, owner_id=owner, presentation_id=deck, stage="deck",
            generation_id=uuid.uuid4(), rating=1, reasons=["quality"], comment="",
            context={"empty": "", "unicode": "مرحبا"}, created_at=NOW, updated_at=NOW,
        ),
    }


def seed(engine, data):
    with engine.begin() as connection:
        for table in TABLES:
            if table.name in data:
                connection.execute(table.insert().values(**data[table.name]))


def counts(engine):
    with engine.connect() as connection:
        return {table.name: connection.scalar(select(func.count()).select_from(table)) for table in TABLES}


@pytest.fixture
def databases(tmp_path):
    source_path = tmp_path / "source with space.db"
    source = make_database(source_path)
    target = make_database(tmp_path / "target.db")
    data = records()
    seed(source, data)
    yield source_path, source, target, data
    source.dispose()
    target.dispose()


def test_dry_run_apply_and_rerun_preserve_payloads_without_source_writes(databases):
    path, _, target, data = databases
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with readonly_source(path) as source, target.begin() as destination:
        plan = copy_records(source, destination)
    assert all(row["insert"] == 1 for row in plan.values())
    assert all(count == 0 for count in counts(target).values())
    with readonly_source(path) as source, target.begin() as destination:
        copy_records(source, destination, apply=True)
    with readonly_source(path) as source, target.begin() as destination:
        plan = copy_records(source, destination, apply=True)
    assert all(row["insert"] == 0 and row["existing_identical"] == 1 for row in plan.values())
    assert all(count == 1 for count in counts(target).values())
    with target.connect() as destination:
        deck = destination.execute(select(NAMES["GENAI_WORKSPACE_PRESENTATION"])).mappings().one()
        assert deck["content"] == "" and deck["title"] is None
        assert deck["outlines"] == data["GENAI_WORKSPACE_PRESENTATION"]["outlines"]
        slide = destination.execute(select(NAMES["GENAI_WORKSPACE_SLIDE"])).mappings().one()
        assert slide["html_content"] == data["GENAI_WORKSPACE_SLIDE"]["html_content"]
        assert slide["content"]["empty"] == "" and slide["speaker_note"] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_source_connection_cannot_write_or_create_missing_file(databases, tmp_path):
    path, _, _, _ = databases
    with readonly_source(path) as source:
        with pytest.raises(Exception, match="readonly"):
            source.exec_driver_sql("CREATE TABLE forbidden (value INTEGER)")
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        with readonly_source(missing):
            pass
    assert not missing.exists()


def test_conflicts_abort_before_missing_rows_are_inserted(databases):
    path, _, target, data = databases
    seed(target, {
        "GENAI_WORKSPACE_STUDIO_USER": data["GENAI_WORKSPACE_STUDIO_USER"],
        "GENAI_WORKSPACE_IMAGE_ASSET": {**data["GENAI_WORKSPACE_IMAGE_ASSET"], "path": "conflicting-reference"},
    })
    before = counts(target)
    with pytest.raises(MigrationError, match="Conflicting record"):
        with readonly_source(path) as source, target.begin() as destination:
            copy_records(source, destination, apply=True)
    assert counts(target) == before


def test_failure_after_inserts_rolls_back_the_whole_target_transaction(databases):
    path, _, target, _ = databases

    @event.listens_for(target, "before_cursor_execute")
    def fail_midway(_, __, statement, ___, ____, _____):
        if statement.startswith('INSERT INTO "GENAI_WORKSPACE_SLIDE"'):
            raise RuntimeError("injected migration failure")

    with pytest.raises(RuntimeError, match="injected"):
        with readonly_source(path) as source, target.begin() as destination:
            copy_records(source, destination, apply=True)
    assert all(count == 0 for count in counts(target).values())


def test_self_referencing_decks_can_be_copied_in_any_uuid_order(databases):
    path, source_engine, target, data = databases
    table = NAMES["GENAI_WORKSPACE_PRESENTATION"]
    first = data[table.name]["id"]
    second = uuid.uuid4()
    with source_engine.begin() as connection:
        connection.execute(table.insert().values(**{**data[table.name], "id": second, "source_presentation_id": first}))
        connection.execute(update(table).where(table.c.id == first).values(source_presentation_id=second))
    with readonly_source(path) as source, target.begin() as destination:
        copy_records(source, destination, apply=True)
    with target.connect() as connection:
        links = dict(connection.execute(select(table.c.id, table.c.source_presentation_id)).all())
    assert links == {first: second, second: first}


def test_unmapped_ownership_is_rejected_without_mutation(databases):
    path, source_engine, target, _ = databases
    users = NAMES["GENAI_WORKSPACE_STUDIO_USER"]
    with source_engine.begin() as connection:
        connection.execute(update(users).values(external_subject=None))
    with pytest.raises(MigrationError, match="owner backfill"):
        with readonly_source(path) as source, target.begin() as destination:
            copy_records(source, destination, apply=True)
    assert all(count == 0 for count in counts(target).values())


@pytest.mark.parametrize("table_name,column_name", [
    ("GENAI_WORKSPACE_SLIDE", "presentation"),
    ("GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE", "presentation_id"),
    ("GENAI_WORKSPACE_STUDIO_FEEDBACK", "presentation_id"),
    ("GENAI_WORKSPACE_PRESENTATION", "source_presentation_id"),
])
def test_cross_owner_deck_links_are_rejected_before_copy(databases, table_name, column_name):
    path, source_engine, target, data = databases
    other_owner, other_deck = uuid.uuid4(), uuid.uuid4()
    users = NAMES["GENAI_WORKSPACE_STUDIO_USER"]
    decks = NAMES["GENAI_WORKSPACE_PRESENTATION"]
    with source_engine.begin() as connection:
        connection.execute(users.insert().values(**{
            **data[users.name], "id": other_owner, "username": "ws:bob", "external_subject": "bob",
        }))
        connection.execute(decks.insert().values(**{
            **data[decks.name], "id": other_deck, "owner_id": other_owner, "file_paths": [],
        }))
        connection.execute(update(NAMES[table_name]).where(
            NAMES[table_name].c.id == data[table_name]["id"]
        ).values({column_name: other_deck}))
    with pytest.raises(MigrationError, match="cross-owner reference"):
        with readonly_source(path) as source, target.begin() as destination:
            copy_records(source, destination, apply=True)
    assert all(count == 0 for count in counts(target).values())


def test_required_labels_cannot_be_silently_normalized_to_null():
    table = NAMES["GENAI_WORKSPACE_SLIDE"]
    row = {column.name: None for column in table.columns}
    row["layout_group"] = ""
    with pytest.raises(MigrationError, match="empty required scalar"):
        normalize_row(table, row)


@pytest.mark.parametrize("reference", ["C:/old-machine/images/image.png", "/app_data/images/users/00000000-0000-0000-0000-000000000000/image.png"])
def test_nonportable_or_cross_owner_files_block_copy(databases, reference):
    path, source_engine, target, _ = databases
    images = NAMES["GENAI_WORKSPACE_IMAGE_ASSET"]
    with source_engine.begin() as connection:
        connection.execute(update(images).values(path=reference))
    with pytest.raises(MigrationError, match="Non-portable Studio asset references"):
        with readonly_source(path) as source, target.begin() as destination:
            copy_records(source, destination, apply=True)
    assert all(count == 0 for count in counts(target).values())


def test_cli_rejects_non_oracle_destinations_without_disclosing_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STUDIO_ENV_FILE", "")
    monkeypatch.setenv("PERSISTENCE_MODE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ORACLE_PASSWORD", "must-not-print")
    result = main(["--source-sqlite", str(tmp_path / "missing.db")])
    assert result == 1
    output = capsys.readouterr()
    assert "Destination must be" in output.err
    assert "must-not-print" not in output.err + output.out


def test_selected_destination_file_cannot_borrow_shell_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "oracle+oracledb://wrong:wrong@wrong/?service_name=wrong")
    monkeypatch.setenv("ORACLE_PASSWORD", "wrong-shell-password")
    monkeypatch.setenv("PASSWORD_FRAGMENT", "wrong-interpolation")
    monkeypatch.setenv("STUDIO_ENV_FILE", "unrelated.env")
    selected = tmp_path / "selected.env"
    selected.write_text(
        "PERSISTENCE_MODE=oracle\nORACLE_USER=studio_owner\n"
        "ORACLE_PASSWORD='${PASSWORD_FRAGMENT}@:/#'\nORACLE_DSN=host:1521/service\n",
        encoding="utf-8-sig",
    )
    url = destination_url(selected)
    assert url.drivername == "oracle+oracledb"
    assert url.username == "studio_owner"
    assert url.password == "${PASSWORD_FRAGMENT}@:/#"
    assert url.query == {"dsn": "host:1521/service"}
    assert os.environ["STUDIO_ENV_FILE"] == "unrelated.env"
    assert os.environ["ORACLE_PASSWORD"] == "wrong-shell-password"


def test_incomplete_selected_destination_does_not_use_shell_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "oracle+oracledb://wrong:wrong@wrong")
    monkeypatch.setenv("ORACLE_PASSWORD", "wrong-shell-password")
    selected = tmp_path / "incomplete.env"
    selected.write_text("PERSISTENCE_MODE=oracle\nORACLE_USER=studio_owner\nORACLE_DSN=host/service\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="incomplete: ORACLE_PASSWORD"):
        destination_url(selected)


def test_process_destination_never_loads_implicit_environment(tmp_path, monkeypatch):
    selected = tmp_path / "unrequested.env"
    selected.write_text("DATABASE_URL=oracle+oracledb://wrong:secret@wrong\n", encoding="utf-8")
    monkeypatch.setenv("STUDIO_ENV_FILE", str(selected))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PERSISTENCE_MODE", raising=False)
    with pytest.raises(MigrationError, match="explicitly configured"):
        destination_url()


@pytest.mark.parametrize("driver", ["oracle", "oracle+oracledb", "oracle+oracledb_async"])
def test_explicit_destination_url_preserves_query_and_overrides_mode(driver, monkeypatch):
    monkeypatch.setenv("PERSISTENCE_MODE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"{driver}://studio:pass%40word@host:1521/?service_name=studio_service&retry_count=3")
    url = destination_url()
    assert url.drivername == "oracle+oracledb"
    assert url.username == "studio" and url.password == "pass@word"
    assert url.host == "host" and url.port == 1521
    assert url.query == {"service_name": "studio_service", "retry_count": "3"}


def test_cli_rejects_duplicate_destination_keys_without_disclosing_values(tmp_path, capsys):
    selected = tmp_path / "ambiguous.env"
    selected.write_text("ORACLE_PASSWORD=first-secret\nORACLE_PASSWORD=second-secret\n", encoding="utf-8")
    assert main(["--source-sqlite", str(tmp_path / "missing.db"), "--env-file", str(selected)]) == 1
    output = capsys.readouterr()
    assert "Duplicate configuration key ORACLE_PASSWORD at line 2" in output.err
    assert "first-secret" not in output.err + output.out
    assert "second-secret" not in output.err + output.out


def test_rejecting_sqlite_destination_does_not_create_parent_directories(tmp_path, monkeypatch):
    destination = tmp_path / "must-not-create" / "database.db"
    monkeypatch.setenv("PERSISTENCE_MODE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + destination.as_posix())
    with pytest.raises(MigrationError, match="Destination must be"):
        destination_url()
    assert not destination.parent.exists()
