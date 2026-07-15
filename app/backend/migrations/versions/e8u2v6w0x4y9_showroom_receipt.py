"""showroom_receipt — customer-facing retail receipts for Showroom Mode.

Revision ID: e8u2v6w0x4y9
Revises: d7t1u5v9w3x8
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8u2v6w0x4y9"
down_revision: Union[str, None] = "d7t1u5v9w3x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "showroom_receipt",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("receipt_number", sa.String(length=32), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="unpaid", nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("logo_url", sa.String(length=1000), nullable=True),
        sa.Column("lines", sa.JSON(), nullable=True),
        sa.Column("retail_subtotal", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("retail_tax", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.Column("retail_total", sa.Numeric(10, 2), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_showroom_receipt_customer_id", "showroom_receipt", ["customer_id"])
    op.create_index("ix_showroom_receipt_receipt_number", "showroom_receipt", ["receipt_number"])


def downgrade() -> None:
    op.drop_index("ix_showroom_receipt_receipt_number", table_name="showroom_receipt")
    op.drop_index("ix_showroom_receipt_customer_id", table_name="showroom_receipt")
    op.drop_table("showroom_receipt")
