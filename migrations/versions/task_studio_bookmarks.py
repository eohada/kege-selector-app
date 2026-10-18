"""Add TaskBookmarks table for teacher task studio.

Revision ID: task_studio_bookmarks
Revises: ai_lab_quality_v05
"""
from alembic import op
import sqlalchemy as sa


revision = 'task_studio_bookmarks'
down_revision = 'ai_lab_quality_v05'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'TaskBookmarks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('Tasks.task_id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('user_id', 'task_id', name='uq_user_task_bookmark'),
    )
    op.create_index('ix_TaskBookmarks_user_id', 'TaskBookmarks', ['user_id'])
    op.create_index('ix_TaskBookmarks_task_id', 'TaskBookmarks', ['task_id'])


def downgrade():
    op.drop_index('ix_TaskBookmarks_task_id', table_name='TaskBookmarks')
    op.drop_index('ix_TaskBookmarks_user_id', table_name='TaskBookmarks')
    op.drop_table('TaskBookmarks')
