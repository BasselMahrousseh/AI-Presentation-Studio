"""Studio-owned database names and safeguards for legacy schema discovery.

Keep Alembic revisions self-contained: their historical table names must not
change when this runtime contract changes.
"""

from sqlalchemy import Column, MetaData, String, Table, inspect
from sqlalchemy.sql.elements import quoted_name


TABLE_RENAMES = {
    "user": "GENAI_WORKSPACE_STUDIO_USER",
    "presentations": "GENAI_WORKSPACE_PRESENTATION",
    "slides": "GENAI_WORKSPACE_SLIDE",
    "imageasset": "GENAI_WORKSPACE_IMAGE_ASSET",
    "chat_history_messages": "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE",
    "generation_feedback": "GENAI_WORKSPACE_STUDIO_FEEDBACK",
}
SCHEMA_VERSION_TABLE = "GENAI_WORKSPACE_STUDIO_SCHEMA_VERSION"
LEGACY_VERSION_TABLE = "alembic_version"


def find_name(names, expected: str) -> str | None:
    matches = [name for name in names if name.casefold() == expected.casefold()]
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous Studio database objects for {expected}: {matches}")
    return matches[0] if matches else None


def version_table_name(inspector) -> str | None:
    tables = inspector.get_table_names()
    old = find_name(tables, LEGACY_VERSION_TABLE)
    new = find_name(tables, SCHEMA_VERSION_TABLE)
    views = inspector.get_view_names()
    if any(find_name(views, name) for name in (LEGACY_VERSION_TABLE, SCHEMA_VERSION_TABLE)):
        raise RuntimeError("A view conflicts with the Studio migration tracker")
    if old and new:
        raise RuntimeError("Both legacy and canonical Studio migration trackers exist; reconcile them before migrating")
    name = new or old
    if name and inspector.bind.dialect.name != "mysql" and name not in (
        LEGACY_VERSION_TABLE, SCHEMA_VERSION_TABLE
    ):
        raise RuntimeError(f"Unexpected casing for Studio migration tracker: {name}")
    return name


def version_table(name: str) -> Table:
    return Table(quoted_name(name, True), MetaData(), Column("version_num", String(32)))


def canonical_schema_tables(inspector) -> dict[str, str]:
    """Return canonical tables, refusing ambiguous or mixed active schemas."""
    names = inspector.get_table_names()
    canonical = {
        new: found for new in TABLE_RENAMES.values()
        if (found := find_name(names, new)) is not None
    }
    legacy = [old for old in TABLE_RENAMES if find_name(names, old)]
    if canonical and legacy:
        raise RuntimeError("Mixed legacy and canonical Studio tables; reconcile the schema before migrating")
    if canonical and len(canonical) != len(TABLE_RENAMES):
        raise RuntimeError("Incomplete canonical Studio schema; restore the missing tables before migrating")
    if inspector.bind.dialect.name != "mysql" and any(k != v for k, v in canonical.items()):
        raise RuntimeError("Studio table names must use their canonical uppercase spelling")
    return canonical


def validate_create_all_schema(connection, metadata) -> None:
    """Never hide legacy data behind a new empty set of ORM tables."""
    inspector = inspect(connection)
    names = inspector.get_table_names()
    canonical = canonical_schema_tables(inspector)
    if any(find_name(names, old) for old in TABLE_RENAMES) or (
        version_table_name(inspector) == LEGACY_VERSION_TABLE
    ):
        raise RuntimeError("Legacy Studio schema found; enable MIGRATE_DATABASE_ON_STARTUP or run Alembic upgrade head")
    for expected in TABLE_RENAMES.values():
        if find_name(inspector.get_view_names(), expected):
            raise RuntimeError(f"A view conflicts with Studio table {expected}")
    for expected, actual in canonical.items():
        columns = {column["name"] for column in inspector.get_columns(actual)}
        if not set(metadata.tables[expected].columns.keys()).issubset(columns):
            raise RuntimeError(f"Outdated Studio table {expected}; run Alembic upgrade head")
