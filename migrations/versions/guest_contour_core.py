"""guest contour core entities

Revision ID: guest_contour_core
Revises: ff4a5b6c7d8e
"""
from alembic import op
import sqlalchemy as sa

revision = 'guest_contour_core'
down_revision = 'ff4a5b6c7d8e'
branch_labels = None
depends_on = None


def _json_type(bind):
    return sa.JSON()


def upgrade():
    # Local WSGI creates model tables eagerly for SQLite before Alembic runs.
    # If the complete guest schema is already present, only advance the
    # revision; production databases still execute the full expand migration.
    inspector = sa.inspect(op.get_bind())
    if 'GuestSessions' in inspector.get_table_names() and all(
        table in inspector.get_table_names()
        for table in ('GuestParticipants', 'GuestTasks', 'GuestResponses', 'GuestAttachments', 'GuestDrawings', 'GuestActivities', 'GuestReviews')
    ):
        return
    op.create_table(
        'GuestSessions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('Users.id'), nullable=False),
        sa.Column('session_type', sa.String(24), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('access_code', sa.String(16), nullable=False),
        sa.Column('access_token_hash', sa.String(64), nullable=False),
        sa.Column('template_key', sa.String(80), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('max_participants', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('settings', _json_type(None), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('access_code', name='uq_guest_session_access_code'),
        sa.UniqueConstraint('access_token_hash', name='uq_guest_session_access_token_hash'),
    )
    op.create_index('ix_guest_session_teacher', 'GuestSessions', ['teacher_id'])
    op.create_index('ix_guest_session_type', 'GuestSessions', ['session_type'])
    op.create_index('ix_guest_session_status', 'GuestSessions', ['status'])
    op.create_index('ix_guest_session_expires', 'GuestSessions', ['expires_at'])

    op.create_table(
        'GuestParticipants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('GuestSessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('display_name', sa.String(160), nullable=False),
        sa.Column('guest_token_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('converted_student_id', sa.Integer(), sa.ForeignKey('Students.student_id'), nullable=True),
        sa.Column('onboarding_state', _json_type(None), nullable=False, server_default='{}'),
        sa.UniqueConstraint('guest_token_hash', name='uq_guest_participant_token_hash'),
    )
    op.create_index('ix_guest_participant_session', 'GuestParticipants', ['session_id'])
    op.create_index('ix_guest_participant_status', 'GuestParticipants', ['status'])

    op.create_table(
        'GuestTasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('GuestSessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_task_id', sa.Integer(), sa.ForeignKey('Tasks.task_id'), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('task_type', sa.String(24), nullable=False, server_default='short_text'),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('options', _json_type(None), nullable=False, server_default='[]'),
        sa.Column('expected_answer', sa.Text(), nullable=True),
        sa.Column('skill_key', sa.String(120), nullable=True),
        sa.Column('max_score', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('metadata_json', _json_type(None), nullable=False, server_default='{}'),
    )
    op.create_index('ix_guest_task_session', 'GuestTasks', ['session_id'])
    op.create_index('ix_guest_task_source', 'GuestTasks', ['source_task_id'])

    op.create_table(
        'GuestResponses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('participant_id', sa.Integer(), sa.ForeignKey('GuestParticipants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('GuestTasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('answer_text', sa.Text(), nullable=True),
        sa.Column('answer_json', _json_type(None), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('flagged', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('teacher_comment', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('auto_checked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('participant_id', 'task_id', name='uq_guest_response_participant_task'),
    )
    op.create_index('ix_guest_response_participant', 'GuestResponses', ['participant_id'])
    op.create_index('ix_guest_response_task', 'GuestResponses', ['task_id'])

    op.create_table(
        'GuestAttachments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('response_id', sa.Integer(), sa.ForeignKey('GuestResponses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('mime_type', sa.String(120), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('storage_key', name='uq_guest_attachment_storage_key'),
    )
    op.create_index('ix_guest_attachment_response', 'GuestAttachments', ['response_id'])

    op.create_table(
        'GuestDrawings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('response_id', sa.Integer(), sa.ForeignKey('GuestResponses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('payload', _json_type(None), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_guest_drawing_response', 'GuestDrawings', ['response_id'])

    op.create_table(
        'GuestActivities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('GuestSessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('participant_id', sa.Integer(), sa.ForeignKey('GuestParticipants.id', ondelete='CASCADE'), nullable=True),
        sa.Column('event', sa.String(80), nullable=False),
        sa.Column('payload', _json_type(None), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_guest_activity_session', 'GuestActivities', ['session_id'])
    op.create_index('ix_guest_activity_participant', 'GuestActivities', ['participant_id'])

    op.create_table(
        'GuestReviews',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('GuestSessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('participant_id', sa.Integer(), sa.ForeignKey('GuestParticipants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('total_score', sa.Integer(), nullable=True),
        sa.Column('max_score', sa.Integer(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('teacher_comment', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('participant_id', name='uq_guest_review_participant'),
    )
    op.create_index('ix_guest_review_session', 'GuestReviews', ['session_id'])


def downgrade():
    for table in ('GuestReviews', 'GuestActivities', 'GuestDrawings', 'GuestAttachments', 'GuestResponses', 'GuestTasks', 'GuestParticipants', 'GuestSessions'):
        op.drop_table(table)
