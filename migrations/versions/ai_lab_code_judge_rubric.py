"""Add criterion definitions to local Code Judge test sets.

Revision ID: ai_lab_code_judge_rubric
Revises: ai_lab_code_judge
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa


revision = "ai_lab_code_judge_rubric"
down_revision = "ai_lab_code_judge"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("AiLabCodeJudgeTestSets") as batch:
        batch.add_column(sa.Column("rubric_json", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    with op.batch_alter_table("AiLabCodeJudgeTestSets") as batch:
        batch.drop_column("rubric_json")
