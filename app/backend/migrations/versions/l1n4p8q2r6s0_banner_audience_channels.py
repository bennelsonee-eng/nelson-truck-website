"""banner audience: add dealer + municipality channels.

Extends the `banner_audience` enum so homepage banner slides can target each
customer channel (retail / wholesale=jobber / dealer / municipality) in addition
to the catch-all 'both'. Owner ask 2026-07-22.

Postgres cannot run `ALTER TYPE ... ADD VALUE` inside a transaction block, so we
use Alembic's autocommit_block(). `IF NOT EXISTS` makes it idempotent.

Revision ID: l1n4p8q2r6s0
Revises: k9n3p7q1r5s8
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "l1n4p8q2r6s0"
down_revision: Union[str, None] = "k9n3p7q1r5s8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE banner_audience ADD VALUE IF NOT EXISTS 'dealer'")
        op.execute("ALTER TYPE banner_audience ADD VALUE IF NOT EXISTS 'municipality'")


def downgrade() -> None:
    # Postgres can't drop a value from an enum type without recreating the type
    # and rewriting every dependent column. The extra values are harmless once
    # the app stops writing them, so downgrade is intentionally a no-op.
    pass
