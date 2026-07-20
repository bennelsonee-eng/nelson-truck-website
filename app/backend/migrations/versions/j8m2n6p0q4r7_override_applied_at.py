"""add catalog_override.applied_at (pending tracking).

Lets the admin tree show "pending until tonight" for any toggle made after the
last resolve: pending <=> applied_at IS NULL OR applied_at < updated_at. The
resolver stamps applied_at = now() on every override each run.

Revision ID: j8m2n6p0q4r7
Revises: i7k1m5n9p3q6
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j8m2n6p0q4r7"
down_revision: Union[str, None] = "i7k1m5n9p3q6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("catalog_override", sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("catalog_override", "applied_at")
