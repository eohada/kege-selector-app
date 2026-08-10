"""Bring pre-Alembic production databases up to the mapped schema contract.

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-10 16:25:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def _actual_name(table_names, expected_name):
    expected = expected_name.lower()
    return next((name for name in table_names if name.lower() == expected), None)


def upgrade():
    """Expand missing mapped structures without changing or deleting data.

    Older BooStudy installations used ``create_all`` and manual SQL before
    Alembic. Some were stamped at a later revision despite missing structures.
    This migration reconciles those installations with the mapped metadata.
    New columns are deliberately nullable: existing rows remain valid and
    application defaults populate values written after the migration.
    """
    from app.models import db

    bind = op.get_bind()
    metadata = db.metadata
    inspector = sa.inspect(bind)
    existing_names = set(inspector.get_table_names())

    missing_tables = [
        table
        for table_name, table in metadata.tables.items()
        if _actual_name(existing_names, table_name) is None
    ]
    if missing_tables:
        metadata.create_all(bind=bind, tables=missing_tables, checkfirst=True)

    inspector = sa.inspect(bind)
    actual_tables = set(inspector.get_table_names())
    for expected_name, table in metadata.tables.items():
        table_name = _actual_name(actual_tables, expected_name)
        if table_name is None:
            continue

        existing_columns = {
            column["name"].lower() for column in inspector.get_columns(table_name)
        }
        for column in table.columns:
            if column.name.lower() in existing_columns or column.primary_key:
                continue
            op.add_column(
                table_name,
                sa.Column(
                    column.name,
                    column.type,
                    nullable=True,
                    server_default=column.server_default,
                ),
            )

    inspector = sa.inspect(bind)
    actual_tables = set(inspector.get_table_names())
    for expected_name, table in metadata.tables.items():
        table_name = _actual_name(actual_tables, expected_name)
        if table_name is None:
            continue
        existing_indexes = {
            index["name"].lower()
            for index in inspector.get_indexes(table_name)
            if index.get("name")
        }
        for index in table.indexes:
            if index.name and index.name.lower() not in existing_indexes:
                index.create(bind=bind)


def downgrade():
    # Expand-only production migration: structures are intentionally retained.
    pass
