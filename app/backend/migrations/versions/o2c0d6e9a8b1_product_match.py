"""product_match table — S1 reseller-finder.

Candidate pairs from the auto-scorer plus admin decisions.

Revision ID: o2c0d6e9a8b1
Revises: n1b9c5d8e7f9
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "o2c0d6e9a8b1"
down_revision: Union[str, None] = "n1b9c5d8e7f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_VALUES = ("pending", "confirmed", "rejected")
_SOURCE_VALUES = ("auto", "manual")


def upgrade() -> None:
    status_enum = postgresql.ENUM(*_STATUS_VALUES, name="product_match_status", create_type=False)
    status_enum.create(op.get_bind(), checkfirst=True)
    source_enum = postgresql.ENUM(*_SOURCE_VALUES, name="product_match_source", create_type=False)
    source_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "product_match",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("canonical_product_id", sa.Integer(), nullable=False),
        sa.Column("alias_product_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_STATUS_VALUES, name="product_match_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "source",
            postgresql.ENUM(*_SOURCE_VALUES, name="product_match_source", create_type=False),
            nullable=False,
            server_default=sa.text("'auto'"),
        ),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_product_id"], ["product.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alias_product_id"], ["product.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_product_id", "alias_product_id", name="uq_product_match_pair"),
    )
    op.create_index("ix_product_match_canonical", "product_match", ["canonical_product_id"])
    op.create_index("ix_product_match_alias", "product_match", ["alias_product_id"])
    op.create_index("ix_product_match_status", "product_match", ["status"])


def downgrade() -> None:
    for ix in (
        "ix_product_match_status",
        "ix_product_match_alias",
        "ix_product_match_canonical",
    ):
        op.drop_index(ix, table_name="product_match")
    op.drop_table("product_match")
    op.execute("DROP TYPE IF EXISTS product_match_source")
    op.execute("DROP TYPE IF EXISTS product_match_status")
