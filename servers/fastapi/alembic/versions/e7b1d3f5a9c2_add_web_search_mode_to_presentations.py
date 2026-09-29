"""add web_search_mode to presentations

Revision ID: e7b1d3f5a9c2
Revises: d5f7b9c1e3a4
Create Date: 2026-09-29 10:00:00.000000

"auto" / "always" / "off" per deck. Existing rows stay NULL and keep following the old
web_search boolean (PresentationModel.effective_web_search_mode).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b1d3f5a9c2"
down_revision: Union[str, None] = "d5f7b9c1e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "web_search_mode" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(sa.Column("web_search_mode", sa.String(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "web_search_mode" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("web_search_mode")
