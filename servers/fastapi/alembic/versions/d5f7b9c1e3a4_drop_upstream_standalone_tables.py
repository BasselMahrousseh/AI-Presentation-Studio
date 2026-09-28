"""drop tables left over from the upstream standalone app

Revision ID: d5f7b9c1e3a4
Revises: c4e6a8b0d2f3
Create Date: 2026-09-28 16:00:00.000000

Studio is now only the backend behind the GenAI Workspace (Smart decks, Workspace JWT auth,
Azure OpenAI from env). These tables belonged to features that were removed: TemplateV2
templates and layouts, local login API tokens, provider settings and Presenton Cloud, Ollama
pulls, font uploads, themes (key/value store), webhooks and async generation tasks. The
chat_history_messages.template_v2_id column (template chat) goes with template_v2.

Existing TemplateV2 decks are untouched: they live in presentations/slides, which stay.

downgrade() recreates the tables and the column empty; the dropped rows are not restored.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision: str = "d5f7b9c1e3a4"
down_revision: Union[str, None] = "c4e6a8b0d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Order matters on PostgreSQL: nothing that stays references these tables once
# chat_history_messages.template_v2_id is gone.
DROPPED_TABLES = (
    "access_tokens",
    "template_create_infos",
    "templates",
    "presentation_layout_codes",
    "webhook_subscriptions",
    "async_tasks",
    "async_presentation_generation_tasks",
    "ollamapullstatus",
    "presenton_cloud_provider",
    "provider_settings",
    "font_uploads",
    "keyvaluesqlmodel",
    "template_v2",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _chat_columns() -> set[str]:
    if "chat_history_messages" not in _tables():
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_history_messages")}


def _chat_indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("chat_history_messages")
    }


def upgrade() -> None:
    if "template_v2_id" in _chat_columns():
        if "ix_chat_history_messages_template_v2_id" in _chat_indexes():
            op.drop_index(
                "ix_chat_history_messages_template_v2_id",
                table_name="chat_history_messages",
            )
        # Batch mode recreates the table on SQLite, which is the only way to drop a column
        # that carries a foreign key there; PostgreSQL drops the constraint with the column.
        with op.batch_alter_table("chat_history_messages") as batch_op:
            batch_op.drop_column("template_v2_id")

    existing = _tables()
    for table in DROPPED_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    existing = _tables()
    if not set(DROPPED_TABLES) & existing:
        op.create_table('access_tokens',
        sa.Column('token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('token')
        )
        op.create_table('template_v2',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('raw_layouts', sa.JSON(), nullable=True),
        sa.Column('components', sa.JSON(), nullable=True),
        sa.Column('merged_components', sa.JSON(), nullable=True),
        sa.Column('layouts', sa.JSON(), nullable=True),
        sa.Column('assets', sa.JSON(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('template_create_infos',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('fonts', sa.JSON(), nullable=True),
        sa.Column('pptx_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('slide_htmls', sa.JSON(), nullable=False),
        sa.Column('slide_image_urls', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('presentation_layout_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('presentation', sa.Uuid(), nullable=False),
        sa.Column('layout_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('layout_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('layout_code', sa.Text(), nullable=True),
        sa.Column('fonts', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('webhook_subscriptions',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('event', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('async_tasks',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error', sa.JSON(), nullable=True),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('async_presentation_generation_tasks',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('ollamapullstatus',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_updated', sa.DateTime(), nullable=True),
        sa.Column('status', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('presenton_cloud_provider',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('issuer', sa.String(length=512), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('provider_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('font_uploads',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('filename', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('path', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('normalized_family_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('family_name', sa.String(), nullable=True),
        sa.Column('subfamily_name', sa.String(), nullable=True),
        sa.Column('full_name', sa.String(), nullable=True),
        sa.Column('postscript_name', sa.String(), nullable=True),
        sa.Column('weight_class', sa.Integer(), nullable=True),
        sa.Column('width_class', sa.Integer(), nullable=True),
        sa.Column('format', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('extras', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('keyvaluesqlmodel',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_access_tokens_user_id'), 'access_tokens', ['user_id'], unique=False)
        op.create_index(op.f('ix_access_tokens_token'), 'access_tokens', ['token'], unique=False)
        op.create_index(op.f('ix_template_v2_owner_id'), 'template_v2', ['owner_id'], unique=False)
        op.create_index(op.f('ix_templates_owner_id'), 'templates', ['owner_id'], unique=False)
        op.create_index(op.f('ix_template_create_infos_owner_id'), 'template_create_infos', ['owner_id'], unique=False)
        op.create_index(op.f('ix_presentation_layout_codes_owner_id'), 'presentation_layout_codes', ['owner_id'], unique=False)
        op.create_index(op.f('ix_presentation_layout_codes_presentation'), 'presentation_layout_codes', ['presentation'], unique=False)
        op.create_index(op.f('ix_webhook_subscriptions_owner_id'), 'webhook_subscriptions', ['owner_id'], unique=False)
        op.create_index(op.f('ix_webhook_subscriptions_event'), 'webhook_subscriptions', ['event'], unique=False)
        op.create_index(op.f('ix_async_tasks_owner_id'), 'async_tasks', ['owner_id'], unique=False)
        op.create_index(op.f('ix_async_tasks_type'), 'async_tasks', ['type'], unique=False)
        op.create_index(op.f('ix_async_tasks_status'), 'async_tasks', ['status'], unique=False)
        op.create_index(op.f('ix_async_presentation_generation_tasks_owner_id'), 'async_presentation_generation_tasks', ['owner_id'], unique=False)
        op.create_index(op.f('ix_font_uploads_normalized_family_name'), 'font_uploads', ['normalized_family_name'], unique=False)
        op.create_index(op.f('ix_keyvaluesqlmodel_key'), 'keyvaluesqlmodel', ['key'], unique=False)

    if "chat_history_messages" in existing and "template_v2_id" not in _chat_columns():
        with op.batch_alter_table("chat_history_messages") as batch_op:
            batch_op.add_column(sa.Column("template_v2_id", sa.String(), nullable=True))
            batch_op.create_foreign_key(
                "fk_chat_history_messages_template_v2_id_template_v2",
                "template_v2",
                ["template_v2_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_index(
                "ix_chat_history_messages_template_v2_id", ["template_v2_id"]
            )
