"""add source_quality_flags and acknowledged_quality_flag_groups to presentations

Revision ID: c3f8a1b2d4e6
Revises: 8aa26640d3e8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3f8a1b2d4e6"
down_revision: str | None = "8aa26640d3e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = ("source_quality_flags", "acknowledged_quality_flag_groups")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    with op.batch_alter_table("presentations") as batch_op:
        for column_name in _COLUMNS:
            if column_name not in columns:
                batch_op.add_column(sa.Column(column_name, sa.JSON(), nullable=True))

    # No backfill: NULL means "not yet computed for this row" (this feature didn't
    # exist when the row was created), which is a correct, non-blocking state for
    # every pre-existing presentation - there is no stale proxy signal being
    # consulted here the way has_explicit_slide_structure's own NULL once was.


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    with op.batch_alter_table("presentations") as batch_op:
        for column_name in _COLUMNS:
            if column_name in columns:
                batch_op.drop_column(column_name)
