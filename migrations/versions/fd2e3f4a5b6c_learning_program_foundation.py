"""Add skills, mastery, learning items, course versions and lesson outcomes.

Revision ID: fd2e3f4a5b6c
Revises: fc1d2e3f4a5b
"""
from alembic import op
import sqlalchemy as sa

revision = 'fd2e3f4a5b6c'
down_revision = 'fc1d2e3f4a5b'
branch_labels = None
depends_on = None


def _tables(bind):
    return {name.lower(): name for name in sa.inspect(bind).get_table_names()}


def _add_columns(bind, table, columns):
    names = {c['name'].lower() for c in sa.inspect(bind).get_columns(table)}
    with op.batch_alter_table(table) as batch:
        for name, column in columns:
            if name.lower() not in names:
                batch.add_column(column)


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)
    if 'courses' in tables:
        _add_columns(bind, tables['courses'], [
            ('exam_course_id', sa.Column('exam_course_id', sa.Integer(), nullable=True)),
            ('target_score', sa.Column('target_score', sa.Integer(), nullable=True)),
            ('exam_date', sa.Column('exam_date', sa.Date(), nullable=True)),
            ('current_forecast', sa.Column('current_forecast', sa.Integer(), nullable=True)),
            ('forecast_low', sa.Column('forecast_low', sa.Integer(), nullable=True)),
            ('forecast_high', sa.Column('forecast_high', sa.Integer(), nullable=True)),
            ('current_version', sa.Column('current_version', sa.Integer(), nullable=False, server_default='1')),
        ])

    if 'examskills' not in tables:
        op.create_table(
            'ExamSkills',
            sa.Column('skill_id', sa.Integer(), primary_key=True),
            sa.Column('exam_course_id', sa.Integer(), sa.ForeignKey('ExamCourses.id'), nullable=True),
            sa.Column('task_number', sa.Integer(), nullable=True),
            sa.Column('title', sa.String(300), nullable=False),
            sa.Column('subject', sa.String(120), nullable=True),
            sa.Column('topic', sa.String(200), nullable=True),
            sa.Column('subtopic', sa.String(200), nullable=True),
            sa.Column('difficulty', sa.Integer(), nullable=True),
            sa.Column('weight', sa.Float(), nullable=False, server_default='1.0'),
            sa.Column('theory_ref', sa.String(300), nullable=True),
            sa.Column('mastery_criteria', sa.JSON(), nullable=True),
            sa.Column('prerequisite_skill_id', sa.Integer(), sa.ForeignKey('ExamSkills.skill_id'), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_ExamSkills_exam_course_id', 'ExamSkills', ['exam_course_id'])
        op.create_index('ix_ExamSkills_task_number', 'ExamSkills', ['task_number'])
        op.create_index('ix_ExamSkills_topic', 'ExamSkills', ['topic'])

    if 'studentskills' not in tables:
        op.create_table(
            'StudentSkills',
            sa.Column('student_skill_id', sa.Integer(), primary_key=True),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('Students.student_id'), nullable=False),
            sa.Column('skill_id', sa.Integer(), sa.ForeignKey('ExamSkills.skill_id'), nullable=False),
            sa.Column('mastery_percent', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('state', sa.String(30), nullable=False, server_default='not_started'),
            sa.Column('theory_done', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('practice_done', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('homework_total', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('homework_done', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_checked_at', sa.DateTime(), nullable=True),
            sa.Column('next_review_at', sa.DateTime(), nullable=True),
            sa.Column('source', sa.String(40), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('student_id', 'skill_id', name='uq_student_skill'),
        )
        op.create_index('ix_StudentSkills_student_id', 'StudentSkills', ['student_id'])
        op.create_index('ix_StudentSkills_skill_id', 'StudentSkills', ['skill_id'])
        op.create_index('ix_StudentSkills_state', 'StudentSkills', ['state'])

    if 'learningerrors' not in tables:
        op.create_table(
            'LearningErrors',
            sa.Column('error_id', sa.Integer(), primary_key=True),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('Students.student_id'), nullable=False),
            sa.Column('skill_id', sa.Integer(), sa.ForeignKey('ExamSkills.skill_id'), nullable=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('Lessons.lesson_id'), nullable=True),
            sa.Column('task_id', sa.Integer(), sa.ForeignKey('Tasks.task_id'), nullable=True),
            sa.Column('error_type', sa.String(120), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('occurrences', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('next_review_at', sa.DateTime(timezone=True), nullable=True),
        )
        for name in ('student_id', 'skill_id', 'lesson_id', 'task_id', 'next_review_at'):
            op.create_index(f'ix_LearningErrors_{name}', 'LearningErrors', [name])

    if 'learningitems' not in tables:
        op.create_table(
            'LearningItems',
            sa.Column('item_id', sa.Integer(), primary_key=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('Courses.course_id'), nullable=False),
            sa.Column('module_id', sa.Integer(), sa.ForeignKey('CourseModules.module_id'), nullable=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('Lessons.lesson_id'), nullable=True),
            sa.Column('skill_id', sa.Integer(), sa.ForeignKey('ExamSkills.skill_id'), nullable=True),
            sa.Column('item_type', sa.String(30), nullable=False, server_default='lesson'),
            sa.Column('title', sa.String(300), nullable=False),
            sa.Column('status', sa.String(30), nullable=False, server_default='planned'),
            sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('why_now', sa.Text(), nullable=True),
            sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        for name, column in [('course_id', 'course_id'), ('module_id', 'module_id'), ('lesson_id', 'lesson_id'), ('skill_id', 'skill_id'), ('item_type', 'item_type'), ('status', 'status')]:
            op.create_index(f'ix_LearningItems_{name}', 'LearningItems', [column])

    if 'courseversions' not in tables:
        op.create_table(
            'CourseVersions',
            sa.Column('version_id', sa.Integer(), primary_key=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('Courses.course_id'), nullable=False),
            sa.Column('version_number', sa.Integer(), nullable=False),
            sa.Column('reason', sa.String(300), nullable=True),
            sa.Column('snapshot', sa.JSON(), nullable=False),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint('course_id', 'version_number', name='uq_course_version'),
        )
        op.create_index('ix_CourseVersions_course_id', 'CourseVersions', ['course_id'])

    if 'lessonoutcomes' not in tables:
        op.create_table(
            'LessonOutcomes',
            sa.Column('outcome_id', sa.Integer(), primary_key=True),
            sa.Column('lesson_id', sa.Integer(), sa.ForeignKey('Lessons.lesson_id'), nullable=False, unique=True),
            sa.Column('covered', sa.JSON(), nullable=True),
            sa.Column('mastery', sa.String(20), nullable=True),
            sa.Column('next_action', sa.String(30), nullable=True),
            sa.Column('homework_assigned', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('teacher_note', sa.Text(), nullable=True),
            sa.Column('content_snapshot', sa.JSON(), nullable=True),
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_LessonOutcomes_lesson_id', 'LessonOutcomes', ['lesson_id'])
    elif 'lessonoutcomes' in tables:
        _add_columns(bind, tables['lessonoutcomes'], [
            ('content_snapshot', sa.Column('content_snapshot', sa.JSON(), nullable=True)),
        ])

    if 'coursetemplates' not in tables:
        op.create_table(
            'CourseTemplates',
            sa.Column('template_id', sa.Integer(), primary_key=True),
            sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=True),
            sa.Column('exam_course_id', sa.Integer(), sa.ForeignKey('ExamCourses.id'), nullable=True),
            sa.Column('title', sa.String(240), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('target_score', sa.Integer(), nullable=True),
            sa.Column('estimated_lessons', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_CourseTemplates_owner_user_id', 'CourseTemplates', ['owner_user_id'])
        op.create_index('ix_CourseTemplates_exam_course_id', 'CourseTemplates', ['exam_course_id'])
        op.create_index('ix_CourseTemplates_is_active', 'CourseTemplates', ['is_active'])

    if 'coursetemplatemodules' not in tables:
        op.create_table(
            'CourseTemplateModules',
            sa.Column('template_module_id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('CourseTemplates.template_id'), nullable=False),
            sa.Column('title', sa.String(240), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        )
        op.create_index('ix_CourseTemplateModules_template_id', 'CourseTemplateModules', ['template_id'])

    if 'coursetemplateitems' not in tables:
        op.create_table(
            'CourseTemplateItems',
            sa.Column('template_item_id', sa.Integer(), primary_key=True),
            sa.Column('template_module_id', sa.Integer(), sa.ForeignKey('CourseTemplateModules.template_module_id'), nullable=False),
            sa.Column('skill_id', sa.Integer(), sa.ForeignKey('ExamSkills.skill_id'), nullable=True),
            sa.Column('item_type', sa.String(30), nullable=False, server_default='practice'),
            sa.Column('title', sa.String(300), nullable=False),
            sa.Column('duration_minutes', sa.Integer(), nullable=True),
            sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('metadata_json', sa.JSON(), nullable=True),
        )
        op.create_index('ix_CourseTemplateItems_template_module_id', 'CourseTemplateItems', ['template_module_id'])
        op.create_index('ix_CourseTemplateItems_skill_id', 'CourseTemplateItems', ['skill_id'])


def downgrade():
    pass
