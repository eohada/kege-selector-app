"""Versioned EGE task mappings and isolated Tutor Core demo registry.

Revision ID: ai_lab_tutor_core3_exam_mapping
Revises: ai_lab_knowledge_editor_v5
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ai_lab_tutor_core3_exam_mapping"
down_revision = "ai_lab_knowledge_editor_v5"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "AiLabExamTaskBindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("binding_key", sa.String(length=180), nullable=False),
        sa.Column("mapping_version", sa.SmallInteger(), nullable=False),
        sa.Column("revision_key", sa.String(length=100), nullable=False),
        sa.Column("exam_year", sa.SmallInteger(), nullable=False),
        sa.Column("document_version", sa.String(length=100), nullable=False),
        sa.Column("document_status", sa.String(length=24), nullable=False),
        sa.Column("task_number", sa.SmallInteger(), nullable=False),
        sa.Column("skill_code", sa.String(length=160), nullable=False),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("ExamSkills.skill_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_type", sa.String(length=180), nullable=False),
        sa.Column("input_format", sa.String(length=240), nullable=False),
        sa.Column("answer_format", sa.String(length=240), nullable=False),
        sa.Column("source_key", sa.String(length=190), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("editorial_status", sa.String(length=32), nullable=False, server_default="source_checked"),
        sa.Column("supersedes_binding_id", sa.Integer(), sa.ForeignKey("AiLabExamTaskBindings.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("binding_key", "mapping_version", name="uq_ai_lab_exam_binding_version"),
    )
    for column in ("binding_key", "revision_key", "exam_year", "document_status", "task_number", "skill_code", "skill_id", "editorial_status"):
        op.create_index(f"ix_AiLabExamTaskBindings_{column}", "AiLabExamTaskBindings", [column])
    op.create_index(
        "ix_ai_lab_exam_binding_revision_task",
        "AiLabExamTaskBindings",
        ["revision_key", "task_number"],
    )

    op.create_table(
        "AiLabTutorDemos",
        sa.Column("demo_key", sa.String(length=80), primary_key=True),
        sa.Column("demo_version", sa.SmallInteger(), nullable=False),
        sa.Column("seed_version", sa.String(length=80), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("Courses.course_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("student_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("Students.student_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("metadata_json", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for column in ("course_id", "student_user_id", "student_id"):
        op.create_index(f"ix_AiLabTutorDemos_{column}", "AiLabTutorDemos", [column])

    op.create_table(
        "AiLabTutorDemoEvents",
        sa.Column("event_id", sa.String(length=200), primary_key=True),
        sa.Column("demo_key", sa.String(length=80), sa.ForeignKey("AiLabTutorDemos.demo_key", ondelete="RESTRICT"), nullable=False),
        sa.Column("scenario_key", sa.String(length=80), nullable=False),
        sa.Column("event_json", _json_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_AiLabTutorDemoEvents_demo_key", "AiLabTutorDemoEvents", ["demo_key"])
    op.create_index("ix_AiLabTutorDemoEvents_scenario_key", "AiLabTutorDemoEvents", ["scenario_key"])


def downgrade():
    op.drop_index("ix_AiLabTutorDemoEvents_scenario_key", table_name="AiLabTutorDemoEvents")
    op.drop_index("ix_AiLabTutorDemoEvents_demo_key", table_name="AiLabTutorDemoEvents")
    op.drop_table("AiLabTutorDemoEvents")
    for column in ("student_id", "student_user_id", "course_id"):
        op.drop_index(f"ix_AiLabTutorDemos_{column}", table_name="AiLabTutorDemos")
    op.drop_table("AiLabTutorDemos")
    op.drop_index("ix_ai_lab_exam_binding_revision_task", table_name="AiLabExamTaskBindings")
    for column in ("editorial_status", "skill_id", "skill_code", "task_number", "document_status", "exam_year", "revision_key", "binding_key"):
        op.drop_index(f"ix_AiLabExamTaskBindings_{column}", table_name="AiLabExamTaskBindings")
    op.drop_table("AiLabExamTaskBindings")
