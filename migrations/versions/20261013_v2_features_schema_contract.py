"""Add v2 features schema contract (Theory final tests, whiteboards, tariffs, student streak, lesson tasks)

Revision ID: 20261013_v2_features_schema_contract
Revises: merge_demo_heads_20261005
Create Date: 2026-10-13 14:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '20261013_v2_features_schema_contract'
down_revision = 'merge_demo_heads_20261005'
branch_labels = None
depends_on = None


def _resolve_table_name(table_names, expected_name):
    return next((name for name in table_names if name.lower() == expected_name.lower()), None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    # 1. LessonWhiteboardOperations table
    target_lwo = _resolve_table_name(table_names, 'LessonWhiteboardOperations')
    if not target_lwo:
        op.create_table(
            'LessonWhiteboardOperations',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('whiteboard_id', sa.Integer(), sa.ForeignKey('LessonWhiteboards.id'), nullable=False),
            sa.Column('operation_id', sa.String(length=96), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=True),
            sa.Column('operation_type', sa.String(length=64), nullable=False),
            sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint('operation_id', name='uq_lesson_whiteboard_operation_id'),
        )
        op.create_index('ix_LessonWhiteboardOperations_whiteboard_id', 'LessonWhiteboardOperations', ['whiteboard_id'])
        op.create_index('ix_LessonWhiteboardOperations_operation_id', 'LessonWhiteboardOperations', ['operation_id'])
        op.create_index('ix_LessonWhiteboardOperations_version', 'LessonWhiteboardOperations', ['version'])
        op.create_index('ix_LessonWhiteboardOperations_user_id', 'LessonWhiteboardOperations', ['user_id'])
        op.create_index('ix_LessonWhiteboardOperations_created_at', 'LessonWhiteboardOperations', ['created_at'])

    # 2. TheoryFinalTestAttempts table
    target_tfta = _resolve_table_name(table_names, 'TheoryFinalTestAttempts')
    if not target_tfta:
        op.create_table(
            'TheoryFinalTestAttempts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('Students.student_id', ondelete='SET NULL'), nullable=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('ExamCourses.id', ondelete='CASCADE'), nullable=False),
            sa.Column('attempt_number', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('score', sa.Integer(), nullable=False),
            sa.Column('total', sa.Integer(), nullable=False, server_default='20'),
            sa.Column('passed', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('task_ids', sa.JSON(), nullable=False),
            sa.Column('answers', sa.JSON(), nullable=False),
            sa.Column('details', sa.JSON(), nullable=False),
            sa.Column('block_scores', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index('ix_TheoryFinalTestAttempts_user_id', 'TheoryFinalTestAttempts', ['user_id'])
        op.create_index('ix_TheoryFinalTestAttempts_student_id', 'TheoryFinalTestAttempts', ['student_id'])
        op.create_index('ix_TheoryFinalTestAttempts_course_id', 'TheoryFinalTestAttempts', ['course_id'])
        op.create_index('ix_TheoryFinalTestAttempts_created_at', 'TheoryFinalTestAttempts', ['created_at'])

    # Re-inspect table names and columns
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    columns_to_add = [
        # (Table, Column_name, Column_obj)
        ('Students', 'streak_weeks', sa.Column('streak_weeks', sa.Integer(), nullable=False, server_default='0')),
        ('Students', 'last_completed_week', sa.Column('last_completed_week', sa.String(length=20), nullable=True)),
        ('Students', 'streak_weeks_frozen', sa.Column('streak_weeks_frozen', sa.Boolean(), nullable=False, server_default=sa.false())),

        ('TariffPlans', 'allow_referral', sa.Column('allow_referral', sa.Boolean(), nullable=True, server_default=sa.true())),
        ('TariffPlans', 'allow_promocode', sa.Column('allow_promocode', sa.Boolean(), nullable=True, server_default=sa.true())),
        ('TariffPlans', 'exam', sa.Column('exam', sa.String(length=50), nullable=True)),
        ('TariffPlans', 'subject', sa.Column('subject', sa.String(length=50), nullable=True)),
        ('TariffPlans', 'format', sa.Column('format', sa.String(length=50), nullable=True)),
        ('TariffPlans', 'level', sa.Column('level', sa.String(length=50), nullable=True)),
        ('TariffPlans', 'badge', sa.Column('badge', sa.String(length=100), nullable=True)),
        ('TariffPlans', 'features', sa.Column('features', sa.JSON(), nullable=True)),

        ('LessonTasks', 'is_visible_to_student', sa.Column('is_visible_to_student', sa.Boolean(), nullable=False, server_default=sa.true())),
        ('LessonTasks', 'is_answer_visible_to_student', sa.Column('is_answer_visible_to_student', sa.Boolean(), nullable=False, server_default=sa.false())),

        ('LessonWhiteboards', 'provider', sa.Column('provider', sa.String(length=32), nullable=False, server_default='boostudy')),
        ('LessonWhiteboards', 'document_state', sa.Column('document_state', sa.JSON(), nullable=False, server_default='{}')),
        ('LessonWhiteboards', 'document_version', sa.Column('document_version', sa.Integer(), nullable=False, server_default='0')),
        ('LessonWhiteboards', 'last_saved_by_user_id', sa.Column('last_saved_by_user_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=True)),
    ]

    for expected_table, col_name, col_obj in columns_to_add:
        real_tbl = _resolve_table_name(table_names, expected_table)
        if not real_tbl:
            continue
        existing_cols = {c['name'].lower() for c in inspector.get_columns(real_tbl)}
        if col_name.lower() not in existing_cols:
            op.add_column(real_tbl, col_obj)

    # Re-inspect for indexes
    inspector = sa.inspect(bind)
    indexes_to_create = [
        ('TariffPlans', 'ix_TariffPlans_exam', ['exam']),
        ('TariffPlans', 'ix_TariffPlans_subject', ['subject']),
        ('TariffPlans', 'ix_TariffPlans_format', ['format']),
        ('LessonWhiteboards', 'ix_LessonWhiteboards_provider', ['provider']),
        ('LessonWhiteboards', 'ix_LessonWhiteboards_last_saved_by_user_id', ['last_saved_by_user_id']),
    ]

    for expected_table, idx_name, idx_cols in indexes_to_create:
        real_tbl = _resolve_table_name(table_names, expected_table)
        if not real_tbl:
            continue
        existing_idxs = {idx['name'].lower() for idx in inspector.get_indexes(real_tbl) if idx.get('name')}
        if idx_name.lower() not in existing_idxs:
            quoted_cols = ', '.join(f'"{col}"' for col in idx_cols)
            op.execute(sa.text(f'CREATE INDEX IF NOT EXISTS "{idx_name}" ON "{real_tbl}" ({quoted_cols})'))


def downgrade():
    pass
