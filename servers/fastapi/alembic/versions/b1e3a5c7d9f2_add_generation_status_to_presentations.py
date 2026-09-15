"""add generation status to presentations

Revision ID: b1e3a5c7d9f2
Revises: a8c2e4f6b1d3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b1e3a5c7d9f2"
down_revision: str | None = "a8c2e4f6b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "generation_status" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("generation_status", sa.String(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "generation_status" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("generation_status")
