"""Guarded Oracle baseline lifecycle. Oracle DDL commits implicitly.

Only the known predecessor marker permits resuming a partial baseline. Existing
objects must match before any DDL, and missing indexes are recreated separately
because CREATE TABLE and CREATE INDEX are separate Oracle transactions.
"""

import re

from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select
from sqlalchemy.schema import CreateTable

from dbschema.oracle_v1 import build_metadata as build_v1
from dbschema.oracle_v2 import PREDECESSOR, REVISION, TRACKER, BASELINE_REVISION, OPERATION_TABLE, build_metadata
from utils.schema_names import LEGACY_VERSION_TABLE, RETIRED_TABLES, TABLE_RENAMES, find_name


def physical_name(inspector, name):
    return str(inspector.bind.dialect.denormalize_name(name))


def _names(inspector, method):
    return [physical_name(inspector, name) for name in getattr(inspector, method)()]


def _normalize_check(value):
    return re.sub(r'[\s"()]', '', str(value)).upper()


def _type_matches(actual, expected):
    from sqlalchemy import Integer, String
    from sqlalchemy.dialects import oracle

    if isinstance(expected, Integer):
        return isinstance(actual, Integer) or (isinstance(actual, oracle.NUMBER)
                                               and actual.scale == 0 and actual.precision == 38)
    if isinstance(expected, oracle.RAW):
        return isinstance(actual, oracle.RAW) and actual.length == 16
    if isinstance(expected, oracle.CLOB):
        return isinstance(actual, oracle.CLOB)
    if isinstance(expected, oracle.TIMESTAMP):
        return isinstance(actual, oracle.TIMESTAMP) and actual.timezone and not actual.local_timezone
    if isinstance(expected, String):
        return isinstance(actual, oracle.VARCHAR2) and actual.length == expected.length
    return False


def _validate_table(inspector, table, *, allow_missing_indexes):
    name = table.name
    actual = {c["name"]: c for c in inspector.get_columns(name)}
    if set(actual) != set(table.c.keys()):
        raise RuntimeError(f"Oracle Studio table {name} has incompatible columns")
    for c in table.c:
        found = actual[c.name]
        default = str(c.server_default.arg) if c.server_default is not None else None
        found_default = found.get("default")
        if (not _type_matches(found["type"], c.type) or bool(found["nullable"]) != c.nullable
                or (str(found_default).strip() if found_default is not None else None) != default):
            raise RuntimeError(f"Oracle Studio column {name}.{c.name} has incompatible type, nullability or default")
    pk = tuple(inspector.get_pk_constraint(name).get("constrained_columns") or ())
    if pk != tuple(c.name for c in table.primary_key.columns):
        raise RuntimeError(f"Oracle Studio table {name} has an incompatible primary key")
    expected_fk = {
        (tuple(f.parent.name for f in c.elements), c.elements[0].column.table.name,
         tuple(f.column.name for f in c.elements), c.ondelete or "NO ACTION")
        for c in table.foreign_key_constraints
    }
    reflected_fk = inspector.get_foreign_keys(name)
    current_owner = getattr(inspector.bind.dialect, "default_schema_name", None)
    if any(f.get("referred_schema") and (
        current_owner is None or physical_name(inspector, f["referred_schema"]) != physical_name(inspector, current_owner)
    ) for f in reflected_fk):
        raise RuntimeError(f"Oracle Studio table {name} has a cross-schema foreign key")
    actual_fk = {
        (tuple(f["constrained_columns"]), physical_name(inspector, f["referred_table"]),
         tuple(f["referred_columns"]), (f.get("options") or {}).get("ondelete", "NO ACTION"))
        for f in reflected_fk
    }
    if actual_fk != expected_fk:
        raise RuntimeError(f"Oracle Studio table {name} has incompatible foreign keys")
    expected_unique = {tuple(c.name for c in constraint.columns)
                       for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
    actual_unique = {tuple(c["column_names"]) for c in inspector.get_unique_constraints(name)}
    if actual_unique != expected_unique:
        raise RuntimeError(f"Oracle Studio table {name} has incompatible unique constraints")
    expected_checks = {_normalize_check(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}
    actual_checks = {_normalize_check(c["sqltext"]) for c in inspector.get_check_constraints(name)}
    if actual_checks != expected_checks:
        raise RuntimeError(f"Oracle Studio table {name} has incompatible check constraints")
    # Oracle reflection includes indexes backing PK/UNIQUE constraints; compare
    # declared secondary indexes only. Their names, order and uniqueness matter.
    actual_indexes = {physical_name(inspector, i["name"]): i for i in inspector.get_indexes(name)}
    missing = []
    for index in table.indexes:
        found = actual_indexes.get(index.name)
        if found is None:
            if allow_missing_indexes:
                missing.append(index)
                continue
            raise RuntimeError(f"Oracle Studio index {index.name} is missing")
        if (tuple(found["column_names"]) != tuple(c.name for c in index.columns)
                or bool(found["unique"]) != bool(index.unique)):
            raise RuntimeError(f"Oracle Studio index {index.name} is incompatible")
    return missing


def validate_schema(connection, *, allow_partial=False, inspector=None, metadata=None):
    """Read-only, fail-closed inspection; returns tables/indexes still to create."""
    inspector = inspector or inspect(connection)
    metadata = metadata or build_metadata(include_tracker=True)
    tables = _names(inspector, "get_table_names")
    views = _names(inspector, "get_view_names") + _names(inspector, "get_materialized_view_names")
    for old in {*TABLE_RENAMES, *RETIRED_TABLES, LEGACY_VERSION_TABLE}:
        if find_name(tables + views, old):
            raise RuntimeError("Legacy Studio objects cannot be auto-converted on Oracle; use the database transfer tool")
    unrelated = set(tables) - set(metadata.tables)
    if unrelated:
        raise RuntimeError("Studio requires its own Oracle schema; unrelated application tables are present")
    # USER_OBJECTS also catches synonyms/sequences/types occupying the table
    # namespace, and unexpected quoted casing hidden by normalized reflection.
    objects = connection.exec_driver_sql(
        "SELECT object_name, object_type FROM user_objects WHERE object_type IN "
        "('TABLE', 'VIEW', 'MATERIALIZED VIEW', 'SYNONYM', 'SEQUENCE', 'TYPE', 'PACKAGE', 'FUNCTION', 'PROCEDURE')"
    ).all()
    for expected in metadata.tables:
        for actual, kind in objects:
            if actual.casefold() == expected.casefold() and (actual != expected or kind != "TABLE"):
                raise RuntimeError(f"Oracle object {actual} ({kind}) conflicts with Studio table {expected}")
        if find_name(views, expected):
            raise RuntimeError(f"Oracle view conflicts with Studio table {expected}")
        found = find_name(tables, expected)
        if found is not None and found != expected:
            raise RuntimeError(f"Unexpected Oracle Studio table casing: {found}")
    expected_indexes = {i.name: t.name for t in metadata.tables.values() for i in t.indexes}
    for actual, table_name in connection.exec_driver_sql("SELECT index_name, table_name FROM user_indexes").all():
        expected = find_name(expected_indexes, actual)
        if expected and (actual != expected or table_name != expected_indexes[expected]):
            raise RuntimeError(f"Oracle index {actual} conflicts with the Studio baseline")
    missing_tables, missing_indexes = [], []
    for table in metadata.sorted_tables:
        if table.name not in tables:
            if not allow_partial:
                raise RuntimeError(f"Oracle Studio table {table.name} is missing; provision the Studio schema or run Alembic upgrade head")
            missing_tables.append(table)
        else:
            missing_indexes.extend(_validate_table(inspector, table, allow_missing_indexes=allow_partial))
    # Disabled/NOVALIDATE constraints do not enforce the frozen contract.
    invalid = connection.exec_driver_sql(
        "SELECT table_name, constraint_name FROM user_constraints "
        "WHERE status <> 'ENABLED' OR validated <> 'VALIDATED'"
    ).all()
    if any(table in metadata.tables for table, _ in invalid):
        raise RuntimeError("Oracle Studio constraints must be enabled and validated")
    byte_columns = connection.exec_driver_sql(
        "SELECT table_name, column_name FROM user_tab_columns WHERE data_type = 'VARCHAR2' AND char_used <> 'C'"
    ).all()
    if any(table in metadata.tables for table, _ in byte_columns):
        raise RuntimeError("Oracle Studio VARCHAR2 columns require CHAR length semantics")
    return missing_tables, missing_indexes


def prepare_upgrade(connection):
    """Bootstrap only empty schemas, or resume our explicitly marked baseline."""
    missing, _ = validate_schema(connection, allow_partial=True)
    metadata = build_metadata(include_tracker=True)
    tracker = metadata.tables[TRACKER]
    missing_names = {t.name for t in missing}
    if TRACKER in missing_names:
        if len(missing_names) != len(metadata.tables):
            raise RuntimeError("Unversioned Oracle Studio tables require an explicit data migration; refusing to stamp")
        tracker.create(connection)
        connection.execute(tracker.insert().values(version_num=PREDECESSOR))
        return
    versions = connection.execute(select(tracker.c.version_num)).scalars().all()
    if not versions and len(missing_names) == len(metadata.tables) - 1:
        connection.execute(tracker.insert().values(version_num=PREDECESSOR))
    elif versions == [PREDECESSOR]:
        return
    elif versions == [BASELINE_REVISION]:
        if missing_names - {OPERATION_TABLE}:
            raise RuntimeError("The existing Oracle Studio baseline is incomplete; restore before upgrading")
        return
    elif versions == [REVISION]:
        validate_schema(connection)
    else:
        raise RuntimeError("Unsupported Oracle Studio migration revision; refusing to infer or overwrite its history")


def apply_baseline(connection):
    metadata = build_v1(include_tracker=True)
    missing, indexes = validate_schema(connection, allow_partial=True, metadata=metadata)
    if any(t.name == TRACKER for t in missing):
        raise RuntimeError("Oracle baseline must run through Alembic upgrade head")
    for table in missing:
        # Explicit DDL permits resuming a crash after table creation but before
        # its indexes, without pretending Oracle supports transactional DDL.
        connection.execute(CreateTable(table))
        indexes.extend(table.indexes)
    for index in sorted(indexes, key=lambda i: i.name):
        index.create(connection)
    validate_schema(connection, metadata=metadata)


def apply_operation_migration(connection):
    missing, indexes = validate_schema(connection, allow_partial=True)
    if {table.name for table in missing} - {OPERATION_TABLE} or indexes:
        raise RuntimeError("Oracle Studio baseline must be complete before the operation upgrade")
    for table in missing:
        connection.execute(CreateTable(table))
    validate_schema(connection)


def validate_runtime_schema(connection):
    validate_schema(connection)
    tracker = build_metadata(include_tracker=True).tables[TRACKER]
    if connection.execute(select(tracker.c.version_num)).scalars().all() != [REVISION]:
        raise RuntimeError("Oracle Studio schema is not at the supported revision; run Alembic upgrade head")
