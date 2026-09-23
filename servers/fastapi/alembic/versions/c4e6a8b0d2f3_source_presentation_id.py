"""link a presentation to the one whose approved outline it was created from

Revision ID: c4e6a8b0d2f3
Revises: b7d3e9f1a2c4
Create Date: 2026-09-23 14:00:00.000000

Adds presentations.source_presentation_id (FK presentations.id, ON DELETE SET NULL). The
Smart flow on the outline-review page creates a brand-new presentation from the approved
outline text of the one being reviewed, so the outline rating and the deck rating land on
two unrelated rows; this column records that link going forward.

No backfill: nothing persisted before this revision records which presentation a Smart deck
was created from (the new row only copies the outline as free text into `content`), so any
guess would be a heuristic match on text and timing, not a reliable source. Pre-existing rows
stay NULL, which the app already treats as "no source".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c4e6a8b0d2f3"
down_revision: Union[str, None] = "b7d3e9f1a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMN = "source_presentation_id"
INDEX = "ix_presentations_source_presentation_id"
FOREIGN_KEY = "fk_presentations_source_presentation_id_presentations"


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _foreign_keys(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {
        fk["name"]
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)
        if fk.get("name")
    }


def upgrade() -> None:
    if not _has_table("presentations"):
        return
    # Each step is guarded separately so a partially applied run can be re-run.
    # Batch mode: SQLite cannot ALTER ADD CONSTRAINT.
    if COLUMN not in _columns("presentations"):
        with op.batch_alter_table("presentations") as batch:
            batch.add_column(sa.Column(COLUMN, sa.Uuid(), nullable=True))
    if FOREIGN_KEY not in _foreign_keys("presentations"):
        with op.batch_alter_table("presentations") as batch:
            batch.create_foreign_key(
                FOREIGN_KEY, "presentations", [COLUMN], ["id"], ondelete="SET NULL"
            )
    if INDEX not in _indexes("presentations"):
        op.create_index(INDEX, "presentations", [COLUMN])


def downgrade() -> None:
    if COLUMN not in _columns("presentations"):
        return
    if INDEX in _indexes("presentations"):
        op.drop_index(INDEX, table_name="presentations")
    with op.batch_alter_table("presentations") as batch:
        if FOREIGN_KEY in _foreign_keys("presentations"):
            batch.drop_constraint(FOREIGN_KEY, type_="foreignkey")
        batch.drop_column(COLUMN)
