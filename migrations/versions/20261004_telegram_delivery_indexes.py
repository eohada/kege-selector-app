"""add mapped indexes for Telegram delivery outbox

Revision ID: telegram_delivery_indexes
Revises: add_telegram_child_preference
"""
from alembic import op


revision = 'telegram_delivery_indexes'
down_revision = 'add_telegram_child_preference'
branch_labels = None
depends_on = None


def upgrade():
    """Add the per-column indexes declared by TelegramDelivery's model."""
    for name, column in (
        ('ix_TelegramDeliveries_telegram_chat_id', 'telegram_chat_id'),
        ('ix_TelegramDeliveries_kind', 'kind'),
        ('ix_TelegramDeliveries_priority', 'priority'),
        ('ix_TelegramDeliveries_status', 'status'),
        ('ix_TelegramDeliveries_next_attempt_at', 'next_attempt_at'),
        ('ix_TelegramDeliveries_created_at', 'created_at'),
        ('ix_TelegramDeliveries_processing_started_at', 'processing_started_at'),
    ):
        op.create_index(name, 'TelegramDeliveries', [column])


def downgrade():
    for name in (
        'ix_TelegramDeliveries_processing_started_at',
        'ix_TelegramDeliveries_created_at',
        'ix_TelegramDeliveries_next_attempt_at',
        'ix_TelegramDeliveries_status',
        'ix_TelegramDeliveries_priority',
        'ix_TelegramDeliveries_kind',
        'ix_TelegramDeliveries_telegram_chat_id',
    ):
        op.drop_index(name, table_name='TelegramDeliveries')
