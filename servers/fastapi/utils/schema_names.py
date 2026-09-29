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
RETIRED_TABLES = {
    "access_tokens", "template_create_infos", "templates", "presentation_layout_codes",
    "webhook_subscriptions", "async_tasks", "async_presentation_generation_tasks",
    "ollamapullstatus", "presenton_cloud_provider", "provider_settings", "font_uploads",
    "keyvaluesqlmodel", "template_v2",
}


def reflected_names(inspector, method):
    names = getattr(inspector, method)()
    if inspector.bind.dialect.name == "oracle":
        return [str(inspector.bind.dialect.denormalize_name(name)) for name in names]
    return names


def find_name(names, expected: str) -> str | None:
    matches = [name for name in names if name.casefold() == expected.casefold()]
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous Studio database objects for {expected}: {matches}")
    return matches[0] if matches else None


def validate_identifier_case(inspector, expected: str, actual: str) -> None:
    if actual == expected:
        return
    # MySQL can normalize physical table names to lowercase. Accept that only
    # when the server actually uses case-insensitive table-name resolution.
    if inspector.bind.dialect.name == "mysql":
        if inspector.bind.exec_driver_sql("SELECT @@lower_case_table_names").scalar_one() in (1, 2):
            return
    raise RuntimeError(f"Unexpected Studio identifier casing: {actual}; expected {expected}")


def version_table_name(inspector) -> str | None:
    tables = reflected_names(inspector, "get_table_names")
    old = find_name(tables, LEGACY_VERSION_TABLE)
    new = find_name(tables, SCHEMA_VERSION_TABLE)
    views = reflected_names(inspector, "get_view_names")
    if any(find_name(views, name) for name in (LEGACY_VERSION_TABLE, SCHEMA_VERSION_TABLE)):
        raise RuntimeError("A view conflicts with the Studio migration tracker")
    if old and new:
        raise RuntimeError("Both legacy and canonical Studio migration trackers exist; reconcile them before migrating")
    name = new or old
    if name:
        validate_identifier_case(inspector, SCHEMA_VERSION_TABLE if new else LEGACY_VERSION_TABLE, name)
    return name


def version_table(name: str) -> Table:
    return Table(quoted_name(name, True), MetaData(), Column("version_num", String(32)))


def canonical_schema_tables(inspector) -> dict[str, str]:
    """Return canonical tables, refusing ambiguous or mixed active schemas."""
    names = reflected_names(inspector, "get_table_names")
    canonical = {
        new: found for new in TABLE_RENAMES.values()
        if (found := find_name(names, new)) is not None
    }
    legacy = [old for old in {*TABLE_RENAMES, *RETIRED_TABLES} if find_name(names, old)]
    if canonical and legacy:
        raise RuntimeError("Mixed legacy and canonical Studio tables; reconcile the schema before migrating")
    if canonical and len(canonical) != len(TABLE_RENAMES):
        raise RuntimeError("Incomplete canonical Studio schema; restore the missing tables before migrating")
    for expected, actual in canonical.items():
        validate_identifier_case(inspector, expected, actual)
    return canonical


def validate_create_all_schema(connection, metadata) -> None:
    """Never hide legacy data behind a new empty set of ORM tables."""
    inspector = inspect(connection)
    names = reflected_names(inspector, "get_table_names")
    canonical = canonical_schema_tables(inspector)
    if any(find_name(names, old) for old in {*TABLE_RENAMES, *RETIRED_TABLES}) or (
        version_table_name(inspector) == LEGACY_VERSION_TABLE
    ):
        raise RuntimeError("Legacy Studio schema found; enable MIGRATE_DATABASE_ON_STARTUP or run Alembic upgrade head")
    for expected in TABLE_RENAMES.values():
        if find_name(reflected_names(inspector, "get_view_names"), expected):
            raise RuntimeError(f"A view conflicts with Studio table {expected}")
    for expected, actual in canonical.items():
        columns = {column["name"] for column in inspector.get_columns(actual)}
        if not set(metadata.tables[expected].columns.keys()).issubset(columns):
            raise RuntimeError(f"Outdated Studio table {expected}; run Alembic upgrade head")
