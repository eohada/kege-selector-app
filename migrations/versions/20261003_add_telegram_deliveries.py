"""add durable Telegram delivery outbox

Revision ID: add_telegram_deliveries
Revises: rev_submission_ai_reviews
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_telegram_deliveries'
down_revision = 'rev_submission_ai_reviews'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'TelegramDeliveries',
        sa.Column('delivery_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('notification_id', sa.Integer(), sa.ForeignKey('UserNotifications.notification_id', ondelete='SET NULL'), nullable=True),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('kind', sa.String(length=50), nullable=False, server_default='generic'),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='normal'),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.UniqueConstraint('dedupe_key', name='uq_telegram_delivery_dedupe'),
    )
    op.create_index('ix_telegram_deliveries_user_id', 'TelegramDeliveries', ['user_id'])
    op.create_index('ix_telegram_deliveries_notification_id', 'TelegramDeliveries', ['notification_id'])
    op.create_index('ix_telegram_deliveries_due', 'TelegramDeliveries', ['status', 'next_attempt_at'])
    op.create_index('ix_telegram_deliveries_recovery', 'TelegramDeliveries', ['status', 'processing_started_at'])


def downgrade():
    op.drop_index('ix_telegram_deliveries_recovery', table_name='TelegramDeliveries')
    op.drop_index('ix_telegram_deliveries_due', table_name='TelegramDeliveries')
    op.drop_index('ix_telegram_deliveries_notification_id', table_name='TelegramDeliveries')
    op.drop_index('ix_telegram_deliveries_user_id', table_name='TelegramDeliveries')
    op.drop_table('TelegramDeliveries')
