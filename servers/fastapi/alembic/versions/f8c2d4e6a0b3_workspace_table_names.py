"""Give every active Studio application table its Workspace name.

Revision ID: f8c2d4e6a0b3
Revises: e7b1d3f5a9c2

Renames preserve rows, ownership, indexes and foreign keys. Index and constraint
names deliberately remain unchanged, so historical downgrade steps still work.
The Alembic tracker is bootstrapped separately by env.py before revision lookup.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import quoted_name


revision = "f8c2d4e6a0b3"
down_revision = "e7b1d3f5a9c2"
branch_labels = None
depends_on = None

# Frozen migration contract: never import the current ORM or runtime names here.
RENAMES = (
    ("user", "GENAI_WORKSPACE_STUDIO_USER"),
    ("presentations", "GENAI_WORKSPACE_PRESENTATION"),
    ("slides", "GENAI_WORKSPACE_SLIDE"),
    ("imageasset", "GENAI_WORKSPACE_IMAGE_ASSET"),
    ("chat_history_messages", "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE"),
    ("generation_feedback", "GENAI_WORKSPACE_STUDIO_FEEDBACK"),
)
RETIRED_TABLES = {
    "access_tokens", "template_create_infos", "templates", "presentation_layout_codes",
    "webhook_subscriptions", "async_tasks", "async_presentation_generation_tasks",
    "ollamapullstatus", "presenton_cloud_provider", "provider_settings", "font_uploads",
    "keyvaluesqlmodel", "template_v2",
}


def _preflight(connection, renames):
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()
    objects = tables + inspector.get_view_names()
    if any(name.casefold() in RETIRED_TABLES for name in tables):
        raise RuntimeError("Retired Studio tables remain; reconcile the preceding cleanup migration first")
    pairs = []
    for source, target in renames:
        matches = [name for name in tables if name.casefold() == source.casefold()]
        if len(matches) != 1:
            raise RuntimeError(f"Studio rename requires exactly one source table {source}")
        actual = matches[0]
        if actual != source:
            folded_mysql_names = connection.dialect.name == "mysql" and (
                connection.exec_driver_sql("SELECT @@lower_case_table_names").scalar_one() in (1, 2)
            )
            if not folded_mysql_names:
                raise RuntimeError(f"Unexpected Studio source table casing: {actual}")
        if any(name.casefold() == target.casefold() for name in objects):
            raise RuntimeError(f"Studio rename target {target} already exists; reconcile the schema first")
        pairs.append((actual, target))
    if connection.dialect.name == "sqlite":
        version = tuple(map(int, connection.exec_driver_sql("SELECT sqlite_version()").scalar_one().split(".")))
        if version < (3, 26, 0):
            raise RuntimeError("Studio table renames require SQLite 3.26 or newer for foreign-key updates")
        if connection.exec_driver_sql("PRAGMA legacy_alter_table").scalar_one():
            raise RuntimeError("Disable SQLite legacy_alter_table before renaming Studio tables")
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("Repair existing SQLite foreign-key violations before renaming Studio tables")
    elif connection.dialect.name not in {"postgresql", "mysql"}:
        raise RuntimeError(f"Unsupported Studio migration dialect: {connection.dialect.name}")
    return pairs


def _rename(renames):
    if op.get_context().as_sql:
        raise RuntimeError("Studio table rename requires an online migration for collision and foreign-key checks")
    connection = op.get_bind()
    pairs = _preflight(connection, renames)
    if connection.dialect.name == "mysql":
        # MySQL DDL commits implicitly; one atomic statement avoids a partially
        # renamed application schema if a later table rename fails.
        quote = connection.dialect.identifier_preparer.quote_identifier
        connection.exec_driver_sql("RENAME TABLE " + ", ".join(
            f"{quote(source)} TO {quote(target)}" for source, target in pairs
        ))
    else:
        for source, target in pairs:
            op.rename_table(quoted_name(source, True), quoted_name(target, True))
    if connection.dialect.name == "sqlite":
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("Studio foreign-key integrity check failed after table rename")


def upgrade():
    _rename(RENAMES)


def downgrade():
    _rename(tuple((new, old) for old, new in reversed(RENAMES)))
