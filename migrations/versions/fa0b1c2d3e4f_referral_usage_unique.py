"""Prevent a referral code from being recorded twice for one account.

Revision ID: fa0b1c2d3e4f
Revises: f9d0e1f2a3b4
"""

from alembic import op
import sqlalchemy as sa


revision = 'fa0b1c2d3e4f'
down_revision = 'f9d0e1f2a3b4'
branch_labels = None
depends_on = None


CONSTRAINT_NAME = 'uq_referral_usage_per_user'
TABLE_NAME = 'ReferralUsage'


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
        DELETE FROM "ReferralUsage"
        WHERE id NOT IN (
            SELECT MIN(id) FROM "ReferralUsage" GROUP BY referral_code_id, user_id
        )
    '''))
    if not _unique_constraint_exists(bind):
        if bind.dialect.name == 'sqlite':
            # SQLite cannot ALTER TABLE ADD CONSTRAINT directly.
            with op.batch_alter_table(TABLE_NAME) as batch:
                batch.create_unique_constraint(
                    CONSTRAINT_NAME,
                    ['referral_code_id', 'user_id'],
                )
        else:
            op.create_unique_constraint(
                CONSTRAINT_NAME,
                TABLE_NAME,
                ['referral_code_id', 'user_id'],
            )


def downgrade():
    if _unique_constraint_exists(op.get_bind()):
        op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_='unique')
