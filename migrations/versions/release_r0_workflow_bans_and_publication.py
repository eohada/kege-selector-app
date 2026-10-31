"""Alembic migration for Release R0: LessonParticipantBans and Submission.results_published_at.

Revision ID: release_r0_workflow_bans_and_publication
Revises: answer_evaluation_provenance
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "release_r0_workflow_bans_and_publication"
down_revision = "answer_evaluation_provenance"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    # 1. Expand-only: Create LessonParticipantBans if not exists
    if "lessonparticipantbans" not in tables:
        op.create_table(
            "LessonParticipantBans",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("lesson_id", sa.Integer(), sa.ForeignKey("Lessons.lesson_id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("banned_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("banned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("unbanned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_LessonParticipantBans_lesson_id", "LessonParticipantBans", ["lesson_id"])
        op.create_index("ix_LessonParticipantBans_user_id", "LessonParticipantBans", ["user_id"])
        op.create_index(
            "ix_lesson_participant_ban_active",
            "LessonParticipantBans",
            ["lesson_id", "user_id", "is_active"],
        )

    # 2. Expand-only: Add results_published_at to Submissions if not exists
    if "submissions" in tables:
        actual_sub_cols = {c["name"].lower() for c in inspector.get_columns("Submissions")}
        if "results_published_at" not in actual_sub_cols:
            with op.batch_alter_table("Submissions", schema=None) as batch_op:
                batch_op.add_column(sa.Column("results_published_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower() for name in inspector.get_table_names()}

    if "lessonparticipantbans" in tables:
        try:
            op.drop_index("ix_lesson_participant_ban_active", table_name="LessonParticipantBans")
            op.drop_index("ix_LessonParticipantBans_user_id", table_name="LessonParticipantBans")
            op.drop_index("ix_LessonParticipantBans_lesson_id", table_name="LessonParticipantBans")
        except Exception:
            pass
        op.drop_table("LessonParticipantBans")

    if "submissions" in tables:
        actual_sub_cols = {c["name"].lower() for c in inspector.get_columns("Submissions")}
        if "results_published_at" in actual_sub_cols:
            with op.batch_alter_table("Submissions", schema=None) as batch_op:
                batch_op.drop_column("results_published_at")
