"""theory study assignments

Revision ID: f4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-09 23:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "TheoryStudyAssignments" in set(inspector.get_table_names()):
        return
    op.create_table(
        "TheoryStudyAssignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("block_id", sa.Integer(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="assigned"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["student_id"], ["Students.student_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["block_id"], ["TheoryBlocks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["Users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "block_id", name="uq_theory_study_assignment"),
    )
    op.create_index(op.f("ix_TheoryStudyAssignments_student_id"), "TheoryStudyAssignments", ["student_id"], unique=False)
    op.create_index(op.f("ix_TheoryStudyAssignments_block_id"), "TheoryStudyAssignments", ["block_id"], unique=False)
    op.create_index(op.f("ix_TheoryStudyAssignments_assigned_by_user_id"), "TheoryStudyAssignments", ["assigned_by_user_id"], unique=False)
    op.create_index(op.f("ix_TheoryStudyAssignments_status"), "TheoryStudyAssignments", ["status"], unique=False)


def downgrade():
    pass
