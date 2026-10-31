"""Alembic migration for Sprint 2.2: Multi-Teacher data foundation.

Adds teacher_id and subject columns to Lessons table with safe,
expand-only nullable definitions and composite performance index.

Revision ID: schedule_sprint2_2_teacher_and_subject
Revises: release_r0_workflow_bans_and_publication
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "schedule_sprint2_2_teacher_and_subject"
down_revision = "release_r0_workflow_bans_and_publication"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    if "lessons" in tables:
        actual_cols = {c["name"].lower() for c in inspector.get_columns("Lessons")}
        with op.batch_alter_table("Lessons", schema=None) as batch_op:
            if "teacher_id" not in actual_cols:
                batch_op.add_column(
                    sa.Column(
                        "teacher_id",
                        sa.Integer(),
                        sa.ForeignKey("Users.id", ondelete="SET NULL"),
                        nullable=True,
                    )
                )
            if "subject" not in actual_cols:
                batch_op.add_column(
                    sa.Column("subject", sa.String(length=100), nullable=True)
                )

        # Refresh index list after batch alterations
        actual_indexes = {ix["name"].lower() for ix in inspector.get_indexes("Lessons")}
        if "ix_lessons_teacher_id" not in actual_indexes:
            try:
                op.create_index("ix_Lessons_teacher_id", "Lessons", ["teacher_id"])
            except Exception:
                pass

        if "ix_lessons_subject" not in actual_indexes:
            try:
                op.create_index("ix_Lessons_subject", "Lessons", ["subject"])
            except Exception:
                pass

        if "ix_lessons_teacher_date" not in actual_indexes:
            try:
                op.create_index("ix_lessons_teacher_date", "Lessons", ["teacher_id", "lesson_date"])
            except Exception:
                pass


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    if "lessons" in tables:
        actual_indexes = {ix["name"].lower() for ix in inspector.get_indexes("Lessons")}
        if "ix_lessons_teacher_date" in actual_indexes:
            try:
                op.drop_index("ix_lessons_teacher_date", table_name="Lessons")
            except Exception:
                pass
        if "ix_lessons_subject" in actual_indexes:
            try:
                op.drop_index("ix_Lessons_subject", table_name="Lessons")
            except Exception:
                pass
        if "ix_lessons_teacher_id" in actual_indexes:
            try:
                op.drop_index("ix_Lessons_teacher_id", table_name="Lessons")
            except Exception:
                pass

        actual_cols = {c["name"].lower() for c in inspector.get_columns("Lessons")}
        with op.batch_alter_table("Lessons", schema=None) as batch_op:
            if "subject" in actual_cols:
                batch_op.drop_column("subject")
            if "teacher_id" in actual_cols:
                batch_op.drop_column("teacher_id")
