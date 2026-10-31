"""Alembic migration for Sprint 2.4: Recurring Lessons, Teacher Availability & Schedule Exceptions.

Adds recurring columns to Lessons and RecurringLessonSlots, and creates
RecurringSlotExceptions, TeacherWeeklyAvailabilities, and TeacherScheduleExceptions tables.

Revision ID: schedule_sprint2_4_recurring_and_availability
Revises: schedule_sprint2_2_teacher_and_subject
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = "schedule_sprint2_4_recurring_and_availability"
down_revision = "schedule_sprint2_2_teacher_and_subject"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    # 1. Update Lessons table
    if "lessons" in tables:
        actual_cols = {c["name"].lower() for c in inspector.get_columns("Lessons")}
        with op.batch_alter_table("Lessons", schema=None) as batch_op:
            if "recurring_slot_id" not in actual_cols:
                batch_op.add_column(
                    sa.Column(
                        "recurring_slot_id",
                        sa.Integer(),
                        sa.ForeignKey("RecurringLessonSlots.slot_id", ondelete="SET NULL"),
                        nullable=True,
                    )
                )
            if "recurrence_key" not in actual_cols:
                batch_op.add_column(
                    sa.Column("recurrence_key", sa.String(length=64), nullable=True)
                )
            if "is_rescheduled" not in actual_cols:
                batch_op.add_column(
                    sa.Column("is_rescheduled", sa.Boolean(), server_default=sa.text("false"), nullable=False)
                )
            if "slot_origin_date" not in actual_cols:
                batch_op.add_column(
                    sa.Column("slot_origin_date", sa.Date(), nullable=True)
                )

        actual_indexes = {ix["name"].lower() for ix in inspector.get_indexes("Lessons")}
        if "ix_lessons_recurring_slot_id" not in actual_indexes:
            try:
                op.create_index("ix_Lessons_recurring_slot_id", "Lessons", ["recurring_slot_id"])
            except Exception:
                pass
        if "ix_lessons_recurrence_key" not in actual_indexes:
            try:
                op.create_index("ix_Lessons_recurrence_key", "Lessons", ["recurrence_key"], unique=True)
            except Exception:
                pass
        if "ix_lessons_slot_origin_date" not in actual_indexes:
            try:
                op.create_index("ix_Lessons_slot_origin_date", "Lessons", ["slot_origin_date"])
            except Exception:
                pass

    # 2. Update RecurringLessonSlots table
    if "recurringlessonslots" in tables:
        actual_cols = {c["name"].lower() for c in inspector.get_columns("RecurringLessonSlots")}
        with op.batch_alter_table("RecurringLessonSlots", schema=None) as batch_op:
            if "subject" not in actual_cols:
                batch_op.add_column(
                    sa.Column("subject", sa.String(length=100), server_default="Информатика", nullable=True)
                )
            if "topic" not in actual_cols:
                batch_op.add_column(
                    sa.Column("topic", sa.String(length=300), nullable=True)
                )
            if "start_date" not in actual_cols:
                batch_op.add_column(
                    sa.Column("start_date", sa.Date(), nullable=True)
                )
            if "end_date" not in actual_cols:
                batch_op.add_column(
                    sa.Column("end_date", sa.Date(), nullable=True)
                )
            if "series_id" not in actual_cols:
                batch_op.add_column(
                    sa.Column("series_id", sa.String(length=64), nullable=True)
                )

    # 3. Create RecurringSlotExceptions
    if "recurringslotexceptions" not in tables:
        op.create_table(
            "RecurringSlotExceptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slot_id", sa.Integer(), sa.ForeignKey("RecurringLessonSlots.slot_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("exception_date", sa.Date(), nullable=False, index=True),
            sa.Column("action", sa.String(length=20), server_default="skip", nullable=False),
            sa.Column("rescheduled_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("slot_id", "exception_date", name="uq_slot_exception_date"),
        )

    # 4. Create TeacherWeeklyAvailabilities
    if "teacherweeklyavailabilities" not in tables:
        op.create_table(
            "TeacherWeeklyAvailabilities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("weekday", sa.Integer(), nullable=False, index=True),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 5. Create TeacherScheduleExceptions
    if "teacherscheduleexceptions" not in tables:
        op.create_table(
            "TeacherScheduleExceptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("exception_date", sa.Date(), nullable=False, index=True),
            sa.Column("exception_type", sa.String(length=30), server_default="unavailable", nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=True),
            sa.Column("end_time", sa.String(length=5), nullable=True),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    if "teacherscheduleexceptions" in tables:
        op.drop_table("TeacherScheduleExceptions")
    if "teacherweeklyavailabilities" in tables:
        op.drop_table("TeacherWeeklyAvailabilities")
    if "recurringslotexceptions" in tables:
        op.drop_table("RecurringSlotExceptions")

    if "recurringlessonslots" in tables:
        actual_cols = {c["name"].lower() for c in inspector.get_columns("RecurringLessonSlots")}
        with op.batch_alter_table("RecurringLessonSlots", schema=None) as batch_op:
            for col in ["series_id", "end_date", "start_date", "topic", "subject"]:
                if col in actual_cols:
                    batch_op.drop_column(col)

    if "lessons" in tables:
        actual_indexes = {ix["name"].lower() for ix in inspector.get_indexes("Lessons")}
        for ix in ["ix_lessons_slot_origin_date", "ix_lessons_recurrence_key", "ix_lessons_recurring_slot_id"]:
            if ix in actual_indexes:
                try:
                    op.drop_index(ix, table_name="Lessons")
                except Exception:
                    pass

        actual_cols = {c["name"].lower() for c in inspector.get_columns("Lessons")}
        with op.batch_alter_table("Lessons", schema=None) as batch_op:
            for col in ["slot_origin_date", "is_rescheduled", "recurrence_key", "recurring_slot_id"]:
                if col in actual_cols:
                    batch_op.drop_column(col)
