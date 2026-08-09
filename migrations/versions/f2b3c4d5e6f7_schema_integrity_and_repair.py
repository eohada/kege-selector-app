"""Schema integrity and repair migration (forward-only compatibility).

Revision ID: f2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-08 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "f2b3c4d5e6f7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # 1. Ensure UserProfiles columns exist
    if "UserProfiles" in existing_tables:
        up_cols = {c['name'] for c in inspector.get_columns("UserProfiles")}
        with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
            if "telegram_username" not in up_cols:
                batch_op.add_column(sa.Column("telegram_username", sa.String(length=64), nullable=True))
            if "discord_id" not in up_cols:
                batch_op.add_column(sa.Column("discord_id", sa.String(length=64), nullable=True))
            if "cover_url" not in up_cols:
                batch_op.add_column(sa.Column("cover_url", sa.String(length=512), nullable=True))
            if "telegram_link_token" not in up_cols:
                batch_op.add_column(sa.Column("telegram_link_token", sa.String(length=64), nullable=True))
            if "telegram_link_token_expires" not in up_cols:
                batch_op.add_column(sa.Column("telegram_link_token_expires", sa.DateTime(), nullable=True))
            if "telegram_last_interaction_at" not in up_cols:
                batch_op.add_column(sa.Column("telegram_last_interaction_at", sa.DateTime(), nullable=True))
            if "tg_notify_subscription_expiring" not in up_cols:
                batch_op.add_column(sa.Column("tg_notify_subscription_expiring", sa.Boolean(), nullable=False, server_default=sa.true()))
            if "tg_notify_bug_report_reply" not in up_cols:
                batch_op.add_column(sa.Column("tg_notify_bug_report_reply", sa.Boolean(), nullable=False, server_default=sa.true()))
            if "tg_notify_daily_digest" not in up_cols:
                batch_op.add_column(sa.Column("tg_notify_daily_digest", sa.Boolean(), nullable=False, server_default=sa.false()))
            if "tg_quiet_hours_start" not in up_cols:
                batch_op.add_column(sa.Column("tg_quiet_hours_start", sa.Integer(), nullable=True))
            if "tg_quiet_hours_end" not in up_cols:
                batch_op.add_column(sa.Column("tg_quiet_hours_end", sa.Integer(), nullable=True))

    # 2. Ensure TheoryBlocks read_minutes exists
    if "TheoryBlocks" in existing_tables:
        tb_cols = {c['name'] for c in inspector.get_columns("TheoryBlocks")}
        if "read_minutes" not in tb_cols:
            with op.batch_alter_table("TheoryBlocks") as batch_op:
                batch_op.add_column(sa.Column("read_minutes", sa.Integer(), nullable=False, server_default="5"))

    # 3. Ensure Answers needs_revision exists
    if "Answers" in existing_tables:
        ans_cols = {c['name'] for c in inspector.get_columns("Answers")}
        if "needs_revision" not in ans_cols:
            with op.batch_alter_table("Answers") as batch_op:
                batch_op.add_column(sa.Column("needs_revision", sa.Boolean(), nullable=False, server_default=sa.false()))

    # 4. Ensure Users timezone columns exist
    if "Users" in existing_tables:
        usr_cols = {c['name'] for c in inspector.get_columns("Users")}
        with op.batch_alter_table("Users") as batch_op:
            if "timezone_mode" not in usr_cols:
                batch_op.add_column(sa.Column("timezone_mode", sa.String(length=16), nullable=False, server_default="auto"))
            if "timezone_iana" not in usr_cols:
                batch_op.add_column(sa.Column("timezone_iana", sa.String(length=64), nullable=True))


def downgrade():
    pass
