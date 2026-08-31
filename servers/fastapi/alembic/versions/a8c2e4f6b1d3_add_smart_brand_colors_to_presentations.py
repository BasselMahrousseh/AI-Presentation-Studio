"""add extracted smart brand colors to presentations

Revision ID: a8c2e4f6b1d3
Revises: e4a6c8d0f2b1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a8c2e4f6b1d3"
down_revision: str | None = "e4a6c8d0f2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "smart_brand_colors" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("smart_brand_colors", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "smart_brand_colors" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("smart_brand_colors")
