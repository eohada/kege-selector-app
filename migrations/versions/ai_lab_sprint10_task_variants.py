"""Persist deterministic variants of approved AI Lab task families.

Revision ID: ai_lab_sprint10_task_variants
Revises: ai_lab_sprint9_families_retries
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ai_lab_sprint10_task_variants"
down_revision = "ai_lab_sprint9_families_retries"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "AiLabAssignmentVariants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("variant_id", sa.String(length=120), nullable=False, unique=True),
        sa.Column("family_version_id", sa.Integer(), sa.ForeignKey("AiLabAssignmentFamilyVersions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("family_id", sa.String(length=120), nullable=False),
        sa.Column("family_version_no", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(length=120), nullable=False),
        sa.Column("parameter_sha256", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", _json_type(), nullable=False),
        sa.Column("assignment_id", sa.String(length=120), nullable=False),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("starter_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference_code", sa.Text(), nullable=False),
        sa.Column("task_snapshot_json", _json_type(), nullable=False),
        sa.Column("test_set_id", sa.Integer(), sa.ForeignKey("AiLabCodeJudgeTestSets.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("test_set_version", sa.Integer(), nullable=False),
        sa.Column("reference_run_id", sa.Integer(), sa.ForeignKey("AiLabCodeJudgeRuns.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("validation_json", _json_type(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="materialized"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_version_id", "parameter_sha256", name="uq_ai_lab_family_variant_parameters"),
    )
    op.create_index("ix_AiLabAssignmentVariants_variant_id", "AiLabAssignmentVariants", ["variant_id"])
    op.create_index("ix_AiLabAssignmentVariants_family_version_id", "AiLabAssignmentVariants", ["family_version_id"])
    op.create_index("ix_AiLabAssignmentVariants_family_id", "AiLabAssignmentVariants", ["family_id"])
    op.create_index("ix_AiLabAssignmentVariants_assignment_id", "AiLabAssignmentVariants", ["assignment_id"])
    op.create_index("ix_AiLabAssignmentVariants_status", "AiLabAssignmentVariants", ["status"])
    op.create_index("ix_ai_lab_family_variant_status", "AiLabAssignmentVariants", ["family_version_id", "status"])


def downgrade():
    op.drop_index("ix_ai_lab_family_variant_status", table_name="AiLabAssignmentVariants")
    op.drop_index("ix_AiLabAssignmentVariants_status", table_name="AiLabAssignmentVariants")
    op.drop_index("ix_AiLabAssignmentVariants_assignment_id", table_name="AiLabAssignmentVariants")
    op.drop_index("ix_AiLabAssignmentVariants_family_id", table_name="AiLabAssignmentVariants")
    op.drop_index("ix_AiLabAssignmentVariants_family_version_id", table_name="AiLabAssignmentVariants")
    op.drop_index("ix_AiLabAssignmentVariants_variant_id", table_name="AiLabAssignmentVariants")
    op.drop_table("AiLabAssignmentVariants")
