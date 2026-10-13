"""add explicit metadata for demo leads

Revision ID: demo_call_request_metadata
Revises: add_telegram_deliveries
"""
from alembic import op
import sqlalchemy as sa

revision = 'demo_call_request_metadata'
down_revision = 'add_telegram_child_preference'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('CallRequests', sa.Column('is_demo', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('CallRequests', sa.Column('consent_given_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('CallRequests', sa.Column('source', sa.String(length=50), nullable=True))
    op.create_index('ix_CallRequests_is_demo', 'CallRequests', ['is_demo'])
    op.create_index('ix_CallRequests_source', 'CallRequests', ['source'])


def downgrade():
    op.drop_index('ix_CallRequests_source', table_name='CallRequests')
    op.drop_index('ix_CallRequests_is_demo', table_name='CallRequests')
    op.drop_column('CallRequests', 'source')
    op.drop_column('CallRequests', 'consent_given_at')
    op.drop_column('CallRequests', 'is_demo')
