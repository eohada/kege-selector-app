"""Create the versioned local Tutor Core knowledge base.

Revision ID: ai_lab_tutor_knowledge_base
Revises: ai_lab_sprint10_task_variants
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ai_lab_tutor_knowledge_base"
down_revision = "ai_lab_sprint10_task_variants"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "AiLabKnowledgeSources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("edition", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("publisher", sa.String(length=160), nullable=False),
        sa.Column("url", sa.String(length=600), nullable=False),
        sa.Column("source_status", sa.String(length=32), nullable=False, server_default="official"),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_key", "edition", name="uq_ai_lab_knowledge_source_edition"),
    )
    op.create_index("ix_AiLabKnowledgeSources_source_key", "AiLabKnowledgeSources", ["source_key"])

    op.create_table(
        "AiLabKnowledgeEntries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stable_key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("knowledge_node_id", sa.Integer(), sa.ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("codifier_codes_json", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("entry_kind", sa.String(length=32), nullable=False, server_default="concept"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_AiLabKnowledgeEntries_subject_id", "AiLabKnowledgeEntries", ["subject_id"])
    op.create_index("ix_AiLabKnowledgeEntries_knowledge_node_id", "AiLabKnowledgeEntries", ["knowledge_node_id"])

    op.create_table(
        "AiLabKnowledgeVersions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("AiLabKnowledgeEntries.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content_json", _json_type(), nullable=False),
        sa.Column("source_refs_json", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tags_json", _json_type(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("change_reason", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("entry_id", "version_no", name="uq_ai_lab_knowledge_entry_version"),
    )
    op.create_index("ix_AiLabKnowledgeVersions_entry_id", "AiLabKnowledgeVersions", ["entry_id"])
    op.create_index("ix_ai_lab_knowledge_version_entry_created", "AiLabKnowledgeVersions", ["entry_id", "created_at"])

    op.create_table(
        "AiLabKnowledgeReviewEvents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("AiLabKnowledgeVersions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_AiLabKnowledgeReviewEvents_version_id", "AiLabKnowledgeReviewEvents", ["version_id"])
    op.create_index("ix_ai_lab_knowledge_review_version_created", "AiLabKnowledgeReviewEvents", ["version_id", "created_at"])


def downgrade():
    op.drop_index("ix_ai_lab_knowledge_review_version_created", table_name="AiLabKnowledgeReviewEvents")
    op.drop_index("ix_AiLabKnowledgeReviewEvents_version_id", table_name="AiLabKnowledgeReviewEvents")
    op.drop_table("AiLabKnowledgeReviewEvents")
    op.drop_index("ix_ai_lab_knowledge_version_entry_created", table_name="AiLabKnowledgeVersions")
    op.drop_index("ix_AiLabKnowledgeVersions_entry_id", table_name="AiLabKnowledgeVersions")
    op.drop_table("AiLabKnowledgeVersions")
    op.drop_index("ix_AiLabKnowledgeEntries_knowledge_node_id", table_name="AiLabKnowledgeEntries")
    op.drop_index("ix_AiLabKnowledgeEntries_subject_id", table_name="AiLabKnowledgeEntries")
    op.drop_table("AiLabKnowledgeEntries")
    op.drop_index("ix_AiLabKnowledgeSources_source_key", table_name="AiLabKnowledgeSources")
    op.drop_table("AiLabKnowledgeSources")
