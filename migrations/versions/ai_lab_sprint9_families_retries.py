"""AI Lab task families and durable provider-attempt audit.

Revision ID: ai_lab_sprint9_families_retries
Revises: task_studio_bookmarks
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ai_lab_sprint9_families_retries"
down_revision = "task_studio_bookmarks"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    with op.batch_alter_table("AiLabExperiments") as batch:
        batch.add_column(sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
        batch.create_index("ix_AiLabExperiments_request_fingerprint", ["request_fingerprint"], unique=False)

    op.create_table(
        "AiLabAssignmentFamilyVersions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.String(length=120), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("assignment_id", sa.String(length=120), nullable=False),
        sa.Column("assignment_version", sa.Integer(), nullable=False),
        sa.Column("rubric_version_id", sa.Integer(), sa.ForeignKey("AiLabRubricVersions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rubric_version_no", sa.Integer(), nullable=False),
        sa.Column("test_set_id", sa.Integer(), sa.ForeignKey("AiLabCodeJudgeTestSets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("test_set_version", sa.Integer(), nullable=False),
        sa.Column("reference_run_id", sa.Integer(), sa.ForeignKey("AiLabCodeJudgeRuns.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("contract_json", _json_type(), nullable=False),
        sa.Column("compatibility_json", _json_type(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("validation_json", _json_type(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("Users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("family_id", "version_no", name="uq_ai_lab_family_version"),
    )
    op.create_index("ix_AiLabAssignmentFamilyVersions_family_id", "AiLabAssignmentFamilyVersions", ["family_id"])
    op.create_index("ix_AiLabAssignmentFamilyVersions_assignment_id", "AiLabAssignmentFamilyVersions", ["assignment_id"])
    op.create_index("ix_AiLabAssignmentFamilyVersions_rubric_version_id", "AiLabAssignmentFamilyVersions", ["rubric_version_id"])
    op.create_index("ix_AiLabAssignmentFamilyVersions_test_set_id", "AiLabAssignmentFamilyVersions", ["test_set_id"])
    op.create_index("ix_AiLabAssignmentFamilyVersions_status", "AiLabAssignmentFamilyVersions", ["status"])
    op.create_index("ix_ai_lab_family_status", "AiLabAssignmentFamilyVersions", ["family_id", "status"])

    op.create_table(
        "AiLabProviderAttempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("AiLabExperiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("retry_reason", sa.String(length=40), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="started"),
        sa.Column("provider_payload_id", sa.String(length=180), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("request_metadata_json", _json_type(), nullable=False),
        sa.Column("usage_json", _json_type(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("experiment_id", "attempt_number", name="uq_ai_lab_provider_attempt_number"),
        sa.UniqueConstraint("idempotency_key", name="uq_ai_lab_provider_attempt_key"),
    )
    op.create_index("ix_AiLabProviderAttempts_experiment_id", "AiLabProviderAttempts", ["experiment_id"])
    op.create_index("ix_AiLabProviderAttempts_status", "AiLabProviderAttempts", ["status"])
    op.create_index("ix_ai_lab_provider_attempt_status", "AiLabProviderAttempts", ["status", "started_at"])


def downgrade():
    op.drop_index("ix_ai_lab_provider_attempt_status", table_name="AiLabProviderAttempts")
    op.drop_index("ix_AiLabProviderAttempts_status", table_name="AiLabProviderAttempts")
    op.drop_index("ix_AiLabProviderAttempts_experiment_id", table_name="AiLabProviderAttempts")
    op.drop_table("AiLabProviderAttempts")
    op.drop_index("ix_ai_lab_family_status", table_name="AiLabAssignmentFamilyVersions")
    op.drop_index("ix_AiLabAssignmentFamilyVersions_status", table_name="AiLabAssignmentFamilyVersions")
    op.drop_index("ix_AiLabAssignmentFamilyVersions_test_set_id", table_name="AiLabAssignmentFamilyVersions")
    op.drop_index("ix_AiLabAssignmentFamilyVersions_rubric_version_id", table_name="AiLabAssignmentFamilyVersions")
    op.drop_index("ix_AiLabAssignmentFamilyVersions_assignment_id", table_name="AiLabAssignmentFamilyVersions")
    op.drop_index("ix_AiLabAssignmentFamilyVersions_family_id", table_name="AiLabAssignmentFamilyVersions")
    op.drop_table("AiLabAssignmentFamilyVersions")
    with op.batch_alter_table("AiLabExperiments") as batch:
        batch.drop_index("ix_AiLabExperiments_request_fingerprint")
        batch.drop_column("request_fingerprint")
