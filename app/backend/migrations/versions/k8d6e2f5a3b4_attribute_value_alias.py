"""attribute_value_alias + attribute_key_review tables — admin curation
of PIES product_attribute values.

The catalog left-rail drill-down surfaces `product_attribute` values as
filter buckets. Supplier feeds ship the same material with different
spellings ("TPE - Thermoplastic Elastomer" vs "Thermoplastic Elastomer
(TPE)") which splits the customer's filter clicks across multiple
buckets. The admin curator at /admin/attribute-curator lets an owner
fold the variants into a single canonical bucket; this migration adds
the persistence layer.

`attribute_value_alias`:
    For a given (attribute_key, raw_value), map to a canonical_value.
    `source` flags whether the row came from auto-rules (case/trim
    fold) or from a human merge ('manual'). The browse + facets
    endpoints consult this table before bucketing.

`attribute_key_review`:
    One row per attribute_key that's been triaged. Lets the curator
    drop a "done" key off the queue without us having to infer it
    from "no clusters left."

Revision ID: k8d6e2f5a3b4
Revises: j7c5d1e4f2b3
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k8d6e2f5a3b4"
down_revision: Union[str, None] = "j7c5d1e4f2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attribute_value_alias",
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
        sa.Column("attribute_key", sa.String(length=120), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attribute_key", "raw_value",
            name="uq_attribute_value_alias_key_raw",
        ),
    )
    op.create_index(
        "ix_attribute_value_alias_key_canonical",
        "attribute_value_alias",
        ["attribute_key", "canonical_value"],
    )

    op.create_table(
        "attribute_key_review",
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
        sa.Column("attribute_key", sa.String(length=120), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attribute_key",
            name="uq_attribute_key_review_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("attribute_key_review")
    op.drop_index(
        "ix_attribute_value_alias_key_canonical",
        table_name="attribute_value_alias",
    )
    op.drop_table("attribute_value_alias")
