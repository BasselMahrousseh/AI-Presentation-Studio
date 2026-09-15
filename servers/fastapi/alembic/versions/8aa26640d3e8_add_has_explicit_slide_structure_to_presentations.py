"""add has_explicit_slide_structure to presentations

Revision ID: 8aa26640d3e8
Revises: b1e3a5c7d9f2
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8aa26640d3e8"
down_revision: str | None = "b1e3a5c7d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Frozen copy of utils/outline_utils.py's EXPLICIT_SLIDE_MARKER_PATTERN /
# detect_explicit_slide_count() as of this migration. Deliberately not
# imported from the live module - migrations must not depend on application
# code that can change after this migration has already run against real
# data. Do not "fix" this by importing the live function if it's edited
# later; write a new migration instead if historical rows ever need
# re-backfilling under updated logic.
_EXPLICIT_SLIDE_MARKER_PATTERN = re.compile(r"(?im)^\s*slide\s+(\d{1,3})\s*[-–—:.)]")


def _detect_explicit_slide_count_frozen(content: str | None) -> int | None:
    if not content:
        return None

    matches = _EXPLICIT_SLIDE_MARKER_PATTERN.findall(content)
    if len(matches) < 2:
        return None

    numbers = sorted({int(match) for match in matches})
    if numbers != list(range(1, len(numbers) + 1)):
        return None

    return len(numbers)


def _backfill_has_explicit_slide_structure() -> None:
    # Every row that already exists is left at has_explicit_slide_structure =
    # NULL by the column-add above. If left NULL, stream_outlines()'s "first
    # call" branch would treat it as never-yet-detected and fall back to
    # n_slides > 0 - which, for any row that has already been streamed once,
    # holds a value this same endpoint backfilled itself and is exactly the
    # unreliable signal this whole fix exists to stop trusting. So a row that
    # correctly detected has_explicit_slide_structure=true on its one call so
    # far would silently flip to false on its next call after this migration
    # ships, unless backfilled here first - relocating the original bug to
    # the migration boundary instead of fixing it. This backfill closes that
    # gap by deriving the real value directly from content, the same source
    # of truth stream_outlines() itself uses, rather than from n_slides.
    #
    # Idempotent by construction: only ever selects rows still at NULL, so a
    # second run (e.g. a retried migration) touches zero rows.
    bind = op.get_bind()
    presentations = sa.table(
        "presentations",
        sa.column("id"),
        sa.column("content"),
        sa.column("has_explicit_slide_structure"),
    )
    rows = bind.execute(
        sa.select(presentations.c.id, presentations.c.content).where(
            presentations.c.has_explicit_slide_structure.is_(None)
        )
    ).fetchall()
    for row in rows:
        detected = _detect_explicit_slide_count_frozen(row.content) is not None
        bind.execute(
            presentations.update()
            .where(presentations.c.id == row.id)
            .values(has_explicit_slide_structure=detected)
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "has_explicit_slide_structure" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(
                sa.Column("has_explicit_slide_structure", sa.Boolean(), nullable=True)
            )

    # Only meaningful (and only safe to query) once the table actually has a
    # content column - some test/legacy schema snapshots upgraded through
    # this migration intentionally model an intermediate table shape that
    # doesn't include it yet (mirrors the same defensive column-existence
    # guard REVISION_SMART_MODE_BACKFILL already uses for its own backfill).
    # A real deployment always has content, since it's a required column
    # from this model's very first revision.
    if "content" in columns:
        _backfill_has_explicit_slide_structure()


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "has_explicit_slide_structure" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("has_explicit_slide_structure")
