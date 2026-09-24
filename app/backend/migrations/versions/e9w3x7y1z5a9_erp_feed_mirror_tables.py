"""Mirror tables for the ERP's customer and supplier master data.

`cus190_erp` and `sup190_erp` hold a copy of the ERP's `customers` / `vendors`
(the data that arrives nightly as the CUS190 and SUP190 feeds). The "_erp"
suffix says where the rows come from: they are written only by
scripts/sync_erp_feeds.py, never edited here.

Why a mirror rather than a live read: the ERP database is a separate Postgres
on the same box, and the website shouldn't hold a connection open to it while
serving pages. The website's own `customer` table stays the app's (it carries
logins, addresses people edit, order history); these are the reference copy it
is filled from.

Money and collections columns are deliberately left out — balances, aging and
holds stay in the ERP. What's here is master data: who they are, where they
are, their terms and tax status.

Revision ID: e9w3x7y1z5a9
Revises: d8v2w6x0y4z8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9w3x7y1z5a9"
down_revision: Union[str, None] = "d8v2w6x0y4z8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cus190_erp",
        sa.Column("customer_number", sa.String(32), primary_key=True),
        sa.Column("erp_id", sa.Integer, nullable=True, index=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("contact", sa.String(120), nullable=True),
        sa.Column("address1", sa.String(200), nullable=True),
        sa.Column("address2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(10), nullable=True),
        sa.Column("zip", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("fax", sa.String(40), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("terms", sa.String(40), nullable=True),
        sa.Column("tax_code", sa.String(20), nullable=True),
        sa.Column("tax_exempt", sa.Boolean, nullable=True),
        sa.Column("status", sa.String(10), nullable=True),
        sa.Column("price_type", sa.String(20), nullable=True),
        sa.Column("bill_to_customer", sa.String(32), nullable=True),
        sa.Column("po_required", sa.Boolean, nullable=True),
        sa.Column("sales_rep", sa.String(60), nullable=True),
        sa.Column("territory", sa.String(60), nullable=True),
        sa.Column("location_code", sa.String(20), nullable=True),
        sa.Column("default_warehouse", sa.String(20), nullable=True),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cus190_erp_name", "cus190_erp", ["name"])
    op.create_index("ix_cus190_erp_bill_to", "cus190_erp", ["bill_to_customer"])

    op.create_table(
        "sup190_erp",
        sa.Column("supplier_code", sa.String(32), primary_key=True),
        sa.Column("erp_id", sa.Integer, nullable=True, index=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("contact", sa.String(120), nullable=True),
        sa.Column("address1", sa.String(200), nullable=True),
        sa.Column("address2", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("state", sa.String(10), nullable=True),
        sa.Column("zip", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("fax", sa.String(40), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("terms", sa.String(40), nullable=True),
        sa.Column("status", sa.String(10), nullable=True),
        sa.Column("prod_code", sa.String(20), nullable=True, index=True),
        sa.Column("alpha_code", sa.String(20), nullable=True),
        sa.Column("supplier_type", sa.String(40), nullable=True),
        sa.Column("supplier_class", sa.String(40), nullable=True),
        sa.Column("payment_type", sa.String(40), nullable=True),
        sa.Column("po_required", sa.Boolean, nullable=True),
        sa.Column("ship_via", sa.String(60), nullable=True),
        sa.Column("min_order_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_prepaid_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sup190_erp_name", "sup190_erp", ["name"])


def downgrade() -> None:
    op.drop_table("sup190_erp")
    op.drop_table("cus190_erp")
