"""Frozen Studio Oracle baseline a9b2c4d6e8f0. Do not edit after release.

Pure metadata/SQL generation: no environment loading or connection creation.
Future schema changes belong in a new Alembic revision and baseline version.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, SmallInteger, String, Table, UniqueConstraint, text
from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateIndex, CreateTable

REVISION = "a9b2c4d6e8f0"
PREDECESSOR = "f8c2d4e6a0b3"
TRACKER = "GENAI_WORKSPACE_STUDIO_SCHEMA_VERSION"

SCHEMA = [{'name': 'GENAI_WORKSPACE_STUDIO_USER',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'username', 'type': 'VARCHAR2(128 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'external_subject',
               'type': 'VARCHAR2(256 CHAR)',
               'nullable': True,
               'primary_key': False},
              {'name': 'admin_slot', 'type': 'VARCHAR2(32 CHAR)', 'nullable': True, 'primary_key': False},
              {'name': 'hashed_password',
               'type': 'VARCHAR2(1024 CHAR)',
               'nullable': False,
               'primary_key': False},
              {'name': 'is_active',
               'type': 'SMALLINT',
               'nullable': False,
               'primary_key': False,
               'boolean': True,
               'default': '1'},
              {'name': 'is_superuser',
               'type': 'SMALLINT',
               'nullable': False,
               'primary_key': False,
               'boolean': True,
               'default': '0'},
              {'name': 'is_verified',
               'type': 'SMALLINT',
               'nullable': False,
               'primary_key': False,
               'boolean': True,
               'default': '1'},
              {'name': 'created_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': True,
               'primary_key': False},
              {'name': 'auth_version',
               'type': 'INTEGER',
               'nullable': False,
               'primary_key': False,
               'default': '1'}],
  'checks': [],
  'uniques': [(None, ['admin_slot'])],
  'indexes': [('ix_GENAI_WORKSPACE_STUDIO_USER_external_subject', ['external_subject'], True),
              ('ix_GENAI_WORKSPACE_STUDIO_USER_username', ['username'], True)]},
 {'name': 'GENAI_WORKSPACE_IMAGE_ASSET',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'owner_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_STUDIO_USER.id', 'CASCADE')},
              {'name': 'created_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False},
              {'name': 'is_uploaded',
               'type': 'SMALLINT',
               'nullable': False,
               'primary_key': False,
               'boolean': True},
              {'name': 'path', 'type': 'CLOB', 'nullable': False, 'primary_key': False},
              {'name': 'extras', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True}],
  'checks': [],
  'uniques': [],
  'indexes': [('ix_GENAI_WORKSPACE_IMAGE_ASSET_owner_id', ['owner_id'], False)]},
 {'name': 'GENAI_WORKSPACE_PRESENTATION',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'owner_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_STUDIO_USER.id', 'CASCADE')},
              {'name': 'version', 'type': 'VARCHAR(11 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'content', 'type': 'CLOB', 'nullable': False, 'primary_key': False},
              {'name': 'n_slides', 'type': 'INTEGER', 'nullable': False, 'primary_key': False},
              {'name': 'language', 'type': 'VARCHAR2(64 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'title', 'type': 'CLOB', 'nullable': True, 'primary_key': False},
              {'name': 'file_paths', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'outlines', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'created_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False},
              {'name': 'updated_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False},
              {'name': 'layout', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'structure', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'instructions', 'type': 'CLOB', 'nullable': True, 'primary_key': False},
              {'name': 'tone', 'type': 'VARCHAR2(64 CHAR)', 'nullable': True, 'primary_key': False},
              {'name': 'verbosity', 'type': 'VARCHAR2(64 CHAR)', 'nullable': True, 'primary_key': False},
              {'name': 'is_favorite',
               'type': 'SMALLINT',
               'nullable': False,
               'primary_key': False,
               'boolean': True,
               'default': '0'},
              {'name': 'include_table_of_contents',
               'type': 'SMALLINT',
               'nullable': True,
               'primary_key': False,
               'boolean': True},
              {'name': 'include_title_slide',
               'type': 'SMALLINT',
               'nullable': True,
               'primary_key': False,
               'boolean': True},
              {'name': 'web_search',
               'type': 'SMALLINT',
               'nullable': True,
               'primary_key': False,
               'boolean': True},
              {'name': 'web_search_mode',
               'type': 'VARCHAR2(64 CHAR)',
               'nullable': True,
               'primary_key': False},
              {'name': 'theme', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'fonts', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'generation_mode',
               'type': 'VARCHAR2(64 CHAR)',
               'nullable': False,
               'primary_key': False},
              {'name': 'community_design_ids',
               'type': 'CLOB',
               'nullable': True,
               'primary_key': False,
               'json': True},
              {'name': 'smart_template',
               'type': 'VARCHAR2(255 CHAR)',
               'nullable': True,
               'primary_key': False},
              {'name': 'smart_brand_colors',
               'type': 'CLOB',
               'nullable': True,
               'primary_key': False,
               'json': True},
              {'name': 'generation_status',
               'type': 'VARCHAR2(64 CHAR)',
               'nullable': True,
               'primary_key': False},
              {'name': 'has_explicit_slide_structure',
               'type': 'SMALLINT',
               'nullable': True,
               'primary_key': False,
               'boolean': True},
              {'name': 'source_quality_flags',
               'type': 'CLOB',
               'nullable': True,
               'primary_key': False,
               'json': True},
              {'name': 'acknowledged_quality_flag_groups',
               'type': 'CLOB',
               'nullable': True,
               'primary_key': False,
               'json': True},
              {'name': 'outline_generation_id', 'type': 'RAW(16)', 'nullable': True, 'primary_key': False},
              {'name': 'deck_generation_id', 'type': 'RAW(16)', 'nullable': True, 'primary_key': False},
              {'name': 'source_presentation_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_PRESENTATION.id', 'SET NULL')}],
  'checks': [('presentation_version',
              'version IN (\'v1-standard\', \'v2-standard\')')],
  'uniques': [],
  'indexes': [('ix_GENAI_WORKSPACE_PRESENTATION_owner_id', ['owner_id'], False),
              ('ix_GENAI_WORKSPACE_PRESENTATION_source_presentation_id', ['source_presentation_id'], False)]},
 {'name': 'GENAI_WORKSPACE_SLIDE',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'owner_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_STUDIO_USER.id', 'CASCADE')},
              {'name': 'presentation',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_PRESENTATION.id', 'CASCADE')},
              {'name': 'layout_group', 'type': 'VARCHAR2(255 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'layout', 'type': 'VARCHAR2(255 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'index', 'type': 'INTEGER', 'nullable': False, 'primary_key': False},
              {'name': 'content', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'html_content', 'type': 'CLOB', 'nullable': True, 'primary_key': False},
              {'name': 'speaker_note', 'type': 'CLOB', 'nullable': True, 'primary_key': False},
              {'name': 'properties', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'ui', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True}],
  'checks': [],
  'uniques': [],
  'indexes': [('ix_GENAI_WORKSPACE_SLIDE_owner_id', ['owner_id'], False),
              ('ix_GENAI_WORKSPACE_SLIDE_presentation', ['presentation'], False)]},
 {'name': 'GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'owner_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_STUDIO_USER.id', 'CASCADE')},
              {'name': 'presentation_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_PRESENTATION.id', 'CASCADE')},
              {'name': 'conversation_id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': False},
              {'name': 'position', 'type': 'INTEGER', 'nullable': False, 'primary_key': False},
              {'name': 'role', 'type': 'VARCHAR2(32 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'content', 'type': 'CLOB', 'nullable': False, 'primary_key': False},
              {'name': 'created_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False},
              {'name': 'tool_calls', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True}],
  'checks': [],
  'uniques': [],
  'indexes': [('ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_conversation_id', ['conversation_id'], False),
              ('ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_owner_id', ['owner_id'], False),
              ('ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_position', ['position'], False),
              ('ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_presentation_id', ['presentation_id'], False)]},
 {'name': 'GENAI_WORKSPACE_STUDIO_FEEDBACK',
  'columns': [{'name': 'id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': True},
              {'name': 'owner_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_STUDIO_USER.id', 'CASCADE')},
              {'name': 'presentation_id',
               'type': 'RAW(16)',
               'nullable': True,
               'primary_key': False,
               'fk': ('GENAI_WORKSPACE_PRESENTATION.id', 'SET NULL')},
              {'name': 'stage', 'type': 'VARCHAR2(16 CHAR)', 'nullable': False, 'primary_key': False},
              {'name': 'generation_id', 'type': 'RAW(16)', 'nullable': False, 'primary_key': False},
              {'name': 'rating', 'type': 'SMALLINT', 'nullable': False, 'primary_key': False},
              {'name': 'reasons', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'comment', 'type': 'CLOB', 'nullable': True, 'primary_key': False},
              {'name': 'context', 'type': 'CLOB', 'nullable': True, 'primary_key': False, 'json': True},
              {'name': 'created_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False},
              {'name': 'updated_at',
               'type': 'TIMESTAMP WITH TIME ZONE',
               'nullable': False,
               'primary_key': False}],
  'checks': [],
  'uniques': [('uq_generation_feedback_owner_generation',
               ['owner_id', 'presentation_id', 'stage', 'generation_id'])],
  'indexes': [('ix_GENAI_WORKSPACE_STUDIO_FEEDBACK_owner_id', ['owner_id'], False),
              ('ix_GENAI_WORKSPACE_STUDIO_FEEDBACK_presentation_id', ['presentation_id'], False)]}]


def _type(value):
    if value == "RAW(16)": return oracle.RAW(16)
    if value == "CLOB": return oracle.CLOB()
    if value == "TIMESTAMP WITH TIME ZONE": return oracle.TIMESTAMP(timezone=True)
    if value == "INTEGER": return Integer()
    if value == "SMALLINT": return SmallInteger()
    if value.startswith(("VARCHAR2(", "VARCHAR(")):
        return oracle.VARCHAR2(int(value.split("(")[1].split(" ")[0].rstrip(")")))
    raise ValueError("Unexpected frozen type: " + value)


def build_metadata(*, include_tracker=False):
    metadata = MetaData()
    for spec in SCHEMA:
        cols = []
        for c in spec["columns"]:
            fk = [ForeignKey(c["fk"][0], ondelete=c["fk"][1])] if c.get("fk") else []
            cols.append(Column(c["name"], _type(c["type"]), *fk, nullable=c["nullable"],
                               primary_key=c["primary_key"], server_default=text(c["default"]) if "default" in c else None))
        table = Table(spec["name"], metadata, *cols)
        for name, expression in spec["checks"]:
            table.append_constraint(CheckConstraint(expression, name=name))
        for name, cols in spec["uniques"]:
            table.append_constraint(UniqueConstraint(*cols, name=name))
        for c in spec["columns"]:
            suffix = spec["name"].removeprefix("GENAI_WORKSPACE_").lower() + "_" + c["name"]
            if c.get("json"):
                table.append_constraint(CheckConstraint(c["name"] + " IS JSON", name="ck_" + suffix + "_json"))
            if c.get("boolean"):
                table.append_constraint(CheckConstraint(c["name"] + " IN (0, 1)", name="ck_" + suffix + "_bool"))
        for name, columns, unique in spec["indexes"]:
            Index(name, *(table.c[c] for c in columns), unique=unique)
    if include_tracker:
        Table(TRACKER, metadata, Column("version_num", String(32), primary_key=True, nullable=False))
    return metadata


def render_sql():
    dialect = oracle.dialect()
    metadata = build_metadata(include_tracker=True)
    statements = ["-- Generated by AI-Presentation-Studio: python -m dbschema.oracle_v1",
                  "-- Run as the dedicated Studio schema owner; never the Workspace owner.",
                  "-- Fresh schema only. Existing installs use Alembic upgrade head."]
    for table in metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    statements.append(f'INSERT INTO "{TRACKER}" (version_num) VALUES (\'{REVISION}\');')
    statements.append("COMMIT;")
    return "\n\n".join(statements) + "\n"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(render_sql())
