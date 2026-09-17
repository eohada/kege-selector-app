"""add teacher quick comments

Revision ID: rev_teacher_quick_comments
Revises: rev_teacher_review_state
Create Date: 2026-09-15 14:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'rev_teacher_quick_comments'
down_revision = 'rev_teacher_review_state'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table('TeacherQuickComments'):
        return
    op.create_table(
        'TeacherQuickComments',
        sa.Column('quick_comment_id', sa.Integer(), primary_key=True),
        sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('text', sa.String(length=1000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('teacher_id', 'text', name='uq_teacher_quick_comment_text'),
    )
    op.create_index('ix_teacher_quick_comments_teacher_id', 'TeacherQuickComments', ['teacher_id'])


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table('TeacherQuickComments'):
        op.drop_table('TeacherQuickComments')
