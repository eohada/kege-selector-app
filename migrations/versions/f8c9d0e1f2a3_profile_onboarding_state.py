"""Persist the one-time student profile onboarding state.

Revision ID: f8c9d0e1f2a3
Revises: f7b8c9d0e1f2
"""
from alembic import op
import sqlalchemy as sa

revision = 'f8c9d0e1f2a3'
down_revision = 'f7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('UserProfiles', sa.Column('profile_onboarding_completed_at', sa.DateTime(), nullable=True))
    op.create_index('ix_UserProfiles_profile_onboarding_completed_at', 'UserProfiles', ['profile_onboarding_completed_at'], unique=False)


def downgrade():
    op.drop_index('ix_UserProfiles_profile_onboarding_completed_at', table_name='UserProfiles')
    op.drop_column('UserProfiles', 'profile_onboarding_completed_at')
