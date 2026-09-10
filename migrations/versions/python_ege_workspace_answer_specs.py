"""Add the answer specification used by the universal student workspace.

Revision ID: py_ege_ws_answer_spec
Revises: python_ege_template_library
Create Date: 2026-09-09 20:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "py_ege_ws_answer_spec"
down_revision = "python_ege_template_library"
branch_labels = None
depends_on = None


def _task_columns(bind):
    return {column["name"].lower() for column in sa.inspect(bind).get_columns("Tasks")}


def upgrade():
    if "answer_spec" not in _task_columns(op.get_bind()):
        op.add_column("Tasks", sa.Column("answer_spec", sa.JSON(), nullable=True))


def downgrade():
    if "answer_spec" in _task_columns(op.get_bind()):
        op.drop_column("Tasks", "answer_spec")
