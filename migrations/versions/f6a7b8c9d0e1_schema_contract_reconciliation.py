"""Reconcile schema gaps present before Alembic became the source of truth.

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-08-10 01:35:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


REQUIRED_COLUMNS = (
    ('BotErrorReports', 'screenshot_file_id', sa.String(length=200)),
    ('BotErrorReports', 'creator_tg_message_id', sa.BigInteger()),
    ('MaterialAssets', 'course_id', sa.Integer()),
    ('MaterialAssets', 'tag', sa.String(length=100)),
    ('MaterialAssets', 'telegram_chat_link', sa.String(length=255)),
    ('RecurringLessonSlots', 'course_id', sa.Integer()),
    ('RecurringLessonSlots', 'tag', sa.String(length=100)),
    ('RecurringLessonSlots', 'telegram_chat_link', sa.String(length=255)),
    ('RubricTemplates', 'course_id', sa.Integer()),
    ('RubricTemplates', 'tag', sa.String(length=100)),
    ('RubricTemplates', 'telegram_chat_link', sa.String(length=255)),
    ('SchoolGroups', 'course_id', sa.Integer()),
    ('SchoolGroups', 'tag', sa.String(length=100)),
    ('SchoolGroups', 'telegram_chat_link', sa.String(length=255)),
    ('Tasks', 'max_score', sa.Integer()),
)

REQUIRED_INDEXES = (
    ('Assignments', 'ix_Assignments_exam_course_id', ('exam_course_id',), False),
    ('AuditLog', 'ix_AuditLog_user_id', ('user_id',), False),
    ('InviteLinks', 'ix_InviteLinks_teacher_id', ('teacher_id',), False),
    ('InviteLinks', 'ix_InviteLinks_revoked_at', ('revoked_at',), False),
    ('LessonTasks', 'ix_LessonTasks_difficulty_level', ('difficulty_level',), False),
    ('LessonWhiteboards', 'ix_LessonWhiteboards_lesson_id', ('lesson_id',), True),
    ('LessonWhiteboards', 'ix_LessonWhiteboards_miro_board_id', ('miro_board_id',), False),
    ('Lessons', 'ix_Lessons_course_module_id', ('course_module_id',), False),
    ('Lessons', 'ix_Lessons_exam_course_id', ('exam_course_id',), False),
    ('MaterialAssets', 'ix_MaterialAssets_course_id', ('course_id',), False),
    ('QAReports', 'ix_QAReports_cycle_id', ('cycle_id',), False),
    ('RecurringLessonSlots', 'ix_RecurringLessonSlots_course_id', ('course_id',), False),
    ('RubricTemplates', 'ix_RubricTemplates_course_id', ('course_id',), False),
    ('SchoolGroups', 'ix_SchoolGroups_course_id', ('course_id',), False),
    ('StudentLearningPlanItems', 'ix_StudentLearningPlanItems_parent_id', ('parent_id',), False),
    ('StudentTaskStatistics', 'ix_StudentTaskStatistics_course_id', ('course_id',), False),
    ('Students', 'ix_Students_user_id', ('user_id',), True),
    ('Tasks', 'ix_Tasks_source_prototype', ('source_prototype',), False),
    ('Tasks', 'ix_Tasks_bank_origin', ('bank_origin',), False),
    ('Tasks', 'ix_Tasks_kege_source_tag', ('kege_source_tag',), False),
    ('Tasks', 'ix_Tasks_difficulty_level', ('difficulty_level',), False),
    ('Tasks', 'ix_Tasks_knowledge_node_id', ('knowledge_node_id',), False),
    ('Tasks', 'ix_Tasks_course_id', ('course_id',), False),
    ('Tasks', 'ix_Tasks_task_group_id', ('task_group_id',), False),
    ('Tasks', 'ix_Tasks_kege_difficulty_tier', ('kege_difficulty_tier',), False),
    ('TheoryBlocks', 'ix_TheoryBlocks_position', ('position',), False),
    ('TheoryBlocks', 'ix_TheoryBlocks_group_id', ('group_id',), False),
    ('UserNotifications', 'ix_UserNotifications_telegram_sent', ('telegram_sent',), False),
    ('UserProfiles', 'ix_UserProfiles_telegram_chat_id', ('telegram_chat_id',), True),
    ('Users', 'ix_Users_telegram_id', ('telegram_id',), True),
    ('Users', 'ix_Users_presence_last_seen_at', ('presence_last_seen_at',), False),
    ('Users', 'ix_Users_presence_activity_key', ('presence_activity_key',), False),
    ('Users', 'ix_Users_is_demo_user', ('is_demo_user',), False),
    ('Users', 'ix_Users_parent_link_code', ('parent_link_code',), True),
    ('Users', 'ix_Users_numeric_id', ('numeric_id',), False),
    ('Users', 'ix_Users_is_qa_pool', ('is_qa_pool',), False),
)


def _resolve_table_name(table_names, expected_name):
    return next((name for name in table_names if name.lower() == expected_name.lower()), None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    for expected_table, column_name, column_type in REQUIRED_COLUMNS:
        table_name = _resolve_table_name(table_names, expected_table)
        if not table_name:
            continue
        existing_columns = {column['name'].lower() for column in inspector.get_columns(table_name)}
        if column_name.lower() not in existing_columns:
            op.add_column(table_name, sa.Column(column_name, column_type, nullable=True))

    inspector = sa.inspect(bind)
    for expected_table, index_name, columns, unique in REQUIRED_INDEXES:
        table_name = _resolve_table_name(set(inspector.get_table_names()), expected_table)
        if not table_name:
            continue
        existing_indexes = {index['name'] for index in inspector.get_indexes(table_name)}
        if index_name not in existing_indexes:
            unique_sql = 'UNIQUE ' if unique else ''
            quoted_columns = ', '.join(f'"{column}"' for column in columns)
            op.execute(
                sa.text(
                    f'CREATE {unique_sql}INDEX IF NOT EXISTS "{index_name}" '
                    f'ON "{table_name}" ({quoted_columns})'
                )
            )


def downgrade():
    pass
