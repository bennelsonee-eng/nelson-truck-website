"""lost_sale + price_match_request tables — backfill for customer signals.

The `LostSale` and `PriceMatchRequest` models were added to the codebase
without a corresponding migration; both tables are missing from the
database. The frontend's Lost-Sale button on out-of-stock catalog rows
needs the table to exist before it can record signals.

Revision ID: l9e7f3g6b5c7
Revises: k8d6e2f5a3b4
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "l9e7f3g6b5c7"
down_revision: Union[str, None] = "k8d6e2f5a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LOST_SALE_REASONS = (
    "price_too_high",
    "out_of_stock",
    "shipping_time",
    "found_elsewhere",
    "wrong_fitment",
    "other",
)
_PRICE_MATCH_STATUSES = ("pending", "approved", "declined", "expired")


def upgrade() -> None:
    lost_sale_reason_enum = postgresql.ENUM(
        *_LOST_SALE_REASONS, name="lost_sale_reason", create_type=False
    )
    lost_sale_reason_enum.create(op.get_bind(), checkfirst=True)
    price_match_status_enum = postgresql.ENUM(
        *_PRICE_MATCH_STATUSES, name="price_match_status", create_type=False
    )
    price_match_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "lost_sale",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_token", sa.String(length=64), nullable=True),
        sa.Column(
            "reason",
            postgresql.ENUM(*_LOST_SALE_REASONS, name="lost_sale_reason", create_type=False),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lost_sale_product_id", "lost_sale", ["product_id"])
    op.create_index("ix_lost_sale_sku", "lost_sale", ["sku"])
    op.create_index("ix_lost_sale_customer_id", "lost_sale", ["customer_id"])
    op.create_index("ix_lost_sale_user_id", "lost_sale", ["user_id"])
    op.create_index("ix_lost_sale_session_token", "lost_sale", ["session_token"])

    op.create_table(
        "price_match_request",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("competitor_name", sa.String(length=200), nullable=False),
        sa.Column("competitor_url", sa.String(length=1000), nullable=True),
        sa.Column("competitor_price_usd", sa.String(length=32), nullable=False),
        sa.Column("screenshot_url", sa.String(length=1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(*_PRICE_MATCH_STATUSES, name="price_match_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_match_request_product_id", "price_match_request", ["product_id"])
    op.create_index("ix_price_match_request_sku", "price_match_request", ["sku"])
    op.create_index("ix_price_match_request_customer_id", "price_match_request", ["customer_id"])
    op.create_index("ix_price_match_request_user_id", "price_match_request", ["user_id"])
    op.create_index("ix_price_match_request_status", "price_match_request", ["status"])


def downgrade() -> None:
    for ix in (
        "ix_price_match_request_status",
        "ix_price_match_request_user_id",
        "ix_price_match_request_customer_id",
        "ix_price_match_request_sku",
        "ix_price_match_request_product_id",
    ):
        op.drop_index(ix, table_name="price_match_request")
    op.drop_table("price_match_request")
    for ix in (
        "ix_lost_sale_session_token",
        "ix_lost_sale_user_id",
        "ix_lost_sale_customer_id",
        "ix_lost_sale_sku",
        "ix_lost_sale_product_id",
    ):
        op.drop_index(ix, table_name="lost_sale")
    op.drop_table("lost_sale")
    op.execute("DROP TYPE IF EXISTS price_match_status")
    op.execute("DROP TYPE IF EXISTS lost_sale_reason")
