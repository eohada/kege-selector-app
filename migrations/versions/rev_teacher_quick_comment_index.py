"""add missing teacher quick comments index

Revision ID: rev_teacher_quick_comment_index
Revises: rev_teacher_quick_comments
Create Date: 2026-09-17 08:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'rev_teacher_quick_comment_index'
down_revision = 'rev_teacher_quick_comments'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('TeacherQuickComments'):
        return
    index_names = {index['name'] for index in inspector.get_indexes('TeacherQuickComments')}
    if 'ix_TeacherQuickComments_teacher_id' not in index_names:
        op.create_index(
            'ix_TeacherQuickComments_teacher_id',
            'TeacherQuickComments',
            ['teacher_id'],
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('TeacherQuickComments'):
        return
    index_names = {index['name'] for index in inspector.get_indexes('TeacherQuickComments')}
    if 'ix_TeacherQuickComments_teacher_id' in index_names:
        op.drop_index('ix_TeacherQuickComments_teacher_id', table_name='TeacherQuickComments')
