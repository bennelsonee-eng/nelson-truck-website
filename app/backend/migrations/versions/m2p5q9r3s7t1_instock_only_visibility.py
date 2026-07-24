"""in-stock-only visibility: instock_only_<channel> columns.

Adds product.instock_only_{retail,wholesale,dealer,municipality} (bool, default
false) — the "Hidden except in-stock" per-customer-channel mode. The catalog
resolver materializes is_hidden_<channel> = hard-hidden OR (instock_only AND
on_hand<=0), so an in_stock_only item shows only while in stock and auto-hides
the moment it sells out (blowout/clearance — no re-order at the discount). The
15-min inventory sync re-materializes + re-indexes it when stock changes; cart +
checkout enforce the live quantity cap. Owner ask 2026-07-22.

Revision ID: m2p5q9r3s7t1
Revises: l1n4p8q2r6s0
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m2p5q9r3s7t1"
down_revision: Union[str, None] = "l1n4p8q2r6s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHANNELS = ("retail", "wholesale", "dealer", "municipality")


def upgrade() -> None:
    for ch in _CHANNELS:
        op.add_column(
            "product",
            sa.Column(f"instock_only_{ch}", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
        # Partial index over just the (few) in_stock_only rows so the 15-min
        # stock recompute finds them instantly instead of scanning ~326K products.
        op.create_index(
            f"ix_product_instock_only_{ch}", "product", ["id"],
            postgresql_where=sa.text(f"instock_only_{ch}"),
        )


def downgrade() -> None:
    for ch in _CHANNELS:
        op.drop_index(f"ix_product_instock_only_{ch}", table_name="product")
        op.drop_column("product", f"instock_only_{ch}")
