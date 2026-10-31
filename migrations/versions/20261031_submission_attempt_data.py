"""Alembic migration: Add attempt_data to SubmissionAttempts.

Revision ID: 20261031_submission_attempt_data
Revises: schedule_sprint2_4_recurring_and_availability
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261031_submission_attempt_data"
down_revision = "schedule_sprint2_4_recurring_and_availability"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower(): name for name in inspector.get_table_names()}

    # Resolve real table name case-insensitively
    real_tbl = tables.get("submissionattempts")
    if real_tbl:
        actual_cols = {c["name"].lower() for c in inspector.get_columns(real_tbl)}
        if "attempt_data" not in actual_cols:
            col_type = (
                postgresql.JSONB(astext_type=sa.Text())
                if bind.dialect.name == "postgresql"
                else sa.JSON()
            )
            with op.batch_alter_table(real_tbl, schema=None) as batch_op:
                batch_op.add_column(sa.Column("attempt_data", col_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = {name.lower(): name for name in inspector.get_table_names()}

    real_tbl = tables.get("submissionattempts")
    if real_tbl:
        actual_cols = {c["name"].lower() for c in inspector.get_columns(real_tbl)}
        if "attempt_data" in actual_cols:
            with op.batch_alter_table(real_tbl, schema=None) as batch_op:
                batch_op.drop_column("attempt_data")
