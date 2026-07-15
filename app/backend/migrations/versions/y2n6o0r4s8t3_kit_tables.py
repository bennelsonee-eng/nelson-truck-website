"""kit + kit_component tables — bundle/package kits (e.g. WeatherGuard van packages).

Owner ask 2026-06-17: a kit database for the WeatherGuard van packages — each
kit is a sellable package product with a bill-of-materials of component part
numbers + quantities, plus vehicle fitment (make/model/wheelbase/roof). Drives
the admin "Create a kit package" wizard and the storefront package-contents
display. Generalizes the unused plow_kit pattern.

Revision ID: y2n6o0r4s8t3
Revises: x1m5n9p3q7r2
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y2n6o0r4s8t3"
down_revision: Union[str, None] = "x1m5n9p3q7r2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("kit_type", sa.String(length=40), nullable=False,
                  server_default=sa.text("'van_package'")),
        sa.Column("trade", sa.String(length=80), nullable=True),
        sa.Column("vehicle_make", sa.String(length=80), nullable=True),
        sa.Column("vehicle_model", sa.String(length=120), nullable=True),
        sa.Column("wheelbase", sa.String(length=40), nullable=True),
        sa.Column("roof_height", sa.String(length=40), nullable=True),
        sa.Column("hand", sa.String(length=8), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", name="uq_kit_sku"),
    )
    op.create_index("ix_kit_product_id", "kit", ["product_id"])
    op.create_index("ix_kit_type", "kit", ["kit_type"])

    op.create_table(
        "kit_component",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("kit_id", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["kit_id"], ["kit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kit_component_kit_id", "kit_component", ["kit_id"])
    op.create_index("ix_kit_component_product_id", "kit_component", ["product_id"])
    op.create_index("ix_kit_component_part_number", "kit_component", ["part_number"])


def downgrade() -> None:
    for ix in ("ix_kit_component_part_number", "ix_kit_component_product_id", "ix_kit_component_kit_id"):
        op.drop_index(ix, table_name="kit_component")
    op.drop_table("kit_component")
    for ix in ("ix_kit_type", "ix_kit_product_id"):
        op.drop_index(ix, table_name="kit")
    op.drop_table("kit")
