"""brand.special_order_lead_time_min/max_days — L9.

Manufacturer lead-time for special-order (OOS but orderable) items.
Owner ask 2026-05-17. Two nullable integers; UI renders "typically X-Y
business days" alongside the Special-order label.

Revision ID: n1b9c5d8e7f9
Revises: m0a8b4c7d6e8
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n1b9c5d8e7f9"
down_revision: Union[str, None] = "m0a8b4c7d6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brand", sa.Column("special_order_lead_time_min_days", sa.Integer(), nullable=True))
    op.add_column("brand", sa.Column("special_order_lead_time_max_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("brand", "special_order_lead_time_max_days")
    op.drop_column("brand", "special_order_lead_time_min_days")
