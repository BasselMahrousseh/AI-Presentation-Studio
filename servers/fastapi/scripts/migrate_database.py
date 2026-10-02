"""Copy a prepared Studio SQLite database into its provisioned Oracle schema.

Run from servers/fastapi with ``python -m scripts.migrate_database``. The default
compares records without writing. Apply inserts missing records in one Oracle
transaction; it never creates tables, replaces records, or deletes source data.
Stop writers and migrate file references/ownership before the database cutover.
"""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, or_, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from models.sql.chat_history_message import ChatHistoryMessageModel  # noqa: F401
from models.sql.generation_feedback import GenerationFeedback  # noqa: F401
from models.sql.image_asset import ImageAsset  # noqa: F401
from models.sql.presentation import PresentationModel  # noqa: F401
from models.sql.presentation_operation import PresentationOperation  # noqa: F401
from models.sql.slide import SlideModel  # noqa: F401
from models.sql.user import User  # noqa: F401
from utils.schema_names import TABLE_RENAMES, ACTIVE_TABLES
from utils.sql_types import PortableJSON, RequiredText
from services.asset_migration import assert_portable_database_references


TABLES = tuple(
    table for table in SQLModel.metadata.sorted_tables
    if table.name in ACTIVE_TABLES
)
BATCH_SIZE = 200


class MigrationError(RuntimeError):
    """A safe operator-facing message containing no record/credential values."""


@contextmanager
def readonly_source(path: Path):
    path = path.resolve(strict=True)
    if not path.is_file():
        raise MigrationError("The SQLite source must be an existing database file")
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True),
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            # sqlite3's legacy mode otherwise does not snapshot multiple SELECTs.
            connection.exec_driver_sql("BEGIN")
            yield connection
    finally:
        engine.dispose()


def validate_tables(connection):
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    if names.intersection(TABLE_RENAMES):
        raise MigrationError("Legacy Studio tables remain; apply the canonical schema migrations first")
    for table in TABLES:
        if table.name not in names:
            raise MigrationError(f"Missing Studio table {table.name}; provision/upgrade the selected schema first")
        present = {column["name"] for column in inspector.get_columns(table.name)}
        if not set(table.columns.keys()).issubset(present):
            raise MigrationError(f"Outdated Studio table {table.name}; apply schema upgrades first")


def _json_value(value):
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat(timespec="microseconds")
    if isinstance(value, (date, uuid.UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError("Unsupported database value for migration comparison")


def normalize_row(table, record):
    """Account only for defined Oracle scalar/timestamp representation changes."""
    row = dict(record)
    for column in table.columns:
        value = row[column.name]
        if isinstance(value, datetime):
            row[column.name] = (
                value.replace(tzinfo=timezone.utc) if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
        if value == "" and not isinstance(column.type, (PortableJSON, RequiredText)):
            if not column.nullable:
                raise MigrationError(f"{table.name}.{column.name} contains an empty required scalar; resolve it before Oracle migration")
            row[column.name] = None
    return row


def fingerprint(table, row):
    content = json.dumps(
        normalize_row(table, row), default=_json_value, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def batches(connection, table):
    result = connection.execute(select(table).order_by(*table.primary_key.columns))
    try:
        while rows := result.mappings().fetchmany(BATCH_SIZE):
            yield [dict(row) for row in rows]
    finally:
        result.close()


def primary_key(table):
    keys = list(table.primary_key.columns)
    if len(keys) != 1:
        raise MigrationError(f"Unsupported primary-key shape for {table.name}")
    return keys[0]


def target_rows(target, table, rows):
    key = primary_key(table)
    result = target.execute(select(table).where(key.in_([row[key.name] for row in rows])))
    return {row[key.name]: dict(row) for row in result.mappings()}


def validate_source(source):
    validate_tables(source)
    if source.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise MigrationError("Source foreign-key violations must be repaired before migration")
    users = SQLModel.metadata.tables["GENAI_WORKSPACE_STUDIO_USER"]
    identities = {
        row.id for row in source.execute(select(users.c.id, users.c.external_subject))
        if row.external_subject and row.external_subject.strip()
    }
    for table in TABLES:
        if "owner_id" not in table.c:
            continue
        for row in source.execute(select(table.c.owner_id).distinct()):
            if row.owner_id not in identities:
                raise MigrationError(f"{table.name} has unowned or unmapped records; complete Workspace owner backfill first")
        # A foreign key proves existence, not that two records share an owner.
        # Check the model contract even if an old SQLite schema omitted its FK.
        for column in table.columns:
            for foreign in column.foreign_keys:
                referenced = foreign.column.table
                if "owner_id" not in referenced.c:
                    continue
                related = referenced.alias()
                related_key = related.c[foreign.column.name]
                invalid = (
                    select(column)
                    .select_from(table.outerjoin(related, column == related_key))
                    .where(column.is_not(None), or_(
                        related_key.is_(None), related.c.owner_id.is_(None),
                        table.c.owner_id != related.c.owner_id,
                    ))
                    .limit(1)
                )
                if source.execute(invalid).first() is not None:
                    raise MigrationError(
                        f"{table.name}.{column.name} has a missing or cross-owner reference; "
                        "repair ownership before migration"
                    )
        for rows in batches(source, table):
            try:
                assert_portable_database_references({table.name: rows})
            except ValueError as error:
                raise MigrationError(str(error)) from None


def compare(source, target):
    plan = {}
    for table in TABLES:
        counts = {"source": 0, "existing_identical": 0, "insert": 0}
        key = primary_key(table).name
        for rows in batches(source, table):
            existing = target_rows(target, table, rows)
            for row in rows:
                counts["source"] += 1
                digest = fingerprint(table, row)
                found = existing.get(row[key])
                if found is None:
                    counts["insert"] += 1
                elif digest == fingerprint(table, found):
                    counts["existing_identical"] += 1
                else:
                    raise MigrationError(f"Conflicting record in {table.name}; no existing record will be overwritten")
        plan[table.name] = counts
    return plan


def copy_records(source, target, *, apply=False):
    """The caller owns the target transaction; failures must roll it back."""
    validate_source(source)
    if target.dialect.name == "oracle":
        from dbschema.oracle_bootstrap import validate_runtime_schema
        validate_runtime_schema(target)
    else:
        validate_tables(target)
    if apply and target.dialect.name == "oracle":
        quote = target.dialect.identifier_preparer.quote_identifier
        for table in TABLES:
            target.exec_driver_sql(f"LOCK TABLE {quote(table.name)} IN EXCLUSIVE MODE NOWAIT")
    plan = compare(source, target)
    if not apply:
        return plan

    deferred = []
    for table in TABLES:
        key = primary_key(table)
        self_references = [
            column for column in table.columns
            if any(foreign.column.table is table for foreign in column.foreign_keys)
        ]
        for rows in batches(source, table):
            existing = target_rows(target, table, rows)
            for raw in rows:
                if raw[key.name] in existing:
                    continue
                row = normalize_row(table, raw)
                for column in self_references:
                    if row[column.name] is not None:
                        if not column.nullable:
                            raise MigrationError(f"Cannot defer required self-reference in {table.name}.{column.name}")
                        restore = {column.name: row[column.name]}
                        # Restoring a link is migration bookkeeping, not a user
                        # edit. Preserve update timestamps and other onupdate values.
                        restore.update({c.name: row[c.name] for c in table.columns if c.onupdate is not None})
                        deferred.append((table, row[key.name], restore))
                        row[column.name] = None
                target.execute(table.insert().values(**row))
    for table, identity, restore in deferred:
        target.execute(update(table).where(primary_key(table) == identity).values(**restore))

    verified = compare(source, target)
    if any(counts["insert"] for counts in verified.values()):
        raise MigrationError("Post-copy verification found missing records; roll back the target transaction")
    return plan


def destination_url(env_file: Path | None = None) -> URL:
    """Resolve one explicit destination without loading/mutating service env state.

    A selected file is authoritative. Without one, use process values only;
    migration must never discover a different target in an implicit dotenv file.
    """
    if env_file is None:
        values = os.environ
    else:
        path = env_file.resolve(strict=True)
        seen = set()
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if match:
                if match[1] in seen:
                    raise MigrationError(f"Duplicate configuration key {match[1]} at line {line_number}")
                seen.add(match[1])
        values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)

    mode = (values.get("PERSISTENCE_MODE") or "").strip().lower()
    if mode not in {"", "sqlite", "oracle"}:
        raise MigrationError("Studio PERSISTENCE_MODE must be sqlite or oracle")
    explicit = (values.get("DATABASE_URL") or "").strip()
    if explicit:
        url = make_url(explicit)
    elif mode == "oracle":
        required = ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN")
        missing = [key for key in required if not (values.get(key) or "").strip()]
        if missing:
            raise MigrationError("Studio Oracle configuration is incomplete: " + ", ".join(missing))
        url = URL.create(
            "oracle+oracledb", username=values["ORACLE_USER"],
            password=values["ORACLE_PASSWORD"], query={"dsn": values["ORACLE_DSN"]},
        )
    else:
        raise MigrationError("Destination must be the explicitly configured Studio Oracle schema")
    if url.get_backend_name() != "oracle":
        raise MigrationError("Destination must be the explicitly configured Studio Oracle schema")
    if url.drivername not in {"oracle", "oracle+oracledb", "oracle+oracledb_async"}:
        raise MigrationError("Studio Oracle migration requires the python-oracledb driver")
    return url.set(drivername="oracle+oracledb")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, help="Authoritative Studio Oracle environment; otherwise use process values without dotenv fallback")
    parser.add_argument("--apply", action="store_true", help="Insert missing rows; default is a read-only comparison")
    args = parser.parse_args(argv)
    engine = None
    try:
        url = destination_url(args.env_file)
        engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        with readonly_source(args.source_sqlite) as source, engine.begin() as target:
            plan = copy_records(source, target, apply=args.apply)
        print(json.dumps({"applied": args.apply, "tables": plan}, indent=2))
        return 0
    except MigrationError as error:
        print(str(error), file=sys.stderr)
    except Exception as error:
        # Driver exceptions can include credentials or complete bound records.
        print(f"Migration failed ({type(error).__name__}); source data is unchanged. Verify the destination before retrying.", file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
