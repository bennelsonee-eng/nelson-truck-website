"""product_resource table — scraped PDFs, videos, manuals.

Owner ask 2026-05-18 after the first Buyers image scrape — wanted to
also capture the rich content (manuals, datasheets, install videos)
the brand sites carry.

Revision ID: q4e2f8a1c0d3
Revises: p3d1e7f0b9c2
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "q4e2f8a1c0d3"
down_revision: Union[str, None] = "p3d1e7f0b9c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KINDS = (
    "manual", "datasheet", "brochure", "installation",
    "parts_list", "spec_sheet", "video", "diagram", "other",
)


def upgrade() -> None:
    kind_enum = postgresql.ENUM(*_KINDS, name="resource_kind", create_type=False)
    kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "product_resource",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(*_KINDS, name="resource_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "url", name="uq_product_resource_url"),
    )
    op.create_index("ix_product_resource_product_id", "product_resource", ["product_id"])
    op.create_index("ix_product_resource_kind", "product_resource", ["kind"])
    op.create_index("ix_product_resource_source", "product_resource", ["source"])


def downgrade() -> None:
    for ix in ("ix_product_resource_source", "ix_product_resource_kind", "ix_product_resource_product_id"):
        op.drop_index(ix, table_name="product_resource")
    op.drop_table("product_resource")
    op.execute("DROP TYPE IF EXISTS resource_kind")
