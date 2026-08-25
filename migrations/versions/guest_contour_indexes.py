"""Align guest contour indexes with SQLAlchemy model names.

Revision ID: guest_contour_indexes
Revises: guest_contour_core
"""

from alembic import op
import sqlalchemy as sa


revision = "guest_contour_indexes"
down_revision = "guest_contour_core"
branch_labels = None
depends_on = None


EXPECTED_INDEXES = {
    "GuestSessions": {
        "ix_GuestSessions_teacher_id": ["teacher_id"],
        "ix_GuestSessions_status": ["status"],
        "ix_GuestSessions_access_code": ["access_code"],
        "ix_GuestSessions_session_type": ["session_type"],
        "ix_GuestSessions_access_token_hash": ["access_token_hash"],
        "ix_GuestSessions_expires_at": ["expires_at"],
    },
    "GuestParticipants": {
        "ix_GuestParticipants_session_id": ["session_id"],
        "ix_GuestParticipants_status": ["status"],
        "ix_GuestParticipants_guest_token_hash": ["guest_token_hash"],
        "ix_GuestParticipants_converted_student_id": ["converted_student_id"],
    },
    "GuestTasks": {
        "ix_GuestTasks_session_id": ["session_id"],
        "ix_GuestTasks_source_task_id": ["source_task_id"],
    },
    "GuestResponses": {
        "ix_GuestResponses_participant_id": ["participant_id"],
        "ix_GuestResponses_task_id": ["task_id"],
    },
    "GuestAttachments": {
        "ix_GuestAttachments_response_id": ["response_id"],
    },
    "GuestDrawings": {
        "ix_GuestDrawings_response_id": ["response_id"],
    },
    "GuestActivities": {
        "ix_GuestActivities_session_id": ["session_id"],
        "ix_GuestActivities_participant_id": ["participant_id"],
        "ix_GuestActivities_event": ["event"],
        "ix_GuestActivities_created_at": ["created_at"],
    },
    "GuestReviews": {
        "ix_GuestReviews_session_id": ["session_id"],
        "ix_GuestReviews_participant_id": ["participant_id"],
    },
}


def _existing_indexes(inspector, table_name):
    return {item["name"] for item in inspector.get_indexes(table_name) if item.get("name")}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name, indexes in EXPECTED_INDEXES.items():
        if table_name not in tables:
            continue
        existing = _existing_indexes(inspector, table_name)
        for index_name, columns in indexes.items():
            if index_name not in existing:
                op.create_index(index_name, table_name, columns)
                existing.add(index_name)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name, indexes in EXPECTED_INDEXES.items():
        if table_name not in tables:
            continue
        existing = _existing_indexes(inspector, table_name)
        for index_name in indexes:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)
