"""Create missing performance indexes required by the course contract.

Revision ID: ff4a5b6c7d8e
Revises: fe3f4a5b6c7d
Create Date: 2026-08-24 15:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ff4a5b6c7d8e"
down_revision = "fe3f4a5b6c7d"
branch_labels = None
depends_on = None


REQUIRED_INDEXES = (
    ("Courses", "ix_Courses_exam_course_id", "exam_course_id"),
    ("ExamSkills", "ix_ExamSkills_prerequisite_skill_id", "prerequisite_skill_id"),
    ("ExamSkills", "ix_ExamSkills_is_active", "is_active"),
    ("ExamSkills", "ix_ExamSkills_subject", "subject"),
    ("LearningItems", "ix_LearningItems_due_at", "due_at"),
    ("StudentSkills", "ix_StudentSkills_next_review_at", "next_review_at"),
    ("StudentSkills", "ix_StudentSkills_last_checked_at", "last_checked_at"),
)


def _resolve_table_name(inspector, expected_name):
    return next(
        (name for name in inspector.get_table_names() if name.lower() == expected_name.lower()),
        None,
    )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for expected_table, index_name, column_name in REQUIRED_INDEXES:
        table_name = _resolve_table_name(inspector, expected_table)
        if not table_name:
            continue

        columns = {column["name"].lower() for column in inspector.get_columns(table_name)}
        if column_name.lower() not in columns:
            continue

        existing_indexes = {index["name"].lower() for index in inspector.get_indexes(table_name)}
        if index_name.lower() not in existing_indexes:
            op.create_index(index_name, table_name, [column_name])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for expected_table, index_name, _column_name in REQUIRED_INDEXES:
        table_name = _resolve_table_name(inspector, expected_table)
        if not table_name:
            continue
        existing_indexes = {index["name"].lower() for index in inspector.get_indexes(table_name)}
        if index_name.lower() in existing_indexes:
            op.drop_index(index_name, table_name=table_name)
