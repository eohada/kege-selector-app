"""Bind Code Judge suites to versioned AI Lab assignments.

Revision ID: ai_lab_cj_assignment
Revises: ai_lab_code_judge_rubric
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa


revision = "ai_lab_cj_assignment"
down_revision = "ai_lab_code_judge_rubric"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("AiLabCodeJudgeTestSets") as batch:
        batch.add_column(sa.Column("assignment_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("assignment_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rubric_version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_index("ix_AiLabCodeJudgeTestSets_assignment_id", ["assignment_id"])


def downgrade():
    with op.batch_alter_table("AiLabCodeJudgeTestSets") as batch:
        batch.drop_index("ix_AiLabCodeJudgeTestSets_assignment_id")
        batch.drop_column("rubric_version")
        batch.drop_column("assignment_version")
        batch.drop_column("assignment_id")
