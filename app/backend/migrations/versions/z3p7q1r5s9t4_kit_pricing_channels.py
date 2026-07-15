"""kit channel availability + price-source flags.

Owner ask 2026-06-17: admin sets per-kit pricing (Retail / Municipality / Dealer
/ Wholesale — stored in product_price) AND dictates which channels a kit is
available to (retail / wholesale / dealer / municipality). A visitor whose
channel isn't allowed should not see the kit at all. `price_is_manual` records
whether the package product's prices were set on the kit (vs ERP-synced) so the
suggester knows when to offer a component-sum default.

Revision ID: z3p7q1r5s9t4
Revises: y2n6o0r4s8t3
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z3p7q1r5s9t4"
down_revision: Union[str, None] = "y2n6o0r4s8t3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for col in ("avail_retail", "avail_wholesale", "avail_dealer", "avail_municipality"):
        op.add_column("kit", sa.Column(
            col, sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("kit", sa.Column(
        "price_is_manual", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    for col in ("price_is_manual", "avail_municipality", "avail_dealer",
                "avail_wholesale", "avail_retail"):
        op.drop_column("kit", col)
