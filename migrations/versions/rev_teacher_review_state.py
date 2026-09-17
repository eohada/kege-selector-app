"""persist per-task teacher review state

Revision ID: rev_teacher_review_state
Revises: py_ege_ws_answer_spec
Create Date: 2026-09-15 14:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "rev_teacher_review_state"
down_revision = "py_ege_ws_answer_spec"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"].lower() for column in sa.inspect(op.get_bind()).get_columns("Answers")}
    if "reviewed_at" not in columns:
        op.add_column("Answers", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    columns = {column["name"].lower() for column in sa.inspect(op.get_bind()).get_columns("Answers")}
    if "reviewed_at" in columns:
        op.drop_column("Answers", "reviewed_at")
