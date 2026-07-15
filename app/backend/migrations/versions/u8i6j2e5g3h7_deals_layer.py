"""deal_collection + deal_item — Deals layer for the Deal Warehouse homepage.

No seed data (admin curates real deals via /admin/deals); the homepage degrades
gracefully when nothing is configured.

Revision ID: u8i6j2e5g3h7
Revises: t7h5i1d4f2g6
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "u8i6j2e5g3h7"
down_revision: Union[str, None] = "t7h5i1d4f2g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAL_AUD = sa.Enum("retail", "wholesale", "both", name="deal_audience")
_ITEM_AUD = sa.Enum("retail", "wholesale", "both", name="deal_item_audience")
_ITEM_KIND = sa.Enum("product", "highlight", name="deal_item_kind")


def upgrade() -> None:
    op.create_table(
        "deal_collection",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("placement", sa.String(length=50), server_default="home", nullable=False),
        sa.Column("audience", _DEAL_AUD, server_default="both", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="1000", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deal_collection_audience", "deal_collection", ["audience"])
    op.create_index("ix_deal_collection_placement", "deal_collection", ["placement"])

    op.create_table(
        "deal_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("kind", _ITEM_KIND, nullable=False),
        sa.Column("audience", _ITEM_AUD, server_default="both", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("badge_label", sa.String(length=60), nullable=True),
        sa.Column("badge_tone", sa.String(length=20), nullable=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("sublabel", sa.String(length=120), nullable=True),
        sa.Column("icon", sa.String(length=16), nullable=True),
        sa.Column("link_url", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["collection_id"], ["deal_collection.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deal_item_collection_id", "deal_item", ["collection_id"])
    op.create_index("ix_deal_item_kind", "deal_item", ["kind"])
    op.create_index("ix_deal_item_audience", "deal_item", ["audience"])
    op.create_index("ix_deal_item_sku", "deal_item", ["sku"])


def downgrade() -> None:
    op.drop_table("deal_item")
    op.drop_table("deal_collection")
    sa.Enum(name="deal_item_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="deal_item_audience").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="deal_audience").drop(op.get_bind(), checkfirst=True)
