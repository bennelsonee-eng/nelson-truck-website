"""kit availability window — schedule when a package is live.

Owner ask 2026-06-18: a kit (package) should be sellable only within a date
window — typically "available until <end date>" for seasonal / limited-time
packages, with an optional start date to schedule one to go live later. Both
null = open-ended. Folds into the existing "is this kit live" check
(is_active + channel availability), so an out-of-window kit hides everywhere.

Revision ID: a4q8r2s6t0u5
Revises: z3p7q1r5s9t4
Create Date: 2026-06-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4q8r2s6t0u5"
down_revision: Union[str, None] = "z3p7q1r5s9t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("kit", sa.Column("available_from", sa.Date(), nullable=True))
    op.add_column("kit", sa.Column("available_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("kit", "available_until")
    op.drop_column("kit", "available_from")
