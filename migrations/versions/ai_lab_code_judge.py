"""Add isolated Code Judge task sets and execution history.

Revision ID: ai_lab_code_judge
Revises: ai_lab_homework_studio
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa


revision = "ai_lab_code_judge"
down_revision = "ai_lab_homework_studio"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "AiLabCodeJudgeTestSets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("scenario_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("function_name", sa.String(length=80), nullable=True),
        sa.Column("comparator", sa.String(length=32), nullable=False, server_default="exact"),
        sa.Column("tolerance", sa.Float(), nullable=False, server_default="0.000001"),
        sa.Column("starter_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("test_cases", sa.JSON(), nullable=False),
        sa.Column("test_set_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_seeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scenario_id", name="uq_ai_lab_code_judge_scenario_id"),
    )
    op.create_index("ix_AiLabCodeJudgeTestSets_scenario_id", "AiLabCodeJudgeTestSets", ["scenario_id"])
    op.create_index("ix_AiLabCodeJudgeTestSets_created_by_user_id", "AiLabCodeJudgeTestSets", ["created_by_user_id"])

    op.create_table(
        "AiLabCodeJudgeRuns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("test_set_id", sa.Integer(), sa.ForeignKey("AiLabCodeJudgeTestSets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=80), nullable=False),
        sa.Column("run_type", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("test_set_version", sa.Integer(), nullable=False),
        sa.Column("runner_version", sa.String(length=80), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("technical_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("actor_user_id", "request_key", name="uq_ai_lab_code_judge_actor_request"),
    )
    op.create_index("ix_AiLabCodeJudgeRuns_actor_user_id", "AiLabCodeJudgeRuns", ["actor_user_id"])
    op.create_index("ix_AiLabCodeJudgeRuns_test_set_id", "AiLabCodeJudgeRuns", ["test_set_id"])
    op.create_index("ix_AiLabCodeJudgeRuns_scenario_id", "AiLabCodeJudgeRuns", ["scenario_id"])
    op.create_index("ix_AiLabCodeJudgeRuns_status", "AiLabCodeJudgeRuns", ["status"])
    op.create_index("ix_AiLabCodeJudgeRuns_code_hash", "AiLabCodeJudgeRuns", ["code_hash"])
    op.create_index("ix_AiLabCodeJudgeRuns_created_at", "AiLabCodeJudgeRuns", ["created_at"])
    op.create_index("ix_ai_lab_code_judge_created_status", "AiLabCodeJudgeRuns", ["created_at", "status"])


def downgrade():
    op.drop_index("ix_ai_lab_code_judge_created_status", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_created_at", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_code_hash", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_status", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_scenario_id", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_test_set_id", table_name="AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeRuns_actor_user_id", table_name="AiLabCodeJudgeRuns")
    op.drop_table("AiLabCodeJudgeRuns")
    op.drop_index("ix_AiLabCodeJudgeTestSets_created_by_user_id", table_name="AiLabCodeJudgeTestSets")
    op.drop_index("ix_AiLabCodeJudgeTestSets_scenario_id", table_name="AiLabCodeJudgeTestSets")
    op.drop_table("AiLabCodeJudgeTestSets")
