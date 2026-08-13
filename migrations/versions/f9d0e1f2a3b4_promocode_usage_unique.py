"""Prevent a promo code from being redeemed twice by one account.

Revision ID: f9d0e1f2a3b4
Revises: f8c9d0e1f2a3
"""
from alembic import op
import sqlalchemy as sa


revision = 'f9d0e1f2a3b4'
down_revision = 'f8c9d0e1f2a3'
branch_labels = None
depends_on = None


CONSTRAINT_NAME = 'uq_promocode_usage_per_user'
TABLE_NAME = 'PromoCodeUsage'


def _unique_constraint_exists(bind) -> bool:
    inspector = sa.inspect(bind)
    names = {
        item['name'].lower()
        for item in inspector.get_unique_constraints(TABLE_NAME)
        if item.get('name')
    }
    names.update(
        item['name'].lower()
        for item in inspector.get_indexes(TABLE_NAME)
        if item.get('name') and item.get('unique')
    )
    return CONSTRAINT_NAME.lower() in names


def upgrade():
    bind = op.get_bind()
    # Keep the earliest usage and make recovery work on PostgreSQL and SQLite.
    op.execute(sa.text('''
        DELETE FROM "PromoCodeUsage"
        WHERE id NOT IN (
            SELECT MIN(id) FROM "PromoCodeUsage" GROUP BY promocode_id, user_id
        )
    '''))
    if not _unique_constraint_exists(bind):
        op.create_unique_constraint(
            CONSTRAINT_NAME,
            TABLE_NAME,
            ['promocode_id', 'user_id'],
        )


def downgrade():
    if _unique_constraint_exists(op.get_bind()):
        op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_='unique')
