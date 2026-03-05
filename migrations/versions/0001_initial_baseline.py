"""Initial baseline migration.

This is a baseline migration that represents the existing database schema.
It does not create any tables — the existing schema was created by SQLAlchemy
create_all() and manual ALTER TABLE statements in db_migrations.py.

To adopt Alembic on an existing database, run:
    flask db stamp head

This will mark the database as being at this revision without running any SQL.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
