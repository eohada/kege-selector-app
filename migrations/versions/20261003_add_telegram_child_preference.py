"""add parent Telegram selected-child preference

Revision ID: add_telegram_child_preference
Revises: add_telegram_deliveries
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_telegram_child_preference'
down_revision = 'add_telegram_deliveries'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('UserProfiles', sa.Column('telegram_selected_child_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_user_profiles_telegram_selected_child', 'UserProfiles', 'Students',
        ['telegram_selected_child_id'], ['student_id'], ondelete='SET NULL',
    )
    op.create_index('ix_UserProfiles_telegram_selected_child_id', 'UserProfiles', ['telegram_selected_child_id'])


def downgrade():
    op.drop_index('ix_UserProfiles_telegram_selected_child_id', table_name='UserProfiles')
    op.drop_constraint('fk_user_profiles_telegram_selected_child', 'UserProfiles', type_='foreignkey')
    op.drop_column('UserProfiles', 'telegram_selected_child_id')
