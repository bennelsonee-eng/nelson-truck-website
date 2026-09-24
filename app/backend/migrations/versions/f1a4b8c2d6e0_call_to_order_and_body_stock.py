"""Call-to-order CTA, and per-product "show every branch's stock".

Two things truck bodies need (Ben, 2026-09-24):

1. A $16K service body shouldn't sit behind "Add to Cart" with no freight
   cost. `cta_mode` gains `call_to_order`, which shows both branch numbers.

2. Bodies are sold across both companies, so their stock counts Spokane as
   well as Portland and Kent — the opposite of the storefront default set in
   services/stock_scope.py, where Spokane stock belongs to titantruck.com.
   `show_all_branch_stock` turns that on per product.

Revision ID: f1a4b8c2d6e0
Revises: e9w3x7y1z5a9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a4b8c2d6e0"
down_revision: Union[str, None] = "e9w3x7y1z5a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres enums can't gain a value inside a transaction block on older
    # servers; ALTER TYPE ... ADD VALUE IF NOT EXISTS is safe to re-run.
    op.execute("ALTER TYPE cta_mode ADD VALUE IF NOT EXISTS 'CALL_TO_ORDER'")
    op.add_column(
        "product",
        sa.Column("show_all_branch_stock", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_product_show_all_branch_stock", "product", ["show_all_branch_stock"])


def downgrade() -> None:
    op.drop_index("ix_product_show_all_branch_stock", table_name="product")
    op.drop_column("product", "show_all_branch_stock")
    # The enum value is left in place — dropping one means rebuilding the type.
