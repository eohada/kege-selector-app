"""add lesson outcomes metrics balance deducted and student study time

Revision ID: rev_lesson_outcomes_metrics
Revises: rev_teacher_quick_comment_index
Create Date: 2026-09-21 21:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'rev_lesson_outcomes_metrics'
down_revision = 'rev_teacher_quick_comment_index'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = {t.lower(): t for t in inspector.get_table_names()}

    # 1. LessonOutcomes
    lo_table = table_names.get('lessonoutcomes')
    if lo_table:
        cols = {c['name'].lower() for c in inspector.get_columns(lo_table)}
        with op.batch_alter_table(lo_table, schema=None) as batch_op:
            if 'comprehension_score' not in cols:
                batch_op.add_column(sa.Column('comprehension_score', sa.Integer(), nullable=True))
            if 'independence_level' not in cols:
                batch_op.add_column(sa.Column('independence_level', sa.String(length=30), nullable=True))
            if 'pacing' not in cols:
                batch_op.add_column(sa.Column('pacing', sa.String(length=30), nullable=True))
            if 'identified_errors' not in cols:
                batch_op.add_column(sa.Column('identified_errors', sa.JSON(), nullable=True))
            if 'auto_replan_triggered' not in cols:
                batch_op.add_column(sa.Column('auto_replan_triggered', sa.Boolean(), nullable=False, server_default=sa.text('false')))
            if 'adaptive_diff_summary' not in cols:
                batch_op.add_column(sa.Column('adaptive_diff_summary', sa.JSON(), nullable=True))

    # 2. Lessons
    lessons_table = table_names.get('lessons')
    if lessons_table:
        cols = {c['name'].lower() for c in inspector.get_columns(lessons_table)}
        with op.batch_alter_table(lessons_table, schema=None) as batch_op:
            if 'balance_deducted' not in cols:
                batch_op.add_column(sa.Column('balance_deducted', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # 3. Students
    students_table = table_names.get('students')
    if students_table:
        cols = {c['name'].lower() for c in inspector.get_columns(students_table)}
        with op.batch_alter_table(students_table, schema=None) as batch_op:
            if 'study_time_seconds' not in cols:
                batch_op.add_column(sa.Column('study_time_seconds', sa.Integer(), nullable=False, server_default=sa.text('0')))


def downgrade():
    pass
