"""complete Telegram delivery outbox index contract

Revision ID: tg_delivery_contract_idx
Revises: telegram_delivery_indexes
"""
from alembic import op


revision = 'tg_delivery_contract_idx'
down_revision = 'telegram_delivery_indexes'
branch_labels = None
depends_on = None


def upgrade():
    for name, columns in (
        ('ix_TelegramDeliveries_notification_id', ['notification_id']),
        ('ix_TelegramDeliveries_user_id', ['user_id']),
        ('ix_telegram_delivery_due', ['status', 'next_attempt_at']),
        ('ix_telegram_delivery_recovery', ['status', 'processing_started_at']),
    ):
        op.create_index(name, 'TelegramDeliveries', columns)


def downgrade():
    for name in (
        'ix_telegram_delivery_recovery',
        'ix_telegram_delivery_due',
        'ix_TelegramDeliveries_user_id',
        'ix_TelegramDeliveries_notification_id',
    ):
        op.drop_index(name, table_name='TelegramDeliveries')
