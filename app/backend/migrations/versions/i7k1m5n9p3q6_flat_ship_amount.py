"""add product flat_ship_amount (flat-rate shipping override).

A third field the admin catalog tree can override (owner ask 2026-07-16):
NULL = weight-tiered freight (today's behavior); 0.00 = free shipping; > 0 =
flat amount. Nullable, so the baseline is simply NULL for the whole catalog —
no seed.

Revision ID: i7k1m5n9p3q6
Revises: h6j0k4m8n2p5
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i7k1m5n9p3q6"
down_revision: Union[str, None] = "h6j0k4m8n2p5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product", sa.Column("flat_ship_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("product", sa.Column("base_flat_ship_amount", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("product", "base_flat_ship_amount")
    op.drop_column("product", "flat_ship_amount")
