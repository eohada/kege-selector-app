"""Create isolated AI Homework Lab storage.

Revision ID: ai_lab_homework_studio
Revises: python_practice_bank_20261015
Create Date: 2026-10-15
"""

from alembic import op
import sqlalchemy as sa


revision = "ai_lab_homework_studio"
down_revision = "python_practice_bank_20261015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "AiLabPromptVersions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("prompt_name", sa.String(length=120), nullable=False, server_default="AI Homework Evaluator"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("restored_from_version_no", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("Users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("version_no", name="uq_ai_lab_prompt_version_no"),
    )
    op.create_index(
        "ix_AiLabPromptVersions_created_by_user_id",
        "AiLabPromptVersions",
        ["created_by_user_id"],
    )

    op.create_table(
        "AiLabExperiments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("Users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column(
            "prompt_version_id",
            sa.Integer(),
            sa.ForeignKey("AiLabPromptVersions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt_version_no", sa.Integer(), nullable=True),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("scenario_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("expected_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("quality_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("manual_rating", sa.String(length=24), nullable=True),
        sa.Column("manual_comment", sa.Text(), nullable=True),
        sa.Column(
            "reviewer_user_id",
            sa.Integer(),
            sa.ForeignKey("Users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_ai_lab_run_actor_request"),
    )
    op.create_index("ix_AiLabExperiments_actor_user_id", "AiLabExperiments", ["actor_user_id"])
    op.create_index("ix_AiLabExperiments_scenario_id", "AiLabExperiments", ["scenario_id"])
    op.create_index("ix_AiLabExperiments_status", "AiLabExperiments", ["status"])
    op.create_index("ix_AiLabExperiments_created_at", "AiLabExperiments", ["created_at"])
    op.create_index(
        "ix_ai_lab_run_created_status",
        "AiLabExperiments",
        ["created_at", "status"],
    )
    op.create_index(
        "ix_ai_lab_run_scenario_created",
        "AiLabExperiments",
        ["scenario_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_ai_lab_run_scenario_created", table_name="AiLabExperiments")
    op.drop_index("ix_ai_lab_run_created_status", table_name="AiLabExperiments")
    op.drop_index("ix_AiLabExperiments_created_at", table_name="AiLabExperiments")
    op.drop_index("ix_AiLabExperiments_status", table_name="AiLabExperiments")
    op.drop_index("ix_AiLabExperiments_scenario_id", table_name="AiLabExperiments")
    op.drop_index("ix_AiLabExperiments_actor_user_id", table_name="AiLabExperiments")
    op.drop_table("AiLabExperiments")
    op.drop_index("ix_AiLabPromptVersions_created_by_user_id", table_name="AiLabPromptVersions")
    op.drop_table("AiLabPromptVersions")
