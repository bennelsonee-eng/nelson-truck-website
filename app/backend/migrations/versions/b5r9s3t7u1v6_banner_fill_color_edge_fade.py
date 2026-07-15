"""banner_slide: fill_color + edge_fade — graceful display for undersized art.

Adds two optional presentation columns so the admin can handle banner images
that are smaller than the 1200x325 (3.7:1) hero frame without ugly upscaling:

  * fill_color — when set (e.g. '#0b1f3a'), the slide renders the image at its
    natural size centered in the frame, with the rest of the banner space filled
    by this solid color (instead of the default blurred-backdrop fill).
  * edge_fade — feather the image's outer edges to transparent so a too-small
    image melts into the fill color out to the edge of the banner space.

NULL fill_color preserves the original blurred-backdrop + object-contain look.

Revision ID: b5r9s3t7u1v6
Revises: a4q8r2s6t0u5
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5r9s3t7u1v6"
down_revision: Union[str, None] = "a4q8r2s6t0u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("banner_slide", sa.Column("fill_color", sa.String(length=9), nullable=True))
    op.add_column(
        "banner_slide",
        sa.Column("edge_fade", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("banner_slide", "edge_fade")
    op.drop_column("banner_slide", "fill_color")
