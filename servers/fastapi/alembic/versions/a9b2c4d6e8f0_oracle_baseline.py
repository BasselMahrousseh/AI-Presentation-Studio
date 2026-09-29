"""Add the first supported Oracle baseline; existing dialects need no DDL.

Revision ID: a9b2c4d6e8f0
Revises: f8c2d4e6a0b3
"""

from alembic import op

revision = "a9b2c4d6e8f0"
down_revision = "f8c2d4e6a0b3"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "oracle":
        from dbschema.oracle_bootstrap import apply_baseline

        apply_baseline(op.get_bind())


def downgrade():
    if op.get_bind().dialect.name == "oracle":
        raise RuntimeError("Oracle cannot downgrade below its first supported baseline; restore a backup instead")
