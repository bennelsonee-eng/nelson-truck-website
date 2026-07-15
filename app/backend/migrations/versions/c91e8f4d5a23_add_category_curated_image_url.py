"""Add category.curated_image_url for manual image curation.

Lets an admin pin a specific product image to a category so the
representative-image picker doesn't have to guess from product names.

Revision ID: c91e8f4d5a23
Revises: b5d8c3a1f4e2
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c91e8f4d5a23'
down_revision: Union[str, None] = 'b5d8c3a1f4e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'category',
        sa.Column('curated_image_url', sa.String(length=1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('category', 'curated_image_url')
