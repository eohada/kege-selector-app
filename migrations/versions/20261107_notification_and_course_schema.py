"""Add schema fields required by current notification and course models.

Revision ID: 20261107_notify_course_schema
Revises: 20261031_schema_contract_indexes
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa


revision = "20261107_notify_course_schema"
down_revision = "20261031_schema_contract_indexes"
branch_labels = None
depends_on = None


def _existing_table_name(inspector, expected_name):
    tables = {name.lower(): name for name in inspector.get_table_names()}
    return tables.get(expected_name.lower())


def _ensure_column(inspector, table_name, column):
    columns = {item["name"].lower() for item in inspector.get_columns(table_name)}
    if column.name.lower() not in columns:
        op.add_column(table_name, column)


def _ensure_index(inspector, table_name, name, columns, unique=False):
    indexes = {item["name"].lower() for item in inspector.get_indexes(table_name) if item.get("name")}
    if name.lower() not in indexes:
        op.create_index(name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    profiles_table = _existing_table_name(inspector, "UserProfiles")
    if not profiles_table:
        raise RuntimeError("Required table UserProfiles is missing")
    _ensure_column(inspector, profiles_table, sa.Column("telegram_blocked_at", sa.DateTime(), nullable=True))
    inspector = sa.inspect(bind)
    _ensure_index(inspector, profiles_table, "ix_UserProfiles_telegram_blocked_at", ["telegram_blocked_at"])

    broadcasts_table = _existing_table_name(inspector, "TelegramBroadcasts")
    if not broadcasts_table:
        raise RuntimeError("Required table TelegramBroadcasts is missing")
    _ensure_column(inspector, broadcasts_table, sa.Column("title", sa.String(length=200), nullable=True))
    _ensure_column(
        inspector,
        broadcasts_table,
        sa.Column("category", sa.String(length=50), nullable=False, server_default=sa.text("'announcement'")),
    )
    _ensure_column(inspector, broadcasts_table, sa.Column("sender_role", sa.String(length=50), nullable=True))
    _ensure_column(
        inspector,
        broadcasts_table,
        sa.Column("is_dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    subscriptions_table = _existing_table_name(inspector, "UserSubscriptions")
    if not subscriptions_table:
        raise RuntimeError("Required table UserSubscriptions is missing")
    _ensure_column(inspector, subscriptions_table, sa.Column("exam", sa.String(length=50), nullable=True))
    _ensure_column(inspector, subscriptions_table, sa.Column("subject", sa.String(length=50), nullable=True))
    _ensure_column(inspector, subscriptions_table, sa.Column("level", sa.String(length=50), nullable=True))

    if not _existing_table_name(inspector, "UserNotificationPreferences"):
        op.create_table(
            "UserNotificationPreferences",
            sa.Column("pref_id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("event_kind", sa.String(length=64), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["Users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "role", "event_kind", name="uq_user_role_event_pref"),
        )
        inspector = sa.inspect(bind)
        preferences_table = _existing_table_name(inspector, "UserNotificationPreferences")
        _ensure_index(inspector, preferences_table, "ix_UserNotificationPreferences_user_id", ["user_id"])
        _ensure_index(inspector, preferences_table, "ix_UserNotificationPreferences_role", ["role"])
        _ensure_index(inspector, preferences_table, "ix_UserNotificationPreferences_event_kind", ["event_kind"])
        _ensure_index(inspector, preferences_table, "ix_user_role_event_pref", ["user_id", "role", "event_kind"])


def downgrade():
    # Keep additive columns and the new preferences table for safe web rollback.
    pass
