"""catalog visibility tree + admin message board.

Adds:
  - product.base_hidden — the non-override visibility baseline (importers write
    this). product.is_hidden becomes the resolver-derived effective flag.
    Backfilled = is_hidden so nothing changes on day one.
  - catalog_visibility_override — one row per admin show/hide toggle
    (brand / category / filter / product scope).
  - admin_message — the admin-only message board (kit conflicts + site health).

Revision ID: g5h9j3k7m1n4
Revises: f4g8h2j6k0m3
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g5h9j3k7m1n4"
down_revision: Union[str, None] = "f4g8h2j6k0m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Baseline visibility column on product, backfilled from current is_hidden.
    op.add_column(
        "product",
        sa.Column("base_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE product SET base_hidden = is_hidden")
    op.create_index("ix_product_base_hidden", "product", ["base_hidden"])

    # 2. Admin show/hide overrides.
    op.create_table(
        "catalog_visibility_override",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_key", sa.String(length=400), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("attr_key", sa.String(length=200), nullable=True),
        sa.Column("attr_value", sa.String(length=400), nullable=True),
        sa.Column("hidden", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=200), server_default="", nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", name="uq_visibility_override_scope_key"),
    )
    op.create_index("ix_visibility_override_scope_type", "catalog_visibility_override", ["scope_type"])
    op.create_index("ix_visibility_override_brand_id", "catalog_visibility_override", ["brand_id"])
    op.create_index("ix_visibility_override_category_id", "catalog_visibility_override", ["category_id"])
    op.create_index("ix_visibility_override_product_id", "catalog_visibility_override", ["product_id"])

    # 3. Admin message board.
    op.create_table(
        "admin_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), server_default="warning", nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("dedupe_key", sa.String(length=400), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_by", sa.String(length=200), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_admin_message_dedupe_key"),
    )
    op.create_index("ix_admin_message_kind", "admin_message", ["kind"])
    op.create_index("ix_admin_message_severity", "admin_message", ["severity"])
    op.create_index("ix_admin_message_status", "admin_message", ["status"])


def downgrade() -> None:
    op.drop_index("ix_admin_message_status", table_name="admin_message")
    op.drop_index("ix_admin_message_severity", table_name="admin_message")
    op.drop_index("ix_admin_message_kind", table_name="admin_message")
    op.drop_table("admin_message")

    op.drop_index("ix_visibility_override_product_id", table_name="catalog_visibility_override")
    op.drop_index("ix_visibility_override_category_id", table_name="catalog_visibility_override")
    op.drop_index("ix_visibility_override_brand_id", table_name="catalog_visibility_override")
    op.drop_index("ix_visibility_override_scope_type", table_name="catalog_visibility_override")
    op.drop_table("catalog_visibility_override")

    op.drop_index("ix_product_base_hidden", table_name="product")
    op.drop_column("product", "base_hidden")
