"""tg bot rewrite: notification prefs, bug report fields, lesson reminder flag

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tg_notify_subscription_expiring", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("tg_notify_bug_report_reply", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("tg_notify_daily_digest", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("tg_quiet_hours_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tg_quiet_hours_end", sa.Integer(), nullable=True))

    with op.batch_alter_table("BotErrorReports", schema=None) as batch_op:
        batch_op.add_column(sa.Column("screenshot_file_id", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("creator_tg_message_id", sa.BigInteger(), nullable=True))

    with op.batch_alter_table("Lessons", schema=None) as batch_op:
        batch_op.add_column(sa.Column("tg_reminder_30min_sent", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("Lessons", schema=None) as batch_op:
        batch_op.drop_column("tg_reminder_30min_sent")

    with op.batch_alter_table("BotErrorReports", schema=None) as batch_op:
        batch_op.drop_column("creator_tg_message_id")
        batch_op.drop_column("screenshot_file_id")

    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.drop_column("tg_quiet_hours_end")
        batch_op.drop_column("tg_quiet_hours_start")
        batch_op.drop_column("tg_notify_daily_digest")
        batch_op.drop_column("tg_notify_bug_report_reply")
        batch_op.drop_column("tg_notify_subscription_expiring")
