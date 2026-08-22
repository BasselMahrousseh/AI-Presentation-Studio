"""add the selected Smart brand template to presentations

Revision ID: e4a6c8d0f2b1
Revises: d2f4a6b8c0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e4a6c8d0f2b1"
down_revision: str | None = "d2f4a6b8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "smart_template" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("smart_template", sa.String(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "smart_template" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("smart_template")
