"""add weather alert subscribers

Revision ID: caddd32d8040
Revises: 119f036526e0
Create Date: 2026-04-28 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'caddd32d8040'
down_revision: Union[str, None] = '119f036526e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'weather_alert_subscriber',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=False),
        sa.Column('zip_code', sa.String(length=10), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('nws_office', sa.String(length=8), nullable=True),
        sa.Column('nws_grid_x', sa.Integer(), nullable=True),
        sa.Column('nws_grid_y', sa.Integer(), nullable=True),
        sa.Column('location_label', sa.String(length=80), nullable=True),
        sa.Column('nws_resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('alert_opt_in', sa.Boolean(), nullable=False, server_default=sa.text('TRUE')),
        sa.Column('promo_opt_in', sa.Boolean(), nullable=False, server_default=sa.text('FALSE')),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('confirmation_token', sa.String(length=64), nullable=False),
        sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
        sa.Column('unsubscribed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unsubscribe_reason', sa.String(length=200), nullable=True),
        sa.Column('last_alert_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_alert_subject', sa.String(length=200), nullable=True),
        sa.Column('total_alerts_sent', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('source_url', sa.String(length=200), nullable=True),
        sa.Column('user_agent', sa.String(length=400), nullable=True),
    )
    op.create_unique_constraint('uq_weather_alert_subscriber_email', 'weather_alert_subscriber', ['email'])
    op.create_unique_constraint('uq_weather_alert_subscriber_confirmation_token', 'weather_alert_subscriber', ['confirmation_token'])
    op.create_unique_constraint('uq_weather_alert_subscriber_unsubscribe_token', 'weather_alert_subscriber', ['unsubscribe_token'])
    op.create_index('ix_weather_alert_subscriber_email', 'weather_alert_subscriber', ['email'])
    op.create_index('ix_weather_alert_subscriber_zip_code', 'weather_alert_subscriber', ['zip_code'])
    op.create_index('ix_weather_alert_subscriber_confirmed_at', 'weather_alert_subscriber', ['confirmed_at'])
    op.create_index('ix_weather_alert_subscriber_unsubscribed_at', 'weather_alert_subscriber', ['unsubscribed_at'])
    op.create_index('ix_weather_alert_subscriber_confirmation_token', 'weather_alert_subscriber', ['confirmation_token'])
    op.create_index('ix_weather_alert_subscriber_unsubscribe_token', 'weather_alert_subscriber', ['unsubscribe_token'])


def downgrade() -> None:
    op.drop_index('ix_weather_alert_subscriber_unsubscribe_token', table_name='weather_alert_subscriber')
    op.drop_index('ix_weather_alert_subscriber_confirmation_token', table_name='weather_alert_subscriber')
    op.drop_index('ix_weather_alert_subscriber_unsubscribed_at', table_name='weather_alert_subscriber')
    op.drop_index('ix_weather_alert_subscriber_confirmed_at', table_name='weather_alert_subscriber')
    op.drop_index('ix_weather_alert_subscriber_zip_code', table_name='weather_alert_subscriber')
    op.drop_index('ix_weather_alert_subscriber_email', table_name='weather_alert_subscriber')
    op.drop_table('weather_alert_subscriber')
