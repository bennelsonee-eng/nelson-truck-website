"""customer_link_request table — email-gated User → Customer linkage.

Closes the self-link exploit in /api/auth/signup + /api/auth/link-customer
where any user could claim any Customer record's customer_number and inherit
that customer's pricing tier. After this migration, all linkage goes through
a request → email sales → admin approval flow.

Revision ID: j7c5d1e4f2b3
Revises: i6b4c0d3e1a2
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "j7c5d1e4f2b3"
down_revision: Union[str, None] = "i6b4c0d3e1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CLR_STATUS_VALUES = ("pending", "approved", "rejected")


def upgrade() -> None:
    clr_status_enum = postgresql.ENUM(
        *CLR_STATUS_VALUES, name="customer_link_request_status", create_type=False
    )
    clr_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "customer_link_request",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("requested_customer_number", sa.String(length=20), nullable=False),
        sa.Column("billing_zip", sa.String(length=20), nullable=True),
        sa.Column("additional_info", sa.Text(), nullable=True),
        sa.Column(
            "status",
            clr_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_link_request_user_id",
        "customer_link_request",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_customer_link_request_requested_customer_number",
        "customer_link_request",
        ["requested_customer_number"],
        unique=False,
    )
    op.create_index(
        "ix_customer_link_request_status",
        "customer_link_request",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_link_request_status", table_name="customer_link_request"
    )
    op.drop_index(
        "ix_customer_link_request_requested_customer_number",
        table_name="customer_link_request",
    )
    op.drop_index(
        "ix_customer_link_request_user_id", table_name="customer_link_request"
    )
    op.drop_table("customer_link_request")
    postgresql.ENUM(name="customer_link_request_status").drop(
        op.get_bind(), checkfirst=True
    )
