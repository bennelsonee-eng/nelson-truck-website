"""Add snow plow configurator tables (Phase 1 scaffold)

Schema scaffold for the YMM-class-driven kit configurator described in
docs/snow_plow_configurator_design.md.

Tables introduced (all empty after migration — Phase 2 populates):

  * vehicle_class           — 4-bucket customer-facing class picker
                              (Cab Chassis / 3/4-ton / 1/2-ton / Mid-size)
  * vehicle_application     — one row per YMM spread that shares an
                              interchangeable plow mount + harness
  * plow_application_part   — cross-brand mapping: which mount / harness
                              SKUs satisfy a given application
  * plow_kit                — virtual buildable kit (model + width + light)
                              that decomposes to N real SKUs at checkout
  * plow_kit_component      — universal (non-application-specific) parts
                              in a kit (moldboard / box / lights)

Seeds the 4 vehicle_class rows as part of the upgrade so the UI has a
stable target to render even before Phase 2 data lands.

Revision ID: f7a3b8e2c9d1
Revises: e6c1a8d4b2f0
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a3b8e2c9d1"
down_revision: Union[str, None] = "e6c1a8d4b2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VEHICLE_CLASS_SEED = [
    # Code mirrors what the React picker will send.  internal_classes is the
    # list of buckets from snow_plow_recommender.TruckClass that this front-end
    # bucket maps to — used at recommend time to widen the candidate pool.
    {"code": "mid_size", "name": "Mid Size Truck/SUV",
     "internal_classes": ["mid-size"], "sort_order": 10},
    {"code": "half_ton", "name": "1/2 ton Truck",
     "internal_classes": ["1500"], "sort_order": 20},
    {"code": "three_quarter_ton", "name": "3/4-ton Full Size Truck",
     "internal_classes": ["2500", "3500"], "sort_order": 30},
    {"code": "cab_chassis", "name": "Cab Chassis",
     "internal_classes": ["4500", "5500"], "sort_order": 40},
]


def upgrade() -> None:
    # -------------------- vehicle_class --------------------
    op.create_table(
        "vehicle_class",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("internal_classes", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_vehicle_class_code"),
    )

    # -------------------- vehicle_application --------------------
    op.create_table(
        "vehicle_application",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_class_id", sa.Integer(), nullable=False),
        sa.Column("year_start", sa.Integer(), nullable=False),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("make", sa.String(length=50), nullable=False),
        sa.Column("model_range", sa.String(length=200), nullable=False),
        sa.Column("display_label", sa.String(length=300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["vehicle_class_id"], ["vehicle_class.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_vehicle_application_class", "vehicle_application", ["vehicle_class_id"])
    op.create_index("ix_vehicle_application_make_year",
                    "vehicle_application", ["make", "year_start", "year_end"])

    # -------------------- plow_application_part --------------------
    op.create_table(
        "plow_application_part",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        # part_role values: mount | harness_halogen | harness_led |
        #                   harness_universal | mount_adapter
        sa.Column("part_role", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["application_id"], ["vehicle_application.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("application_id", "product_id", "part_role",
                            name="uq_application_product_role"),
    )
    op.create_index("ix_plow_application_part_application",
                    "plow_application_part", ["application_id"])
    op.create_index("ix_plow_application_part_product",
                    "plow_application_part", ["product_id"])
    op.create_index("ix_plow_application_part_brand_role",
                    "plow_application_part", ["brand_id", "part_role"])

    # -------------------- plow_kit --------------------
    op.create_table(
        "plow_kit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        # Free-form id matching snow_plow_catalog.PlowModel.id, e.g.
        # "western-pro-plus", "meyer-super-v", "snowdogg-vxf".
        sa.Column("plow_model_id", sa.String(length=64), nullable=False),
        sa.Column("blade_width", sa.String(length=10), nullable=False),
        # halogen | led
        sa.Column("light_option", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("sku", name="uq_plow_kit_sku"),
    )
    op.create_index("ix_plow_kit_brand_model", "plow_kit", ["brand_id", "plow_model_id"])

    # -------------------- plow_kit_component --------------------
    op.create_table(
        "plow_kit_component",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kit_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        # part_role values: moldboard | box_assembly | lights | accessory
        sa.Column("part_role", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["kit_id"], ["plow_kit.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("kit_id", "part_role", "product_id",
                            name="uq_kit_role_product"),
    )

    # -------------------- seed vehicle_class --------------------
    vc_table = sa.table(
        "vehicle_class",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("internal_classes", sa.JSON),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(vc_table, VEHICLE_CLASS_SEED)


def downgrade() -> None:
    op.drop_table("plow_kit_component")
    op.drop_index("ix_plow_kit_brand_model", table_name="plow_kit")
    op.drop_table("plow_kit")
    op.drop_index("ix_plow_application_part_brand_role", table_name="plow_application_part")
    op.drop_index("ix_plow_application_part_product", table_name="plow_application_part")
    op.drop_index("ix_plow_application_part_application", table_name="plow_application_part")
    op.drop_table("plow_application_part")
    op.drop_index("ix_vehicle_application_make_year", table_name="vehicle_application")
    op.drop_index("ix_vehicle_application_class", table_name="vehicle_application")
    op.drop_table("vehicle_application")
    op.drop_table("vehicle_class")
