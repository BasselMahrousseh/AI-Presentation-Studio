"""Persist create outcomes in the deck transaction without changing existing rows."""
from alembic import op
import sqlalchemy as sa
from utils.sql_types import PortableUUID, UTCDateTime

revision = "b0c2d4e6f8a1"
down_revision = "a9b2c4d6e8f0"
branch_labels = None
depends_on = None
TABLE = "GENAI_WORKSPACE_STUDIO_OPERATION"


def upgrade():
    if op.get_bind().dialect.name == "oracle":
        from dbschema.oracle_bootstrap import apply_operation_migration
        apply_operation_migration(op.get_bind())
        return
    op.create_table(TABLE,
                    sa.Column("operation_key", sa.String(64), primary_key=True, nullable=False),
                    sa.Column("operation_id", sa.String(128), nullable=False),
                    sa.Column("owner_id", PortableUUID(), sa.ForeignKey("GENAI_WORKSPACE_STUDIO_USER.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("request_hash", sa.String(64), nullable=False),
                    sa.Column("presentation_id", PortableUUID(), nullable=False),
                    sa.Column("created_at", UTCDateTime(), nullable=False))


def downgrade():
    # Never discard replay evidence from a populated operation journal.
    if op.get_bind().execute(sa.text(f'SELECT count(*) FROM "{TABLE}"')).scalar_one():
        raise RuntimeError("Cannot drop populated Studio operation history; retain it or restore a compatible backup")
    op.drop_table(TABLE)
