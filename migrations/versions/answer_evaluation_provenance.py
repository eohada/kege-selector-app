"""Persist append-only answer evaluation provenance.

Revision ID: answer_evaluation_provenance
Revises: ai_lab_tutor_core3_exam_mapping
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa


revision = "answer_evaluation_provenance"
down_revision = "ai_lab_tutor_core3_exam_mapping"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = {name.lower() for name in inspector.get_table_names()}
    if "answerevaluationrevisions" in tables:
        return
    op.create_table(
        "AnswerEvaluationRevisions",
        sa.Column("revision_id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("answer_id", sa.Integer(), sa.ForeignKey("Answers.answer_id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=48), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("Users.id"), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("max_score", sa.Integer(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("teacher_comment", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="current", nullable=False),
        sa.Column("supersedes_revision_id", sa.Integer(), sa.ForeignKey("AnswerEvaluationRevisions.revision_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("answer_id", "revision_no", name="uq_answer_evaluation_revision"),
    )
    op.create_index("ix_AnswerEvaluationRevisions_answer_id", "AnswerEvaluationRevisions", ["answer_id"])
    op.create_index("ix_AnswerEvaluationRevisions_actor_user_id", "AnswerEvaluationRevisions", ["actor_user_id"])
    op.create_index("ix_answer_evaluation_state", "AnswerEvaluationRevisions", ["answer_id", "state"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = {name.lower() for name in inspector.get_table_names()}
    if "answerevaluationrevisions" not in tables:
        return
    op.drop_index("ix_answer_evaluation_state", table_name="AnswerEvaluationRevisions")
    op.drop_index("ix_AnswerEvaluationRevisions_actor_user_id", table_name="AnswerEvaluationRevisions")
    op.drop_index("ix_AnswerEvaluationRevisions_answer_id", table_name="AnswerEvaluationRevisions")
    op.drop_table("AnswerEvaluationRevisions")
