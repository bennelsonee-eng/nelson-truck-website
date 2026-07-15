"""RMA Return Request tables — email-based Phase 1 per SOW A4.31.

Two tables (rma_request + rma_line) + two enums (rma_reason + rma_status).
Phase 1 only writes SUBMITTED / CANCELLED statuses from the website; the
APPROVED/DENIED/RECEIVED/REFUNDED/CLOSED values are declared up-front so
Phase 2 (Titan ERP wiring) doesn't need an enum-type migration.

Revision ID: i6b4c0d3e1a2
Revises: h5a3b9d2c8e1
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "i6b4c0d3e1a2"
down_revision: Union[str, None] = "h5a3b9d2c8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RMA_REASON_VALUES = (
    "defective_doa",
    "wrong_part_shipped",
    "damaged_shipping",
    "customer_error",
    "other",
)
RMA_STATUS_VALUES = (
    "submitted",
    "cancelled",
    "approved",
    "denied",
    "received",
    "refunded",
    "closed",
)


def upgrade() -> None:
    rma_reason_enum = postgresql.ENUM(
        *RMA_REASON_VALUES, name="rma_reason", create_type=False
    )
    rma_status_enum = postgresql.ENUM(
        *RMA_STATUS_VALUES, name="rma_status", create_type=False
    )
    rma_reason_enum.create(op.get_bind(), checkfirst=True)
    rma_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rma_request",
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
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", rma_status_enum, nullable=False, server_default="submitted"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("photo_metadata", sa.JSON(), nullable=True),
        sa.Column("total_photo_bytes", sa.Integer(), nullable=True),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["order.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rma_request_order_id", "rma_request", ["order_id"], unique=False)
    op.create_index(
        "ix_rma_request_requested_by_user_id",
        "rma_request",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index("ix_rma_request_status", "rma_request", ["status"], unique=False)

    op.create_table(
        "rma_line",
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
        sa.Column("rma_request_id", sa.Integer(), nullable=False),
        sa.Column("order_line_id", sa.Integer(), nullable=False),
        sa.Column("qty_to_return", sa.Integer(), nullable=False),
        sa.Column("reason", rma_reason_enum, nullable=False),
        sa.Column("line_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rma_request_id"], ["rma_request.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["order_line_id"], ["order_line.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rma_line_rma_request_id", "rma_line", ["rma_request_id"], unique=False
    )
    op.create_index(
        "ix_rma_line_order_line_id", "rma_line", ["order_line_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_rma_line_order_line_id", table_name="rma_line")
    op.drop_index("ix_rma_line_rma_request_id", table_name="rma_line")
    op.drop_table("rma_line")

    op.drop_index("ix_rma_request_status", table_name="rma_request")
    op.drop_index("ix_rma_request_requested_by_user_id", table_name="rma_request")
    op.drop_index("ix_rma_request_order_id", table_name="rma_request")
    op.drop_table("rma_request")

    postgresql.ENUM(name="rma_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="rma_reason").drop(op.get_bind(), checkfirst=True)
