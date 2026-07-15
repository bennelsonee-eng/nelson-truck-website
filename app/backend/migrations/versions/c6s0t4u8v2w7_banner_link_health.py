"""banner_slide: link health columns — nightly broken-link flagging + auto-hide.

A nightly job validates each slide's click-through link (catalog filters
resolve to >0 products, product SKU exists, landing route is valid, external
URL responds). Results land here so the admin sees a "broken link" badge, and
a broken slide is auto-hidden from the storefront until the link is fixed.

  * link_status   — 'ok' | 'broken' | 'unknown' | NULL (never checked)
  * link_checked_at — when the last check ran
  * link_error    — human-readable reason a link is broken
  * auto_hidden   — True when the checker flipped is_active off (so it can be
                    auto-restored when the link recovers, without clobbering a
                    slide the admin hid on purpose).

Revision ID: c6s0t4u8v2w7
Revises: b5r9s3t7u1v6
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6s0t4u8v2w7"
down_revision: Union[str, None] = "b5r9s3t7u1v6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("banner_slide", sa.Column("link_status", sa.String(length=20), nullable=True))
    op.add_column("banner_slide", sa.Column("link_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("banner_slide", sa.Column("link_error", sa.String(length=500), nullable=True))
    op.add_column(
        "banner_slide",
        sa.Column("auto_hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("banner_slide", "auto_hidden")
    op.drop_column("banner_slide", "link_error")
    op.drop_column("banner_slide", "link_checked_at")
    op.drop_column("banner_slide", "link_status")
