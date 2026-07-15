"""build_idea — admin-only future-build backlog.

Owner ask 2026-06-25: a repository for future build ideas, viewable only by
admin (Issue #15 was meant to be parked here). Stores manually-added ideas plus
ones promoted from error reports (source_report_id links back).

Revision ID: f4g8h2j6k0m3
Revises: e8u2v6w0x4y9
Create Date: 2026-06-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4g8h2j6k0m3"
down_revision: Union[str, None] = "e8u2v6w0x4y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "build_idea",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.String(length=80), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="idea", nullable=False),
        sa.Column("priority", sa.String(length=10), server_default="normal", nullable=False),
        sa.Column("source", sa.String(length=40), server_default="manual", nullable=False),
        sa.Column("source_report_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_build_idea_status", "build_idea", ["status"])
    op.create_index("ix_build_idea_priority", "build_idea", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_build_idea_priority", table_name="build_idea")
    op.drop_index("ix_build_idea_status", table_name="build_idea")
    op.drop_table("build_idea")
