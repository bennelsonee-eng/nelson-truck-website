"""attribute_value_decomposition table — A1.

Multi-output decomposition of compound PIES values (e.g. Finish="Black
Powdercoated" → (Color=Black) + (Finish=Powder Coated)). Owner ask
2026-05-17.

Revision ID: p3d1e7f0b9c2
Revises: o2c0d6e9a8b1
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p3d1e7f0b9c2"
down_revision: Union[str, None] = "o2c0d6e9a8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attribute_value_decomposition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("raw_key", sa.String(length=120), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("target_key", sa.String(length=120), nullable=False),
        sa.Column("target_canonical", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'manual'")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "raw_key", "raw_value", "target_key", "target_canonical",
            name="uq_attribute_value_decomposition_full",
        ),
    )
    op.create_index("ix_attribute_value_decomposition_raw_key",
                    "attribute_value_decomposition", ["raw_key"])
    op.create_index("ix_attribute_value_decomposition_target_key",
                    "attribute_value_decomposition", ["target_key"])


def downgrade() -> None:
    op.drop_index("ix_attribute_value_decomposition_target_key", table_name="attribute_value_decomposition")
    op.drop_index("ix_attribute_value_decomposition_raw_key", table_name="attribute_value_decomposition")
    op.drop_table("attribute_value_decomposition")
