"""customer: showroom mode config (white-label retail kiosk).

Adds account-wide Retail Showroom Mode config to `customer`:
  * showroom_enabled   — jobber/dealer has opted in / set it up
  * showroom_logo_url  — uploaded white-label logo (else default "Online Catalog")
  * showroom_display_name — name shown on receipts (defaults to customer.name)

Markup reuses the existing customer.retail_view_markup_percent. The active kiosk
lock is per-device (frontend), not stored here. Presentation-only — no fitment /
pricing data risk.

Revision ID: d7t1u5v9w3x8
Revises: c6s0t4u8v2w7
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7t1u5v9w3x8"
down_revision: Union[str, None] = "c6s0t4u8v2w7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("showroom_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("customer", sa.Column("showroom_logo_url", sa.String(length=1000), nullable=True))
    op.add_column("customer", sa.Column("showroom_display_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("customer", "showroom_display_name")
    op.drop_column("customer", "showroom_logo_url")
    op.drop_column("customer", "showroom_enabled")
