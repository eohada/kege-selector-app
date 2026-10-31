"""Store structured editorial checks for Tutor Core knowledge versions.

Revision ID: ai_lab_knowledge_editor_v5
Revises: ai_lab_tutor_knowledge_base
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ai_lab_knowledge_editor_v5"
down_revision = "ai_lab_tutor_knowledge_base"
branch_labels = None
depends_on = None


def upgrade():
    review_details_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "AiLabKnowledgeReviewEvents",
        sa.Column("review_details_json", review_details_type, nullable=True),
    )


def downgrade():
    op.drop_column("AiLabKnowledgeReviewEvents", "review_details_json")
