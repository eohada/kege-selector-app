"""Versioned local rubric builder proposals.

Revision ID: ai_lab_rubric_builder
Revises: ai_lab_cj_assignment
"""

from alembic import op
import sqlalchemy as sa

revision = 'ai_lab_rubric_builder'
down_revision = 'ai_lab_cj_assignment'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'AiLabRubricVersions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rubric_key', sa.String(36), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('assignment_id', sa.String(120), nullable=False),
        sa.Column('assignment_version', sa.Integer(), nullable=False),
        sa.Column('task_json', sa.JSON(), nullable=False),
        sa.Column('criteria_json', sa.JSON(), nullable=False),
        sa.Column('proposed_tests_json', sa.JSON(), nullable=False),
        sa.Column('raw_proposal_json', sa.JSON(), nullable=True),
        sa.Column('edits_json', sa.JSON(), nullable=False),
        sa.Column('validation_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('model', sa.String(160), nullable=True),
        sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('generation_json', sa.JSON(), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='SET NULL')),
        sa.Column('approved_by_user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('rubric_key', 'version_no', name='uq_ai_lab_rubric_key_version'),
    )
    op.create_index('ix_AiLabRubricVersions_rubric_key', 'AiLabRubricVersions', ['rubric_key'])
    op.create_index('ix_AiLabRubricVersions_assignment_id', 'AiLabRubricVersions', ['assignment_id'])
    op.create_index('ix_AiLabRubricVersions_status', 'AiLabRubricVersions', ['status'])
    op.create_table(
        'AiLabRubricTestVerifications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rubric_version_id', sa.Integer(), sa.ForeignKey('AiLabRubricVersions.id'), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='SET NULL')),
        sa.Column('reference_hash', sa.String(64), nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_AiLabRubricTestVerifications_rubric_version_id', 'AiLabRubricTestVerifications', ['rubric_version_id'])


def downgrade():
    op.drop_table('AiLabRubricTestVerifications')
    op.drop_table('AiLabRubricVersions')
