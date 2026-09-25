"""Units for sale: watch the ERP's orders and quotes, and let the admin tag listings.

Ben, 2026-09-25: units get written up in the legacy ERP "from time to time", and
a write-up is not a sale. A customer without an account has bought only when
there is money down; a customer with an account, only when the order carries a
valid PO. Everything else is a quote, and the unit stays for sale. Sold units
stay on the site, marked SOLD, "for people to see what we sold".

  erp_unit_order   the open orders and quotes in the ERP that touch a unit's
                   part number, with each one classified sale / quote /
                   internal and the reason, refreshed with the inventory job.
  unit_listing.tags  admin-chosen badges -- "Hot item", "New build",
                   "Price reduced" or anything typed.

Revision ID: i4d7e1f5a9b3
Revises: h3c6d0e4f8a2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i4d7e1f5a9b3"
down_revision: Union[str, None] = "h3c6d0e4f8a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("unit_listing", sa.Column("tags", postgresql.JSONB, nullable=False,
                                            server_default=sa.text("'[]'::jsonb")))
    op.create_table(
        "erp_unit_order",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("part_number", sa.String(60), nullable=False, index=True),
        sa.Column("serial", sa.String(40), nullable=True),
        sa.Column("order_number", sa.String(20), nullable=False),
        sa.Column("order_type", sa.String(4), nullable=True),
        sa.Column("order_status", sa.String(20), nullable=True),
        sa.Column("order_date", sa.Date, nullable=True),
        sa.Column("customer_number", sa.String(20), nullable=True),
        sa.Column("customer_name", sa.String(160), nullable=True),
        sa.Column("terms", sa.String(12), nullable=True),
        sa.Column("is_account", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("po_number", sa.String(40), nullable=True),
        sa.Column("po_valid", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deposit_received", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("is_internal", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("qty_ordered", sa.Numeric(12, 2), nullable=True),
        # sale | quote | internal
        sa.Column("classification", sa.String(12), nullable=False, index=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("erp_unit_order")
    op.drop_column("unit_listing", "tags")
