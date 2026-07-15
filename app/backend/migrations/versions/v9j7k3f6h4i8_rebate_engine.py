"""rebate_program — audience-scoped rebate programs for the Rebate Center.

No seed (admin curates real rebates via /admin/rebates).

Revision ID: v9j7k3f6h4i8
Revises: u8i6j2e5g3h7
Create Date: 2026-06-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v9j7k3f6h4i8"
down_revision: Union[str, None] = "u8i6j2e5g3h7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUD = sa.Enum("retail", "wholesale", "both", name="rebate_audience")
_CLAIM = sa.Enum("instant", "mail_in", name="rebate_claim_method")
_TYPE = sa.Enum("fixed", "percent", "per_unit", name="rebate_type")


def upgrade() -> None:
    op.create_table(
        "rebate_program",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("amount_label", sa.String(length=40), nullable=False),
        sa.Column("rebate_type", _TYPE, server_default="fixed", nullable=False),
        sa.Column("terms", sa.String(length=200), nullable=True),
        sa.Column("threshold_label", sa.String(length=160), nullable=True),
        sa.Column("fine_print", sa.Text(), nullable=True),
        sa.Column("link_url", sa.String(length=1000), nullable=True),
        sa.Column("audience", _AUD, server_default="both", nullable=False),
        sa.Column("claim_method", _CLAIM, server_default="mail_in", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="1000", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rebate_program_audience", "rebate_program", ["audience"])


def downgrade() -> None:
    op.drop_index("ix_rebate_program_audience", table_name="rebate_program")
    op.drop_table("rebate_program")
    sa.Enum(name="rebate_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rebate_claim_method").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rebate_audience").drop(op.get_bind(), checkfirst=True)
