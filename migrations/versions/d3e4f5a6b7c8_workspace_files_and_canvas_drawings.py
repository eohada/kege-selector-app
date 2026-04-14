"""workspace files and canvas drawings

Revision ID: d3e4f5a6b7c8
Revises: 9f2b7c6e1a11
Create Date: 2026-04-14 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "d3e4f5a6b7c8"
down_revision = "9f2b7c6e1a11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "StudentWorkspaceFiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("context_type", sa.String(length=32), nullable=False, server_default="submission"),
        sa.Column("context_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("current_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("is_from_task", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["Users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["Tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_swf_user_id", "StudentWorkspaceFiles", ["user_id"])
    op.create_index("ix_swf_task_id", "StudentWorkspaceFiles", ["task_id"])
    op.create_index("ix_swf_context_id", "StudentWorkspaceFiles", ["context_id"])

    op.create_table(
        "TaskCanvasDrawings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("context_type", sa.String(length=32), nullable=False, server_default="submission"),
        sa.Column("context_id", sa.Integer(), nullable=True),
        sa.Column("strokes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("thumbnail_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["Users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["Tasks.task_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tcd_user_id", "TaskCanvasDrawings", ["user_id"])
    op.create_index("ix_tcd_task_id", "TaskCanvasDrawings", ["task_id"])
    op.create_index("ix_tcd_context_id", "TaskCanvasDrawings", ["context_id"])
    op.create_index(
        "ix_canvas_user_task_ctx",
        "TaskCanvasDrawings",
        ["user_id", "task_id", "context_type", "context_id"],
    )


def downgrade():
    op.drop_table("TaskCanvasDrawings")
    op.drop_table("StudentWorkspaceFiles")
