"""Jobber Phase 1 schema — multi-cart, YMM lock-in, source flag, stock snapshot,
shipped-tracking, parent/child customer hierarchy, multi-user admin role.

Implements SOW addendum 004 (A4.1, A4.2, A4.4, A4.5, A4.6, A4.10, A4.17, A4.18,
A4.20, A4.24, A4.28). RMA tables, saved part lists, notification prefs, YMM
recent search, and address-change-request models are NOT in this migration —
those are a separate slice.

Schema changes:
  * customer: + parent_customer_id (self-FK)
  * user: + is_account_admin, is_disabled_by_admin, phone
  * cart: drop unique on customer_id; + user_id, label, is_consolidation_cart, submitted_at
  * cart_line: drop unique (cart_id, product_id); + ymm_*, source, stock_breakdown_at_add, price-ack columns
  * order: + submitted_by_user_id, acting_as_*, shipped_at/by/email_sent, internal_notes, source_cart_id
  * order_line: + ymm_*, source, stock_breakdown_at_add, price-ack columns
  * new ENUM: cart_line_source (ymm_drilldown / part_lookup_with_ymm / part_lookup_no_ymm)

Revision ID: h5a3b9d2c8e1
Revises: g8c4d9e3a7b2
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h5a3b9d2c8e1"
down_revision: Union[str, None] = "g8c4d9e3a7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CART_LINE_SOURCE_VALUES = ("ymm_drilldown", "part_lookup_with_ymm", "part_lookup_no_ymm")


def upgrade() -> None:
    # ---- customer: parent bill-to / child locations (A4.10, A4.20) ----
    op.add_column("customer", sa.Column("parent_customer_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_customer_parent_customer_id",
        "customer",
        ["parent_customer_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_customer_parent_customer_id",
        "customer",
        "customer",
        ["parent_customer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- user: multi-user admin role + SMS-capable phone (A4.18, A4.20) ----
    op.add_column(
        "user",
        sa.Column(
            "is_account_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "user",
        sa.Column(
            "is_disabled_by_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("user", sa.Column("phone", sa.String(length=32), nullable=True))

    # ---- cart_line_source enum (used by cart_line.source AND order_line.source) ----
    cart_line_source_enum = postgresql.ENUM(
        *CART_LINE_SOURCE_VALUES,
        name="cart_line_source",
        create_type=False,
    )
    cart_line_source_enum.create(op.get_bind(), checkfirst=True)

    # ---- cart: concurrent carts + consolidation + submitted_at (A4.6, A4.20) ----
    op.drop_index("ix_cart_customer_id", table_name="cart")
    op.create_index("ix_cart_customer_id", "cart", ["customer_id"], unique=False)

    op.add_column("cart", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_cart_user_id", "cart", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_cart_user_id",
        "cart",
        "user",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("cart", sa.Column("label", sa.String(length=100), nullable=True))
    op.add_column(
        "cart",
        sa.Column(
            "is_consolidation_cart",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("cart", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_cart_submitted_at", "cart", ["submitted_at"], unique=False)

    # ---- cart_line: YMM lock-in, source, stock snapshot, price-ack (A4.1, A4.2, A4.4) ----
    op.drop_constraint("uq_cart_line_cart_product", "cart_line", type_="unique")

    op.add_column("cart_line", sa.Column("ymm_year", sa.Integer(), nullable=True))
    op.add_column("cart_line", sa.Column("ymm_make", sa.String(length=50), nullable=True))
    op.add_column("cart_line", sa.Column("ymm_model", sa.String(length=100), nullable=True))
    op.add_column(
        "cart_line",
        sa.Column("source", cart_line_source_enum, nullable=True),
    )
    op.add_column("cart_line", sa.Column("stock_breakdown_at_add", sa.JSON(), nullable=True))
    op.add_column(
        "cart_line",
        sa.Column("original_price", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "cart_line",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cart_line",
        sa.Column("acknowledged_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_cart_line_acknowledged_by_user_id",
        "cart_line",
        "user",
        ["acknowledged_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- order: submitter, acting-as audit, shipped tracking (A4.5, A4.17, A4.24, A4.28) ----
    op.add_column("order", sa.Column("submitted_by_user_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_order_submitted_by_user_id",
        "order",
        ["submitted_by_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_order_submitted_by_user_id",
        "order",
        "user",
        ["submitted_by_user_id"],
        ["id"],
    )

    op.add_column("order", sa.Column("acting_as_customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_order_acting_as_customer_id",
        "order",
        "customer",
        ["acting_as_customer_id"],
        ["id"],
    )

    op.add_column("order", sa.Column("acting_as_staff_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_order_acting_as_staff_user_id",
        "order",
        "user",
        ["acting_as_staff_user_id"],
        ["id"],
    )

    op.add_column("order", sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_order_shipped_at", "order", ["shipped_at"], unique=False)

    op.add_column("order", sa.Column("shipped_by_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_order_shipped_by_user_id",
        "order",
        "user",
        ["shipped_by_user_id"],
        ["id"],
    )

    op.add_column(
        "order",
        sa.Column("shipped_email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("order", sa.Column("internal_notes", sa.Text(), nullable=True))

    op.add_column("order", sa.Column("source_cart_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_order_source_cart_id",
        "order",
        "cart",
        ["source_cart_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ---- order_line: frozen YMM + source + stock snapshot + price-ack (A4.5) ----
    op.add_column("order_line", sa.Column("ymm_year", sa.Integer(), nullable=True))
    op.add_column("order_line", sa.Column("ymm_make", sa.String(length=50), nullable=True))
    op.add_column("order_line", sa.Column("ymm_model", sa.String(length=100), nullable=True))
    op.add_column(
        "order_line",
        sa.Column(
            "source",
            postgresql.ENUM(
                *CART_LINE_SOURCE_VALUES,
                name="cart_line_source",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("order_line", sa.Column("stock_breakdown_at_add", sa.JSON(), nullable=True))
    op.add_column(
        "order_line",
        sa.Column("original_price", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "order_line",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_line",
        sa.Column("acknowledged_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_order_line_acknowledged_by_user_id",
        "order_line",
        "user",
        ["acknowledged_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # ---- order_line ----
    op.drop_constraint(
        "fk_order_line_acknowledged_by_user_id", "order_line", type_="foreignkey"
    )
    op.drop_column("order_line", "acknowledged_by_user_id")
    op.drop_column("order_line", "acknowledged_at")
    op.drop_column("order_line", "original_price")
    op.drop_column("order_line", "stock_breakdown_at_add")
    op.drop_column("order_line", "source")
    op.drop_column("order_line", "ymm_model")
    op.drop_column("order_line", "ymm_make")
    op.drop_column("order_line", "ymm_year")

    # ---- order ----
    op.drop_constraint("fk_order_source_cart_id", "order", type_="foreignkey")
    op.drop_column("order", "source_cart_id")
    op.drop_column("order", "internal_notes")
    op.drop_column("order", "shipped_email_sent_at")
    op.drop_constraint("fk_order_shipped_by_user_id", "order", type_="foreignkey")
    op.drop_column("order", "shipped_by_user_id")
    op.drop_index("ix_order_shipped_at", table_name="order")
    op.drop_column("order", "shipped_at")
    op.drop_constraint("fk_order_acting_as_staff_user_id", "order", type_="foreignkey")
    op.drop_column("order", "acting_as_staff_user_id")
    op.drop_constraint("fk_order_acting_as_customer_id", "order", type_="foreignkey")
    op.drop_column("order", "acting_as_customer_id")
    op.drop_constraint("fk_order_submitted_by_user_id", "order", type_="foreignkey")
    op.drop_index("ix_order_submitted_by_user_id", table_name="order")
    op.drop_column("order", "submitted_by_user_id")

    # ---- cart_line ----
    op.drop_constraint(
        "fk_cart_line_acknowledged_by_user_id", "cart_line", type_="foreignkey"
    )
    op.drop_column("cart_line", "acknowledged_by_user_id")
    op.drop_column("cart_line", "acknowledged_at")
    op.drop_column("cart_line", "original_price")
    op.drop_column("cart_line", "stock_breakdown_at_add")
    op.drop_column("cart_line", "source")
    op.drop_column("cart_line", "ymm_model")
    op.drop_column("cart_line", "ymm_make")
    op.drop_column("cart_line", "ymm_year")
    op.create_unique_constraint(
        "uq_cart_line_cart_product", "cart_line", ["cart_id", "product_id"]
    )

    # ---- cart_line_source enum ----
    postgresql.ENUM(name="cart_line_source").drop(op.get_bind(), checkfirst=True)

    # ---- cart ----
    op.drop_index("ix_cart_submitted_at", table_name="cart")
    op.drop_column("cart", "submitted_at")
    op.drop_column("cart", "is_consolidation_cart")
    op.drop_column("cart", "label")
    op.drop_constraint("fk_cart_user_id", "cart", type_="foreignkey")
    op.drop_index("ix_cart_user_id", table_name="cart")
    op.drop_column("cart", "user_id")
    op.drop_index("ix_cart_customer_id", table_name="cart")
    op.create_index("ix_cart_customer_id", "cart", ["customer_id"], unique=True)

    # ---- user ----
    op.drop_column("user", "phone")
    op.drop_column("user", "is_disabled_by_admin")
    op.drop_column("user", "is_account_admin")

    # ---- customer ----
    op.drop_constraint("fk_customer_parent_customer_id", "customer", type_="foreignkey")
    op.drop_index("ix_customer_parent_customer_id", table_name="customer")
    op.drop_column("customer", "parent_customer_id")
