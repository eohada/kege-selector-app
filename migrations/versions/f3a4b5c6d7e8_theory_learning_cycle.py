"""theory learning cycle progress, notes and checkpoints

Revision ID: f3a4b5c6d7e8
Revises: f2b3c4d5e6f7
Create Date: 2026-08-09 23:05:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "StudentTheoryState" in tables:
        columns = {column["name"] for column in inspector.get_columns("StudentTheoryState")}
        with op.batch_alter_table("StudentTheoryState") as batch_op:
            if "reading_progress" not in columns:
                batch_op.add_column(sa.Column("reading_progress", sa.Integer(), nullable=False, server_default="0"))
            if "last_position" not in columns:
                batch_op.add_column(sa.Column("last_position", sa.Integer(), nullable=False, server_default="0"))

    if "TheoryCheckpointAttempts" not in tables:
        op.create_table(
            "TheoryCheckpointAttempts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=False),
            sa.Column("checkpoint_key", sa.String(length=80), nullable=False),
            sa.Column("selected_answer", sa.String(length=500), nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False),
            sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("answered_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["student_id"], ["Students.student_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["block_id"], ["TheoryBlocks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("student_id", "block_id", "checkpoint_key", name="uq_theory_checkpoint_attempt"),
        )
        op.create_index(op.f("ix_TheoryCheckpointAttempts_student_id"), "TheoryCheckpointAttempts", ["student_id"], unique=False)
        op.create_index(op.f("ix_TheoryCheckpointAttempts_block_id"), "TheoryCheckpointAttempts", ["block_id"], unique=False)
        op.create_index(op.f("ix_TheoryCheckpointAttempts_answered_at"), "TheoryCheckpointAttempts", ["answered_at"], unique=False)

    if "StudentTheoryNotes" not in tables:
        op.create_table(
            "StudentTheoryNotes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["student_id"], ["Students.student_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["block_id"], ["TheoryBlocks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("student_id", "block_id", name="uq_student_theory_note"),
        )
        op.create_index(op.f("ix_StudentTheoryNotes_student_id"), "StudentTheoryNotes", ["student_id"], unique=False)
        op.create_index(op.f("ix_StudentTheoryNotes_block_id"), "StudentTheoryNotes", ["block_id"], unique=False)


def downgrade():
    # Production migrations are forward-only to preserve learner data.
    pass
