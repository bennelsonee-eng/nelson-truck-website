"""attribute_key_alias — curator-confirmed merges of whole attribute KEYS.

One level up from attribute_value_alias (which merges VALUES within a key),
this table merges KEYS that describe the same physical attribute under
different names. Motivating case: the Transfer Tanks browse rail surfaces four
separate facet groups — "Volume", "Gallon Capacity", "Liquid Storage Capacity",
"WEB: Box Width/Tank Capacity" — that all describe tank gallons. The curator
folds them into one group; this is the persistence layer.

Each member key (including the one whose name becomes the group_label) gets a
row mapping member_key -> group_label, so a group resolves with a single
WHERE group_label = :label lookup. source='manual' (curator confirmed).

Label-variant keys that differ only by formatting ("Overall Length" vs
"Overall Length (in.)") are folded deterministically at render time and need
no rows here.

Revision ID: w0k8l4g7i5j9
Revises: v9j7k3f6h4i8
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w0k8l4g7i5j9"
down_revision: Union[str, None] = "v9j7k3f6h4i8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attribute_key_alias",
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
        sa.Column("member_key", sa.String(length=120), nullable=False),
        sa.Column("group_label", sa.String(length=120), nullable=False),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "member_key",
            name="uq_attribute_key_alias_member",
        ),
    )
    op.create_index(
        "ix_attribute_key_alias_group_label",
        "attribute_key_alias",
        ["group_label"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_attribute_key_alias_group_label",
        table_name="attribute_key_alias",
    )
    op.drop_table("attribute_key_alias")
