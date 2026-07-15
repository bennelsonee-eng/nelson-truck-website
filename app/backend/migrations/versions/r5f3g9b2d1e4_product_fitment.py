"""product_fitment table — scraped (non-ACES) vehicle compatibility.

Owner ask 2026-05-22 — Buyers mount-family pages (Layout A in the
scraper's terminology) carry a year/make/model grid that doesn't fit
the ACES/VCDB stack (no clean way to resolve scraped text like
"RAM 1500 2002-2005" to a VCDB base_vehicle_id without a fuzzy
matcher). Store as a plain-text fallback that the /fitments endpoint
falls through to when no PaceFitment rows exist for a SKU.

Revision ID: r5f3g9b2d1e4
Revises: q4e2f8a1c0d3
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r5f3g9b2d1e4"
down_revision: Union[str, None] = "q4e2f8a1c0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_fitment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("year_start", sa.SmallInteger(), nullable=True),
        sa.Column("year_end", sa.SmallInteger(), nullable=True),
        sa.Column("make", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(length=60), nullable=False,
            server_default=sa.text("'buyersproducts.com'"),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "make", "model", "year_start", "year_end", "source",
            name="uq_product_fitment_unique",
        ),
    )
    # Per-product lookup (FK column index)
    op.create_index("ix_product_fitment_product_id", "product_fitment", ["product_id"])
    # Single-column lookups for filtering
    op.create_index("ix_product_fitment_make", "product_fitment", ["make"])
    op.create_index("ix_product_fitment_model", "product_fitment", ["model"])
    # Composite — reverse lookup "what products fit RAM 1500?"
    op.create_index("ix_product_fitment_make_model", "product_fitment", ["make", "model"])


def downgrade() -> None:
    for ix in (
        "ix_product_fitment_make_model",
        "ix_product_fitment_model",
        "ix_product_fitment_make",
        "ix_product_fitment_product_id",
    ):
        op.drop_index(ix, table_name="product_fitment")
    op.drop_table("product_fitment")
