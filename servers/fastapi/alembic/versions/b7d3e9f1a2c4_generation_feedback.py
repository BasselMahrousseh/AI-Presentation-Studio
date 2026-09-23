"""generation feedback (thumbs up/down) and per-generation ids on presentations

Revision ID: b7d3e9f1a2c4
Revises: a1f0c2d4e6b8
Create Date: 2026-09-23 10:00:00.000000

Adds presentations.outline_generation_id / deck_generation_id (rotated by the app each time
an outline / a whole deck finishes generating) and the generation_feedback table that rates
them.

Backfill: every existing presentation that already has an outline gets its own
outline_generation_id, and every one that already has slides gets its own deck_generation_id.
Without it, all pre-existing decks would sit at NULL and their feedback could not be tied to
a generation, so the feedback endpoints would refuse it until the user regenerated. The
backfill only reads presentations.outlines and the slides table directly, so it stays fixed
at what it does today regardless of later app changes.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = "b7d3e9f1a2c4"
down_revision: Union[str, None] = "a1f0c2d4e6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _backfill_generation_ids() -> None:
    bind = op.get_bind()
    presentations = sa.table(
        "presentations",
        sa.column("id", sa.Uuid()),
        sa.column("outlines", sa.JSON()),
        sa.column("outline_generation_id", sa.Uuid()),
        sa.column("deck_generation_id", sa.Uuid()),
    )
    slides = sa.table("slides", sa.column("presentation", sa.Uuid()))

    # Legacy-schema databases (and the synthetic ones in tests/unit/test_migrations.py) may
    # lack these columns entirely; there is nothing to backfill from then.
    columns = _columns("presentations")
    if "outlines" not in columns or "id" not in columns:
        return

    # JSON null and SQL NULL both mean "no outline"; check in Python so the rule is
    # identical on SQLite and Postgres.
    rows = bind.execute(
        sa.select(presentations.c.id, presentations.c.outlines).where(
            presentations.c.outline_generation_id.is_(None)
        )
    ).all()
    for presentation_id, outlines in rows:
        if outlines:
            bind.execute(
                presentations.update()
                .where(presentations.c.id == presentation_id)
                .values(outline_generation_id=uuid.uuid4())
            )

    if "presentation" not in _columns("slides"):
        return
    deck_ids = bind.execute(
        sa.select(presentations.c.id).where(
            presentations.c.deck_generation_id.is_(None),
            sa.exists().where(slides.c.presentation == presentations.c.id),
        )
    ).scalars().all()
    for presentation_id in deck_ids:
        bind.execute(
            presentations.update()
            .where(presentations.c.id == presentation_id)
            .values(deck_generation_id=uuid.uuid4())
        )


def upgrade() -> None:
    if _has_table("presentations"):
        columns = _columns("presentations")
        if "outline_generation_id" not in columns:
            op.add_column(
                "presentations",
                sa.Column("outline_generation_id", sa.Uuid(), nullable=True),
            )
        if "deck_generation_id" not in columns:
            op.add_column(
                "presentations",
                sa.Column("deck_generation_id", sa.Uuid(), nullable=True),
            )
        _backfill_generation_ids()

    if not _has_table("generation_feedback"):
        op.create_table(
            "generation_feedback",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("owner_id", sa.Uuid(), nullable=True),
            sa.Column("presentation_id", sa.Uuid(), nullable=True),
            sa.Column("stage", sa.String(16), nullable=False),
            sa.Column("generation_id", sa.Uuid(), nullable=False),
            sa.Column("rating", sa.SmallInteger(), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("context", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["presentation_id"], ["presentations.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "presentation_id",
                "stage",
                "generation_id",
                name="uq_generation_feedback_owner_generation",
            ),
        )
    indexes = _indexes("generation_feedback")
    if "ix_generation_feedback_owner_id" not in indexes:
        op.create_index(
            "ix_generation_feedback_owner_id", "generation_feedback", ["owner_id"]
        )
    if "ix_generation_feedback_presentation_id" not in indexes:
        op.create_index(
            "ix_generation_feedback_presentation_id",
            "generation_feedback",
            ["presentation_id"],
        )


def downgrade() -> None:
    if _has_table("generation_feedback"):
        indexes = _indexes("generation_feedback")
        for name in (
            "ix_generation_feedback_presentation_id",
            "ix_generation_feedback_owner_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="generation_feedback")
        op.drop_table("generation_feedback")
    to_drop = [
        name
        for name in ("deck_generation_id", "outline_generation_id")
        if name in _columns("presentations")
    ]
    if to_drop:
        # batch mode: SQLite cannot DROP COLUMN on older versions.
        with op.batch_alter_table("presentations") as batch:
            for name in to_drop:
                batch.drop_column(name)
