"""inquiry + newsletter_subscriber — quote/contact requests and newsletter sign-ups.

Launch audit 2026-09-22: quote buttons, the contact links and the newsletter
form delivered nothing to Nelson. Inquiries are stored first, then emailed.

Revision ID: d8v2w6x0y4z8
Revises: c7u1v5w9x3y7
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8v2w6x0y4z8"
down_revision: Union[str, None] = "c7u1v5w9x3y7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inquiry",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="contact"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("branch", sa.String(length=20), nullable=True),
        sa.Column("product_sku", sa.String(length=80), nullable=True),
        sa.Column("product_name", sa.String(length=300), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("page_url", sa.String(length=500), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by", sa.String(length=254), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inquiry_kind", "inquiry", ["kind"])
    op.create_index("ix_inquiry_status", "inquiry", ["status"])
    op.create_index("ix_inquiry_product_sku", "inquiry", ["product_sku"])
    op.create_index("ix_inquiry_created_at", "inquiry", ["created_at"])

    op.create_table(
        "newsletter_subscriber",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_newsletter_subscriber_email"),
    )


def downgrade() -> None:
    op.drop_table("newsletter_subscriber")
    op.drop_index("ix_inquiry_created_at", table_name="inquiry")
    op.drop_index("ix_inquiry_product_sku", table_name="inquiry")
    op.drop_index("ix_inquiry_status", table_name="inquiry")
    op.drop_index("ix_inquiry_kind", table_name="inquiry")
    op.drop_table("inquiry")
