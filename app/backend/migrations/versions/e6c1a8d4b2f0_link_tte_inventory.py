"""Link TTE inventory to website products

Adds:
  * product.tte_ourparts_num     — TigerTech internal SKU (e.g. 'RSPH4-6K-G4-CANBUS').
                                   Indexed for inventory-sync lookups.  Not unique
                                   because some products will legitimately map to
                                   multiple legacy SKUs (aliases / part-number
                                   consolidations).
  * product_inventory.available  — reservable stock (onhand minus allocations).
                                   May be lower than on_hand if there are open
                                   orders.  Nullable: legacy rows have no value.
  * product_inventory.gl_cost    — per-unit GL cost.  Drives our cost-floor in
                                   the pricing engine when stocked-cost beats
                                   the parts-master P5 fallback.  Nullable.

Revision ID: e6c1a8d4b2f0
Revises: c91e8f4d5a23
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6c1a8d4b2f0'
down_revision: Union[str, None] = 'c91e8f4d5a23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'product',
        sa.Column('tte_ourparts_num', sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f('ix_product_tte_ourparts_num'),
        'product',
        ['tte_ourparts_num'],
        unique=False,
    )
    op.add_column(
        'product_inventory',
        sa.Column('available', sa.Integer(), nullable=True),
    )
    op.add_column(
        'product_inventory',
        sa.Column('gl_cost', sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('product_inventory', 'gl_cost')
    op.drop_column('product_inventory', 'available')
    op.drop_index(op.f('ix_product_tte_ourparts_num'), table_name='product')
    op.drop_column('product', 'tte_ourparts_num')
