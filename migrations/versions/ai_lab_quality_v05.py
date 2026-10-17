"""Append-only expert rubric reviews in local AI Lab.

Revision ID: ai_lab_quality_v05
Revises: ai_lab_rubric_builder
"""
from alembic import op
import sqlalchemy as sa

revision = 'ai_lab_quality_v05'
down_revision = 'ai_lab_rubric_builder'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'AiLabRubricReviews',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rubric_version_id', sa.Integer(), sa.ForeignKey('AiLabRubricVersions.id'), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('Users.id', ondelete='SET NULL')),
        sa.Column('verdict', sa.String(16), nullable=False),
        sa.Column('issues_json', sa.JSON(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_AiLabRubricReviews_rubric_version_id', 'AiLabRubricReviews', ['rubric_version_id'])


def downgrade():
    op.drop_table('AiLabRubricReviews')
