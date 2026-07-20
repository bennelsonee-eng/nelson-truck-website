"""generalize catalog overrides + add product shipping_mode.

Turns the visibility-only override table into a general field/value override so
one admin tree drives both `is_hidden` and `shipping_mode` (owner ask
2026-07-16). The override table is empty at this point, so no data migration.

  - catalog_visibility_override -> catalog_override, gains field + value,
    drops the `hidden` bool; unique is now (scope_key, field).
  - product.shipping_mode (effective, resolver-derived) + product.base_shipping_mode
    (baseline). Seeded: weight_lb > 500 OR cta_mode = 'QUOTE_SHIPPING' ->
    'truck_freight', else 'ship'. (will_call is set manually via the tree.)

Revision ID: h6j0k4m8n2p5
Revises: g5h9j3k7m1n4
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h6j0k4m8n2p5"
down_revision: Union[str, None] = "g5h9j3k7m1n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- product shipping columns ---
    op.add_column("product", sa.Column("shipping_mode", sa.String(length=20),
                                       server_default="ship", nullable=False))
    op.add_column("product", sa.Column("base_shipping_mode", sa.String(length=20),
                                       server_default="ship", nullable=False))
    op.execute(
        "UPDATE product SET base_shipping_mode = "
        "CASE WHEN weight_lb > 500 OR cta_mode = 'QUOTE_SHIPPING' "
        "THEN 'truck_freight' ELSE 'ship' END"
    )
    op.execute("UPDATE product SET shipping_mode = base_shipping_mode")
    op.create_index("ix_product_shipping_mode", "product", ["shipping_mode"])
    op.create_index("ix_product_base_shipping_mode", "product", ["base_shipping_mode"])

    # --- generalize the override table (empty here, so no value backfill) ---
    op.rename_table("catalog_visibility_override", "catalog_override")
    op.add_column("catalog_override", sa.Column("field", sa.String(length=30),
                                                server_default="hidden", nullable=False))
    op.add_column("catalog_override", sa.Column("value", sa.String(length=50),
                                                server_default="true", nullable=False))
    op.drop_column("catalog_override", "hidden")

    op.drop_constraint("uq_visibility_override_scope_key", "catalog_override", type_="unique")
    op.create_unique_constraint(
        "uq_catalog_override_scope_field", "catalog_override", ["scope_key", "field"]
    )

    # Rename the scope indexes to match the new table name (cosmetic but tidy).
    for old, new in (
        ("ix_visibility_override_scope_type", "ix_catalog_override_scope_type"),
        ("ix_visibility_override_brand_id", "ix_catalog_override_brand_id"),
        ("ix_visibility_override_category_id", "ix_catalog_override_category_id"),
        ("ix_visibility_override_product_id", "ix_catalog_override_product_id"),
    ):
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
    op.create_index("ix_catalog_override_scope_key", "catalog_override", ["scope_key"])

    # Drop the server defaults now that existing rows are populated (matches the
    # model, which sets these in code).
    op.alter_column("catalog_override", "field", server_default=None)
    op.alter_column("catalog_override", "value", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_catalog_override_scope_key", table_name="catalog_override")
    for new, old in (
        ("ix_catalog_override_scope_type", "ix_visibility_override_scope_type"),
        ("ix_catalog_override_brand_id", "ix_visibility_override_brand_id"),
        ("ix_catalog_override_category_id", "ix_visibility_override_category_id"),
        ("ix_catalog_override_product_id", "ix_visibility_override_product_id"),
    ):
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    op.drop_constraint("uq_catalog_override_scope_field", "catalog_override", type_="unique")
    op.create_unique_constraint(
        "uq_visibility_override_scope_key", "catalog_override", ["scope_key"]
    )
    op.add_column("catalog_override", sa.Column("hidden", sa.Boolean(),
                                                server_default=sa.true(), nullable=False))
    op.execute("UPDATE catalog_override SET hidden = (value = 'true') WHERE field = 'hidden'")
    op.drop_column("catalog_override", "value")
    op.drop_column("catalog_override", "field")
    op.rename_table("catalog_override", "catalog_visibility_override")

    op.drop_index("ix_product_base_shipping_mode", table_name="product")
    op.drop_index("ix_product_shipping_mode", table_name="product")
    op.drop_column("product", "base_shipping_mode")
    op.drop_column("product", "shipping_mode")
