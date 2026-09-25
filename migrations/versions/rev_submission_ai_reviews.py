"""create submission ai reviews table and indexes

Revision ID: rev_submission_ai_reviews
Revises: rev_course_lesson_skills
Create Date: 2026-09-25 20:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'rev_submission_ai_reviews'
down_revision = 'rev_course_lesson_skills'
branch_labels = None
depends_on = None


def _resolve_table_name(table_names, expected_name):
    expected_lower = expected_name.lower()
    return next((name for name in table_names if name.lower() == expected_lower), None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    submissions_tbl = _resolve_table_name(table_names, 'Submissions') or 'Submissions'
    users_tbl = _resolve_table_name(table_names, 'Users') or 'Users'

    ai_reviews_tbl = _resolve_table_name(table_names, 'SubmissionAiReviews')
    if not ai_reviews_tbl:
        op.create_table(
            'SubmissionAiReviews',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('submission_id', sa.Integer(), sa.ForeignKey(f'{submissions_tbl}.submission_id', ondelete='CASCADE'), nullable=False),
            sa.Column('attempt_no', sa.Integer(), server_default='1', nullable=False),
            sa.Column('revision_no', sa.Integer(), server_default='1', nullable=False),
            sa.Column('submission_hash', sa.String(length=64), nullable=False),
            sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
            sa.Column('provider', sa.String(length=32), nullable=True),
            sa.Column('model', sa.String(length=100), nullable=True),
            sa.Column('suggested_total_points', sa.Float(), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('teacher_review_required', sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column('summary_for_teacher', sa.Text(), nullable=True),
            sa.Column('skill_signals', sa.JSON(), nullable=True),
            sa.Column('task_reviews', sa.JSON(), nullable=True),
            sa.Column('raw_response', sa.JSON(), nullable=True),
            sa.Column('error_code', sa.String(length=64), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('accepted_by_user_id', sa.Integer(), sa.ForeignKey(f'{users_tbl}.id'), nullable=True),
            sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        ai_reviews_tbl = 'SubmissionAiReviews'
    else:
        # Check and add missing columns if table already exists in legacy state
        existing_cols = {c['name'].lower() for c in inspector.get_columns(ai_reviews_tbl)}
        with op.batch_alter_table(ai_reviews_tbl) as batch_op:
            if 'submission_id' not in existing_cols:
                batch_op.add_column(sa.Column('submission_id', sa.Integer(), sa.ForeignKey(f'{submissions_tbl}.submission_id', ondelete='CASCADE'), nullable=False))
            if 'attempt_no' not in existing_cols:
                batch_op.add_column(sa.Column('attempt_no', sa.Integer(), server_default='1', nullable=False))
            if 'revision_no' not in existing_cols:
                batch_op.add_column(sa.Column('revision_no', sa.Integer(), server_default='1', nullable=False))
            if 'submission_hash' not in existing_cols:
                batch_op.add_column(sa.Column('submission_hash', sa.String(length=64), nullable=False))
            if 'status' not in existing_cols:
                batch_op.add_column(sa.Column('status', sa.String(length=32), server_default='pending', nullable=False))
            if 'provider' not in existing_cols:
                batch_op.add_column(sa.Column('provider', sa.String(length=32), nullable=True))
            if 'model' not in existing_cols:
                batch_op.add_column(sa.Column('model', sa.String(length=100), nullable=True))
            if 'suggested_total_points' not in existing_cols:
                batch_op.add_column(sa.Column('suggested_total_points', sa.Float(), nullable=True))
            if 'confidence' not in existing_cols:
                batch_op.add_column(sa.Column('confidence', sa.Float(), nullable=True))
            if 'teacher_review_required' not in existing_cols:
                batch_op.add_column(sa.Column('teacher_review_required', sa.Boolean(), server_default=sa.text('true'), nullable=False))
            if 'summary_for_teacher' not in existing_cols:
                batch_op.add_column(sa.Column('summary_for_teacher', sa.Text(), nullable=True))
            if 'skill_signals' not in existing_cols:
                batch_op.add_column(sa.Column('skill_signals', sa.JSON(), nullable=True))
            if 'task_reviews' not in existing_cols:
                batch_op.add_column(sa.Column('task_reviews', sa.JSON(), nullable=True))
            if 'raw_response' not in existing_cols:
                batch_op.add_column(sa.Column('raw_response', sa.JSON(), nullable=True))
            if 'error_code' not in existing_cols:
                batch_op.add_column(sa.Column('error_code', sa.String(length=64), nullable=True))
            if 'error_message' not in existing_cols:
                batch_op.add_column(sa.Column('error_message', sa.Text(), nullable=True))
            if 'accepted_by_user_id' not in existing_cols:
                batch_op.add_column(sa.Column('accepted_by_user_id', sa.Integer(), sa.ForeignKey(f'{users_tbl}.id'), nullable=True))
            if 'accepted_at' not in existing_cols:
                batch_op.add_column(sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True))
            if 'created_at' not in existing_cols:
                batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
            if 'updated_at' not in existing_cols:
                batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))

    # Ensure all required indexes exist
    inspector = sa.inspect(bind)
    existing_indexes = {
        idx['name'].lower()
        for idx in inspector.get_indexes(ai_reviews_tbl)
        if idx.get('name')
    }

    indexes_to_create = [
        ('ix_SubmissionAiReviews_submission_id', ['submission_id'], False),
        ('ix_SubmissionAiReviews_attempt_no', ['attempt_no'], False),
        ('ix_SubmissionAiReviews_submission_hash', ['submission_hash'], False),
        ('ix_SubmissionAiReviews_status', ['status'], False),
        ('ix_submission_ai_review_lookup', ['submission_id', 'revision_no'], True),
        ('ix_submission_ai_review_hash', ['submission_id', 'submission_hash'], False),
    ]

    for idx_name, cols, unique in indexes_to_create:
        if idx_name.lower() not in existing_indexes:
            op.create_index(idx_name, ai_reviews_tbl, cols, unique=unique)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    tbl = _resolve_table_name(table_names, 'SubmissionAiReviews')
    if tbl:
        op.drop_table(tbl)
