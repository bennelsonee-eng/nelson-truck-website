"""back_in_stock_alert table — L7.

Subscription rows: notify (email) when (sku) returns to in-stock. The
nightly notifier job sweeps unsent rows and marks notified_at when the
product's on_hand total flips positive.

Revision ID: m0a8b4c7d6e8
Revises: l9e7f3g6b5c7
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m0a8b4c7d6e8"
down_revision: Union[str, None] = "l9e7f3g6b5c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "back_in_stock_alert",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_token", sa.String(length=64), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku", "email", name="uq_bis_sku_email"),
    )
    op.create_index("ix_back_in_stock_alert_product_id", "back_in_stock_alert", ["product_id"])
    op.create_index("ix_back_in_stock_alert_sku", "back_in_stock_alert", ["sku"])
    op.create_index("ix_back_in_stock_alert_user_id", "back_in_stock_alert", ["user_id"])
    op.create_index("ix_back_in_stock_alert_session_token", "back_in_stock_alert", ["session_token"])
    op.create_index("ix_back_in_stock_alert_notified_at", "back_in_stock_alert", ["notified_at"])


def downgrade() -> None:
    for ix in (
        "ix_back_in_stock_alert_notified_at",
        "ix_back_in_stock_alert_session_token",
        "ix_back_in_stock_alert_user_id",
        "ix_back_in_stock_alert_sku",
        "ix_back_in_stock_alert_product_id",
    ):
        op.drop_index(ix, table_name="back_in_stock_alert")
    op.drop_table("back_in_stock_alert")
