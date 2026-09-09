"""Add stable metadata for imported task-template libraries."""

from alembic import op
import sqlalchemy as sa


revision = "python_ege_template_library"
down_revision = "merge_assignment_guest_heads"
branch_labels = None
depends_on = None


def _columns(bind):
    return {item["name"] for item in sa.inspect(bind).get_columns("TaskTemplates")}


def _indexes(bind):
    return {item["name"] for item in sa.inspect(bind).get_indexes("TaskTemplates")}


def upgrade():
    bind = op.get_bind()
    columns = _columns(bind)
    additions = (
        ("external_key", sa.Column("external_key", sa.String(length=120), nullable=True)),
        ("folder_path", sa.Column("folder_path", sa.String(length=255), nullable=True)),
        ("is_draft", sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("is_featured", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("settings_json", sa.Column("settings_json", sa.JSON(), nullable=True)),
        ("sections_json", sa.Column("sections_json", sa.JSON(), nullable=True)),
        ("attachments_json", sa.Column("attachments_json", sa.JSON(), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("TaskTemplates", column)
    indexes = _indexes(bind)
    if "ix_TaskTemplates_external_key" not in indexes:
        op.create_index("ix_TaskTemplates_external_key", "TaskTemplates", ["external_key"], unique=True)
    if "ix_TaskTemplates_folder_path" not in indexes:
        op.create_index("ix_TaskTemplates_folder_path", "TaskTemplates", ["folder_path"], unique=False)
    if "ix_TaskTemplates_is_draft" not in indexes:
        op.create_index("ix_TaskTemplates_is_draft", "TaskTemplates", ["is_draft"], unique=False)
    if "ix_TaskTemplates_is_featured" not in indexes:
        op.create_index("ix_TaskTemplates_is_featured", "TaskTemplates", ["is_featured"], unique=False)


def downgrade():
    bind = op.get_bind()
    indexes = _indexes(bind)
    for name in ("ix_TaskTemplates_is_featured", "ix_TaskTemplates_is_draft", "ix_TaskTemplates_folder_path", "ix_TaskTemplates_external_key"):
        if name in indexes:
            op.drop_index(name, table_name="TaskTemplates")
    columns = _columns(bind)
    for name in ("attachments_json", "sections_json", "settings_json", "is_featured", "is_draft", "folder_path", "external_key"):
        if name in columns:
            op.drop_column("TaskTemplates", name)
