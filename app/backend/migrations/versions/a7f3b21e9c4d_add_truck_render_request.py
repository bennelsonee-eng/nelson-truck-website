"""add truck_render_request table for FLUX Kontext "see it on my truck" logging

Revision ID: a7f3b21e9c4d
Revises: caddd32d8040
Create Date: 2026-05-03 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3b21e9c4d'
down_revision: Union[str, None] = 'caddd32d8040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Let SQLAlchemy auto-create the enum type when it sees the column.
    # No explicit .create() call needed — the column declaration handles it.
    op.create_table(
        'truck_render_request',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Who
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id', ondelete='SET NULL'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('session_token', sa.String(length=64), nullable=True),
        # YMM (Year, Make, Model, Color) — captured for sales follow-up
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('make', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('color', sa.String(length=64), nullable=True),
        # Source truck (uploaded URL or one of our presets)
        sa.Column('truck_image_url', sa.String(length=500), nullable=True),
        sa.Column('truck_class', sa.String(length=32), nullable=True),
        # What plow they wanted to see
        sa.Column('plow_sku', sa.String(length=64), nullable=False),
        # Result
        sa.Column('rendered_image_url', sa.String(length=500), nullable=True),
        sa.Column('render_duration_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'rendering', 'complete', 'failed', 'rejected',
                                     name='truck_render_status'),
                  nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        # Analytics
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('customer_notes', sa.Text(), nullable=True),
    )
    # Indexes
    op.create_index('ix_truck_render_request_customer_id', 'truck_render_request', ['customer_id'])
    op.create_index('ix_truck_render_request_user_id', 'truck_render_request', ['user_id'])
    op.create_index('ix_truck_render_request_session_token', 'truck_render_request', ['session_token'])
    op.create_index('ix_truck_render_request_year', 'truck_render_request', ['year'])
    op.create_index('ix_truck_render_request_make', 'truck_render_request', ['make'])
    op.create_index('ix_truck_render_request_model', 'truck_render_request', ['model'])
    op.create_index('ix_truck_render_request_plow_sku', 'truck_render_request', ['plow_sku'])
    op.create_index('ix_truck_render_request_status', 'truck_render_request', ['status'])


def downgrade() -> None:
    op.drop_index('ix_truck_render_request_status', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_plow_sku', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_model', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_make', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_year', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_session_token', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_user_id', table_name='truck_render_request')
    op.drop_index('ix_truck_render_request_customer_id', table_name='truck_render_request')
    op.drop_table('truck_render_request')
    sa.Enum(name='truck_render_status').drop(op.get_bind(), checkfirst=True)
