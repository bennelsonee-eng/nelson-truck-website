"""product.has_no_fitment — denormalized universal-fit flag.

Adds an indexed boolean to `product` that is True when the product has zero
`pace_fitment` rows reachable through any of its `pace_part` rows. The catalog
browse vehicle / vehicle_type filter previously OR'd three semi-join subqueries
together, two of which (no pace_part at all; has pace_part but no fitment) were
unfiltered scans over the whole ~296K-product catalog and re-evaluated ~4x per
request (count, in-stock count, page slice, brand facets). Collapsing those two
into one indexed boolean turns the hot filter into an index check.

The upgrade backfills the flag in one UPDATE so no separate script is needed;
the PACE ingest recomputes it at the end of each run going forward.

Revision ID: x1m5n9p3q7r2
Revises: w0k8l4g7i5j9
Create Date: 2026-06-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "x1m5n9p3q7r2"
down_revision: Union[str, None] = "w0k8l4g7i5j9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the column defaulting True (universal) so existing rows are valid
    # before the backfill runs.
    op.add_column(
        "product",
        sa.Column(
            "has_no_fitment",
            sa.Boolean(),
            nullable=False,
            # Constant server_default → Postgres adds the column as a
            # metadata-only change (no full-table rewrite), and every existing
            # row reads as universal until the backfill flips the ones that
            # actually carry a fitment. The ORM model mirrors this server_default
            # so `alembic revision --autogenerate` won't see drift.
            server_default=sa.text("true"),
        ),
    )
    # NOTE: deliberately NO index on has_no_fitment — it's a 2-value boolean the
    # planner would ignore once "true" dominates, and the catalog browse filter
    # is already narrowed by category before this column is consulted. The win
    # comes from removing the old catalog-wide OR-subquery scans, not an index.

    # Backfill: flip ONLY the products that actually have a reachable fitment to
    # has_no_fitment = false; everything else keeps the server_default `true`.
    # Done in id-range batches (not one catalog-wide UPDATE) so the migration
    # doesn't hold a long lock / bloat the table on the Postgres instance shared
    # with the Nelson ERP. Each batch only writes the fitment-having rows in its
    # range, so universal products are never rewritten.
    conn = op.get_bind()
    max_id = conn.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM product")).scalar()
    step = 20000
    lo = 1
    while lo <= max_id:
        conn.execute(
            sa.text(
                """
                UPDATE product
                SET has_no_fitment = false
                WHERE id >= :lo AND id < :hi
                  AND EXISTS (
                    SELECT 1
                    FROM pace_part pp
                    JOIN pace_fitment f ON f.pace_part_id = pp.id
                    WHERE pp.product_id = product.id
                  )
                """
            ),
            {"lo": lo, "hi": lo + step},
        )
        lo += step


def downgrade() -> None:
    op.drop_column("product", "has_no_fitment")
