"""telegram deep link token, broadcast, deadline reminder log

Revision ID: a1b2c3d4e5f6
Revises: 9f2b7c6e1a11
Create Date: 2026-04-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "9f2b7c6e1a11"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("telegram_link_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("telegram_link_token_expires", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("telegram_last_interaction_at", sa.DateTime(), nullable=True)
        )
    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.create_index(
            "ix_UserProfiles_telegram_link_token", ["telegram_link_token"], unique=True
        )
        batch_op.create_index(
            "ix_UserProfiles_telegram_last_interaction_at",
            ["telegram_last_interaction_at"],
            unique=False,
        )

    op.create_table(
        "TelegramBroadcasts",
        sa.Column("broadcast_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("photo_url", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("recipient_scope", sa.String(length=64), nullable=False),
        sa.Column("total_planned", sa.Integer(), nullable=False),
        sa.Column("sent_ok", sa.Integer(), nullable=False),
        sa.Column("sent_failed", sa.Integer(), nullable=False),
        sa.Column("cursor_last_user_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["Users.id"],
        ),
        sa.PrimaryKeyConstraint("broadcast_id"),
    )
    op.create_index(
        op.f("ix_TelegramBroadcasts_created_by_user_id"),
        "TelegramBroadcasts",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_TelegramBroadcasts_cursor_last_user_id"),
        "TelegramBroadcasts",
        ["cursor_last_user_id"],
        unique=False,
    )

    op.create_table(
        "SubmissionTelegramDeadlineSents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("window_key", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["Submissions.submission_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "window_key", name="uq_submission_deadline_window"),
    )
    op.create_index(
        op.f("ix_SubmissionTelegramDeadlineSents_submission_id"),
        "SubmissionTelegramDeadlineSents",
        ["submission_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_SubmissionTelegramDeadlineSents_submission_id"),
        table_name="SubmissionTelegramDeadlineSents",
    )
    op.drop_table("SubmissionTelegramDeadlineSents")

    op.drop_index(
        op.f("ix_TelegramBroadcasts_cursor_last_user_id"),
        table_name="TelegramBroadcasts",
    )
    op.drop_index(
        op.f("ix_TelegramBroadcasts_created_by_user_id"),
        table_name="TelegramBroadcasts",
    )
    op.drop_table("TelegramBroadcasts")

    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.drop_index("ix_UserProfiles_telegram_last_interaction_at")
        batch_op.drop_index("ix_UserProfiles_telegram_link_token")
    with op.batch_alter_table("UserProfiles", schema=None) as batch_op:
        batch_op.drop_column("telegram_last_interaction_at")
        batch_op.drop_column("telegram_link_token_expires")
        batch_op.drop_column("telegram_link_token")
