"""workspace identity (user.external_subject) and deck favourites

Revision ID: a1f0c2d4e6b8
Revises: c3f8a1b2d4e6
Create Date: 2026-09-21 16:00:00.000000

Existing rows need no backfill here: external_subject NULL means "local Studio account", and
is_favorite defaults to false, which is the correct value for every existing deck. Reassigning
existing decks to Workspace users needs mapping data from outside this database, so it is done
by scripts/backfill_deck_owners.py at cutover instead.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1f0c2d4e6b8"
down_revision: Union[str, None] = "c3f8a1b2d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # A missing table means a fresh/partial database that create_all() will build with the new
    # columns already in place, so there is nothing to alter.
    if _has_table("user"):
        if "external_subject" not in _columns("user"):
            op.add_column("user", sa.Column("external_subject", sa.String(256), nullable=True))
        if "ix_user_external_subject" not in _indexes("user"):
            op.create_index("ix_user_external_subject", "user", ["external_subject"], unique=True)
    if _has_table("presentations") and "is_favorite" not in _columns("presentations"):
        op.add_column(
            "presentations",
            sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "is_favorite" in _columns("presentations"):
        op.drop_column("presentations", "is_favorite")
    if "ix_user_external_subject" in _indexes("user"):
        op.drop_index("ix_user_external_subject", table_name="user")
    if "external_subject" in _columns("user"):
        op.drop_column("user", "external_subject")
