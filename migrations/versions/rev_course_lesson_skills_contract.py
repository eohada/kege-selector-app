"""reconcile course lesson skills schema contract

Revision ID: rev_course_lesson_skills_contract
Revises: rev_lesson_outcomes_metrics
Create Date: 2026-09-24 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'rev_course_lesson_skills_contract'
down_revision = 'rev_lesson_outcomes_metrics'
branch_labels = None
depends_on = None


def _resolve_table_name(table_names, expected_name):
    expected_lower = expected_name.lower()
    return next((name for name in table_names if name.lower() == expected_lower), None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    lessons_tbl = _resolve_table_name(table_names, 'Lessons') or 'Lessons'
    skills_tbl = _resolve_table_name(table_names, 'ExamSkills') or 'ExamSkills'
    courses_tbl = _resolve_table_name(table_names, 'Courses') or 'Courses'
    cm_tbl = _resolve_table_name(table_names, 'CourseModules') or 'CourseModules'

    # 1. Table lesson_skills
    lesson_skills_tbl = _resolve_table_name(table_names, 'lesson_skills')
    if not lesson_skills_tbl:
        op.create_table(
            'lesson_skills',
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey(f'{lessons_tbl}.lesson_id', ondelete='CASCADE'), primary_key=True, nullable=False),
            sa.Column('skill_id', sa.Integer(), sa.ForeignKey(f'{skills_tbl}.skill_id', ondelete='CASCADE'), primary_key=True, nullable=False),
            sa.PrimaryKeyConstraint('lesson_id', 'skill_id'),
        )

    # 2. Table lesson_attachments
    lesson_attachments_tbl = _resolve_table_name(table_names, 'lesson_attachments')
    if not lesson_attachments_tbl:
        op.create_table(
            'lesson_attachments',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey(f'{lessons_tbl}.lesson_id', ondelete='CASCADE'), nullable=False),
            sa.Column('file_name', sa.String(length=255), nullable=False),
            sa.Column('file_path', sa.String(length=500), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('target', sa.String(length=20), server_default='theory', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_lesson_attachments_lesson_id', 'lesson_attachments', ['lesson_id'], unique=False)
    else:
        existing_indexes = {idx['name'].lower() for idx in inspector.get_indexes(lesson_attachments_tbl)}
        if 'ix_lesson_attachments_lesson_id' not in existing_indexes:
            op.create_index('ix_lesson_attachments_lesson_id', lesson_attachments_tbl, ['lesson_id'], unique=False)

    # 3. CourseModules columns
    if cm_tbl:
        cm_cols = {c['name'].lower() for c in inspector.get_columns(cm_tbl)}
        if 'is_control_exam' not in cm_cols:
            with op.batch_alter_table(cm_tbl) as batch_op:
                batch_op.add_column(sa.Column('is_control_exam', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    # 4. Courses columns and indexes
    if courses_tbl:
        c_cols = {c['name'].lower() for c in inspector.get_columns(courses_tbl)}
        with op.batch_alter_table(courses_tbl) as batch_op:
            if 'is_template' not in c_cols:
                batch_op.add_column(sa.Column('is_template', sa.Boolean(), server_default=sa.text('false'), nullable=False))
            if 'parent_course_id' not in c_cols:
                batch_op.add_column(sa.Column('parent_course_id', sa.Integer(), sa.ForeignKey(f'{courses_tbl}.course_id', name='fk_courses_parent_course_id'), nullable=True))

        inspector = sa.inspect(bind)
        c_indexes = {idx['name'].lower() for idx in inspector.get_indexes(courses_tbl)}
        if 'ix_courses_is_template' not in c_indexes:
            op.create_index('ix_Courses_is_template', courses_tbl, ['is_template'], unique=False)
        if 'ix_courses_parent_course_id' not in c_indexes:
            op.create_index('ix_Courses_parent_course_id', courses_tbl, ['parent_course_id'], unique=False)

    # 5. ExamSkills columns and indexes
    if skills_tbl:
        es_cols = {c['name'].lower() for c in inspector.get_columns(skills_tbl)}
        with op.batch_alter_table(skills_tbl) as batch_op:
            if 'topic_code' not in es_cols:
                batch_op.add_column(sa.Column('topic_code', sa.String(length=100), nullable=True))
            if 'prerequisite_ids' not in es_cols:
                batch_op.add_column(sa.Column('prerequisite_ids', sa.JSON(), nullable=True))

        inspector = sa.inspect(bind)
        es_indexes = {idx['name'].lower() for idx in inspector.get_indexes(skills_tbl)}
        if 'ix_examskills_topic_code' not in es_indexes:
            op.create_index('ix_ExamSkills_topic_code', skills_tbl, ['topic_code'], unique=False)

    # 6. Lessons columns and indexes
    if lessons_tbl:
        l_cols = {c['name'].lower() for c in inspector.get_columns(lessons_tbl)}
        with op.batch_alter_table(lessons_tbl) as batch_op:
            if 'lesson_format' not in l_cols:
                batch_op.add_column(sa.Column('lesson_format', sa.String(length=60), nullable=True))
            if 'studio_scenario' not in l_cols:
                batch_op.add_column(sa.Column('studio_scenario', sa.Text(), nullable=True))

        inspector = sa.inspect(bind)
        l_indexes = {idx['name'].lower() for idx in inspector.get_indexes(lessons_tbl)}
        if 'ix_lessons_student_id' not in l_indexes:
            op.create_index('ix_Lessons_student_id', lessons_tbl, ['student_id'], unique=False)


def downgrade():
    pass
