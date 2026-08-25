"""Persist teacher scoring metadata and the guest diagnostic report."""

from alembic import op
import sqlalchemy as sa


revision = 'guest_diagnostic_report'
down_revision = 'guest_snapshot_idx_contract'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {column['name'] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    response_columns = _columns(bind, 'GuestResponses')
    if 'teacher_score' not in response_columns:
        op.add_column('GuestResponses', sa.Column('teacher_score', sa.Integer(), nullable=True))
    if 'error_reason' not in response_columns:
        op.add_column('GuestResponses', sa.Column('error_reason', sa.String(40), nullable=True))
    review_columns = _columns(bind, 'GuestReviews')
    if 'report' not in review_columns:
        op.add_column('GuestReviews', sa.Column('report', sa.JSON(), nullable=False, server_default='{}'))


def downgrade():
    bind = op.get_bind()
    if 'report' in _columns(bind, 'GuestReviews'):
        op.drop_column('GuestReviews', 'report')
    response_columns = _columns(bind, 'GuestResponses')
    if 'error_reason' in response_columns:
        op.drop_column('GuestResponses', 'error_reason')
    if 'teacher_score' in response_columns:
        op.drop_column('GuestResponses', 'teacher_score')
