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
    """Add onboarding state after the schema-contract bootstrap safely.

    The preceding bootstrap migration can reconcile a legacy installation
    against the current mapped metadata.  In that case this column and its
    index may already exist by the time this historical revision is reached.
    Alembic migrations must remain safe in both paths.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = next(
        (name for name in inspector.get_table_names() if name.lower() == 'userprofiles'),
        'UserProfiles',
    )
    columns = {column['name'].lower() for column in inspector.get_columns(table_name)}
    if 'profile_onboarding_completed_at' not in columns:
        op.add_column(table_name, sa.Column('profile_onboarding_completed_at', sa.DateTime(), nullable=True))

    inspector = sa.inspect(bind)
    indexes = {
        index['name'].lower()
        for index in inspector.get_indexes(table_name)
        if index.get('name')
    }
    index_name = 'ix_UserProfiles_profile_onboarding_completed_at'
    if index_name.lower() not in indexes:
        op.create_index(index_name, table_name, ['profile_onboarding_completed_at'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = next(
        (name for name in inspector.get_table_names() if name.lower() == 'userprofiles'),
        'UserProfiles',
    )
    indexes = {
        index['name'].lower()
        for index in inspector.get_indexes(table_name)
        if index.get('name')
    }
    index_name = 'ix_UserProfiles_profile_onboarding_completed_at'
    if index_name.lower() in indexes:
        op.drop_index(index_name, table_name=table_name)

    columns = {column['name'].lower() for column in sa.inspect(bind).get_columns(table_name)}
    if 'profile_onboarding_completed_at' in columns:
        op.drop_column(table_name, 'profile_onboarding_completed_at')
