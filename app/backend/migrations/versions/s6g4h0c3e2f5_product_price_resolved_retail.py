"""product_price.resolved_retail_price — persisted contract/sentinel retail for sorting.

Owner ask 2026-06-06 — the catalog "Price high→low / low→high" sort ordered by
the legacy ProductPrice.retail_price, while the storefront DISPLAYS the sentinel
("TITAN WEBSITE SALES", customer_number=106415) contract-resolved retail. The two
diverge by a per-brand markup (e.g. Western +11%, SnowDogg -9%), so a brand could
sort into the wrong place — Western snow plows in particular sank well below where
their *displayed* price said they belonged, making in-stock Western look "missing"
near the top of a high→low sort.

Persist the resolved retail so the sort key matches what the customer sees.
`resolved_retail_at` records when it was last computed (staleness visibility).
Recomputed after every price sync, and via app.scripts.recompute_resolved_retail.

Revision ID: s6g4h0c3e2f5
Revises: r5f3g9b2d1e4
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s6g4h0c3e2f5"
down_revision: Union[str, None] = "r5f3g9b2d1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_price",
        sa.Column("resolved_retail_price", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "product_price",
        sa.Column("resolved_retail_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Supports ORDER BY resolved_retail_price on the catalog price-sort path.
    op.create_index(
        "ix_product_price_resolved_retail_price",
        "product_price",
        ["resolved_retail_price"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_price_resolved_retail_price", table_name="product_price"
    )
    op.drop_column("product_price", "resolved_retail_at")
    op.drop_column("product_price", "resolved_retail_price")
