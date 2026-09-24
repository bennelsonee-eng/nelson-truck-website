"""Factory body options — what a truck body can be ordered with.

Knapheide and CM publish an options set per body family (grain sides, swing-out
rear gates, contractor packages, cargo tie downs, rope hooks…). Nelson's site
showed none of it, so a customer couldn't see what a body can be built with
(Ben, 2026-09-24).

These are CONTENT, not sellable line items: they're ordered with the body, so
the page lists them and invites a call. `body_option` holds the option itself
(one row per family), `product_body_option` attaches it to every body product
of that family — the ported marketing records and the ERP-sourced bodies alike.

Revision ID: g2b5c9d3e7f1
Revises: f1a4b8c2d6e0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g2b5c9d3e7f1"
down_revision: Union[str, None] = "f1a4b8c2d6e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "body_option",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand", sa.String(60), nullable=False, index=True),
        # The manufacturer's family this option belongs to: PVMX, PGND, ALSK…
        sa.Column("family", sa.String(40), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        # Our own copy of the manufacturer's render (assets live on our server).
        sa.Column("image_url", sa.String(400), nullable=True),
        sa.Column("thumb_url", sa.String(400), nullable=True),
        sa.Column("source_url", sa.String(600), nullable=True),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("brand", "family", "slug", name="uq_body_option_brand_family_slug"),
    )
    op.create_table(
        "product_body_option",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("product.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("body_option_id", sa.Integer, sa.ForeignKey("body_option.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        # How the link was made, so a rebuild can replace only its own rows.
        sa.Column("source", sa.String(40), nullable=False, server_default="body-option-rules"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_id", "body_option_id", name="uq_product_body_option"),
    )


def downgrade() -> None:
    op.drop_table("product_body_option")
    op.drop_table("body_option")
