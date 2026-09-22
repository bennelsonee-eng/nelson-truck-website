"""product_spec_table — manufacturer spec matrices, stored as tables.

Owner ask 2026-09-20: bring the specifications from the Knapheide and CM Truck
Beds model pages onto our truck-body product pages. CM's specs are key/value
and go in product_attribute; Knapheide's are model matrices (model x length x
height x width, grouped by cab-to-axle) that key/value cannot represent.

Revision ID: b6t0u4v8w2x6
Revises: s1c4g8d2e6f0
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b6t0u4v8w2x6"
down_revision: Union[str, None] = "m2p5q9r3s7t1"  # Nelson head; Titan chains this after s1c4g8d2e6f0
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_spec_table",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_spec_table_product_id", "product_spec_table", ["product_id"])
    op.create_index("ix_product_spec_table_product_sort", "product_spec_table",
                    ["product_id", "sort_order"])
    op.create_index("ix_product_spec_table_source", "product_spec_table", ["source"])


def downgrade() -> None:
    op.drop_index("ix_product_spec_table_source", table_name="product_spec_table")
    op.drop_index("ix_product_spec_table_product_sort", table_name="product_spec_table")
    op.drop_index("ix_product_spec_table_product_id", table_name="product_spec_table")
    op.drop_table("product_spec_table")
