"""Expand individual courses into a full lesson-program builder.

Revision ID: fc1d2e3f4a5b
Revises: fb1c2d3e4f5a
"""
from alembic import op
import sqlalchemy as sa


revision = 'fc1d2e3f4a5b'
down_revision = 'fb1c2d3e4f5a'
branch_labels = None
depends_on = None


def _table_name(bind, expected):
    tables = {name.lower(): name for name in sa.inspect(bind).get_table_names()}
    return tables.get(expected.lower())


def _columns(bind, table_name):
    return {column['name'].lower(): column for column in sa.inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()

    courses = _table_name(bind, 'Courses')
    if courses:
        columns = _columns(bind, courses)
        with op.batch_alter_table(courses) as batch:
            if 'learning_goal' not in columns:
                batch.add_column(sa.Column('learning_goal', sa.Text(), nullable=True))
            if 'expected_result' not in columns:
                batch.add_column(sa.Column('expected_result', sa.Text(), nullable=True))
            if 'default_lesson_duration' not in columns:
                batch.add_column(sa.Column('default_lesson_duration', sa.Integer(), nullable=True))
        bind.execute(sa.text('UPDATE "Courses" SET default_lesson_duration = 60 WHERE default_lesson_duration IS NULL'))
        refreshed = _columns(bind, courses)
        if refreshed.get('default_lesson_duration', {}).get('nullable', True):
            with op.batch_alter_table(courses) as batch:
                batch.alter_column('default_lesson_duration', existing_type=refreshed['default_lesson_duration']['type'], nullable=False)

    modules = _table_name(bind, 'CourseModules')
    if modules and 'learning_result' not in _columns(bind, modules):
        op.add_column(modules, sa.Column('learning_result', sa.Text(), nullable=True))

    lessons = _table_name(bind, 'Lessons')
    if lessons:
        columns = _columns(bind, lessons)
        with op.batch_alter_table(lessons) as batch:
            if 'learning_trajectory_id' not in columns:
                batch.add_column(sa.Column('learning_trajectory_id', sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    'fk_Lessons_learning_trajectory_id_Courses',
                    'Courses',
                    ['learning_trajectory_id'],
                    ['course_id'],
                )
                batch.create_index('ix_Lessons_learning_trajectory_id', ['learning_trajectory_id'], unique=False)
            if 'course_order_index' not in columns:
                batch.add_column(sa.Column('course_order_index', sa.Integer(), nullable=True))
                batch.create_index('ix_Lessons_course_order_index', ['course_order_index'], unique=False)
            if columns.get('lesson_date') and not columns['lesson_date'].get('nullable', True):
                batch.alter_column('lesson_date', existing_type=columns['lesson_date']['type'], nullable=True)
        bind.execute(sa.text('UPDATE "Lessons" SET course_order_index = 0 WHERE course_order_index IS NULL'))
        refreshed = _columns(bind, lessons)
        if refreshed.get('course_order_index', {}).get('nullable', True):
            with op.batch_alter_table(lessons) as batch:
                batch.alter_column('course_order_index', existing_type=refreshed['course_order_index']['type'], nullable=False)


def downgrade():
    # Expand-only migration: preserving plans is safer than dropping user data.
    pass
