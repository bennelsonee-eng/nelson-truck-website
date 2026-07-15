"""banner_slide table — homepage ad banner CMS (audience-scoped, scheduled).

Phase 1 of the homepage redesign. Seeds the current titantruck.com hero slides
(audience='retail') so the storefront banner is data-driven from day one;
wholesale slides are added later via /admin/banners.

Revision ID: t7h5i1d4f2g6
Revises: s6g4h0c3e2f5
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t7h5i1d4f2g6"
down_revision: Union[str, None] = "s6g4h0c3e2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AUDIENCE = sa.Enum("retail", "wholesale", "both", name="banner_audience")


def upgrade() -> None:
    op.create_table(
        "banner_slide",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("image_url", sa.String(length=1000), nullable=False),
        sa.Column("alt", sa.String(length=300), server_default="", nullable=False),
        sa.Column("link_url", sa.String(length=1000), nullable=True),
        sa.Column("audience", _AUDIENCE, server_default="both", nullable=False),
        sa.Column("placement", sa.String(length=50), server_default="home_hero", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_banner_slide_audience", "banner_slide", ["audience"])
    op.create_index("ix_banner_slide_placement", "banner_slide", ["placement"])

    # Seed the current titantruck.com hero slides (retail audience).
    banner_slide = sa.table(
        "banner_slide",
        sa.column("image_url", sa.String),
        sa.column("alt", sa.String),
        sa.column("link_url", sa.String),
        # Type the column as the (already-created) enum so asyncpg binds the
        # value as banner_audience instead of plain varchar.
        sa.column("audience", sa.Enum("retail", "wholesale", "both", name="banner_audience", create_type=False)),
        sa.column("placement", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        banner_slide,
        [
            {"image_url": "https://www.titantruck.com/images/F4181000.png", "alt": "Now open Saturdays", "link_url": None, "audience": "retail", "placement": "home_hero", "sort_order": 1, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180648.webp", "alt": "Superwinch Tigershark", "link_url": "/catalog?brand=Superwinch", "audience": "retail", "placement": "home_hero", "sort_order": 2, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180637.png", "alt": "Yakima — Titan picks, typically in stock", "link_url": "/catalog?brand=Yakima%20Products", "audience": "retail", "placement": "home_hero", "sort_order": 3, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180649.webp", "alt": "Yakima", "link_url": "/catalog?brand=Yakima%20Products", "audience": "retail", "placement": "home_hero", "sort_order": 4, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F3417030.png", "alt": "Financing with Affirm", "link_url": None, "audience": "retail", "placement": "home_hero", "sort_order": 5, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4184508.png", "alt": "Customer Appreciation Event", "link_url": "https://www.facebook.com/titantruck/", "audience": "retail", "placement": "home_hero", "sort_order": 6, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180642.webp", "alt": "ARC Lighting — SAE", "link_url": "/catalog?brand=Arc%20Lighting", "audience": "retail", "placement": "home_hero", "sort_order": 7, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180998.png", "alt": "BAK Industries", "link_url": "/catalog?brand=Bak%20Industries", "audience": "retail", "placement": "home_hero", "sort_order": 8, "is_active": True},
            {"image_url": "https://www.titantruck.com/images/F4180643.webp", "alt": "Go Rhino E-Board", "link_url": "/catalog?brand=Go%20Rhino", "audience": "retail", "placement": "home_hero", "sort_order": 9, "is_active": True},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_banner_slide_placement", table_name="banner_slide")
    op.drop_index("ix_banner_slide_audience", table_name="banner_slide")
    op.drop_table("banner_slide")
    sa.Enum(name="banner_audience").drop(op.get_bind(), checkfirst=True)
