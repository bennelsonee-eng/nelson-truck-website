"""product_accessory — parts and sized bodies listed under a truck body.

Owner ask 2026-09-21: the Knapheide parts that were filed on "Truck Bodies"
(bumpers, hitches, mount kits, bulkheads, latches, lights ...) should be listed
as options underneath the correct truck body, and the sized bodies we stock
(6108D54, PGTB-96, PVMX-125 ...) under the model they are a configuration of.
One row per (body, part), grouped for display. `rule` records which mapping
rule placed it so a wrong placement can be traced and corrected.

Revision ID: c7u1v5w9x3y7
Revises: b6t0u4v8w2x6
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7u1v5w9x3y7"
down_revision: Union[str, None] = "b6t0u4v8w2x6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_accessory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("body_product_id", sa.Integer(), nullable=False),
        sa.Column("part_product_id", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("rule", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(["body_product_id"], ["product.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part_product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("body_product_id", "part_product_id", name="uq_product_accessory_pair"),
    )
    op.create_index("ix_product_accessory_body", "product_accessory", ["body_product_id"])
    op.create_index("ix_product_accessory_part", "product_accessory", ["part_product_id"])
    op.create_index("ix_product_accessory_source", "product_accessory", ["source"])


def downgrade() -> None:
    op.drop_index("ix_product_accessory_source", table_name="product_accessory")
    op.drop_index("ix_product_accessory_part", table_name="product_accessory")
    op.drop_index("ix_product_accessory_body", table_name="product_accessory")
    op.drop_table("product_accessory")
