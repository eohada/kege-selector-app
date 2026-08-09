"""theory groups and feedback history

Revision ID: c0f4d9d2b9b1
Revises: 887752e658f5
Create Date: 2026-03-31 19:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c0f4d9d2b9b1"
down_revision = "887752e658f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    theory_block_columns = (
        {column['name'] for column in inspector.get_columns('TheoryBlocks')}
        if 'TheoryBlocks' in tables else set()
    )
    # Existing installations were historically bootstrapped with create_all().
    # If their complete theory schema is already present, only advance Alembic.
    if (
        'TheoryGroups' in tables
        and 'TheoryFeedbackHistory' in tables
        and {'group_id', 'description', 'position'}.issubset(theory_block_columns)
    ):
        return

    op.create_table(
        "TheoryGroups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["ExamCourses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["Users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "name", name="uq_theory_group_course_name"),
    )
    op.create_index(op.f("ix_TheoryGroups_course_id"), "TheoryGroups", ["course_id"], unique=False)
    op.create_index(op.f("ix_TheoryGroups_created_by"), "TheoryGroups", ["created_by"], unique=False)
    op.create_index(op.f("ix_TheoryGroups_position"), "TheoryGroups", ["position"], unique=False)

    with op.batch_alter_table("TheoryBlocks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_index(batch_op.f("ix_TheoryBlocks_group_id"), ["group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_TheoryBlocks_position"), ["position"], unique=False)
        batch_op.create_foreign_key("fk_TheoryBlocks_group_id_TheoryGroups", "TheoryGroups", ["group_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "TheoryFeedbackHistory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("task_number", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["ExamCourses.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["Students.student_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["Users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_TheoryFeedbackHistory_course_id"), "TheoryFeedbackHistory", ["course_id"], unique=False)
    op.create_index(op.f("ix_TheoryFeedbackHistory_created_at"), "TheoryFeedbackHistory", ["created_at"], unique=False)
    op.create_index(op.f("ix_TheoryFeedbackHistory_student_id"), "TheoryFeedbackHistory", ["student_id"], unique=False)
    op.create_index(op.f("ix_TheoryFeedbackHistory_task_number"), "TheoryFeedbackHistory", ["task_number"], unique=False)
    op.create_index(op.f("ix_TheoryFeedbackHistory_user_id"), "TheoryFeedbackHistory", ["user_id"], unique=False)

    conn = bind
    rows = conn.execute(sa.text("SELECT DISTINCT course_id FROM TheoryBlocks")).fetchall()
    for row in rows:
        course_id = row[0]
        conn.execute(
            sa.text(
                """
                INSERT INTO TheoryGroups (course_id, name, description, position, created_by, created_at, updated_at)
                VALUES (:course_id, :name, :description, 0, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "course_id": course_id,
                "name": "Общая группа",
                "description": "Группа, созданная автоматически при миграции",
            },
        )
        group_id = conn.execute(
            sa.text(
                """
                SELECT id FROM TheoryGroups
                WHERE course_id IS NOT DISTINCT FROM :course_id
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"course_id": course_id},
        ).scalar()
        if group_id:
            conn.execute(
                sa.text(
                    """
                    UPDATE TheoryBlocks
                    SET group_id = :group_id,
                        position = CASE
                            WHEN task_number IS NULL THEN 0
                            ELSE task_number
                        END
                    WHERE course_id IS NOT DISTINCT FROM :course_id
                    """
                ),
                {"group_id": group_id, "course_id": course_id},
            )


def downgrade():
    op.drop_index(op.f("ix_TheoryFeedbackHistory_user_id"), table_name="TheoryFeedbackHistory")
    op.drop_index(op.f("ix_TheoryFeedbackHistory_task_number"), table_name="TheoryFeedbackHistory")
    op.drop_index(op.f("ix_TheoryFeedbackHistory_student_id"), table_name="TheoryFeedbackHistory")
    op.drop_index(op.f("ix_TheoryFeedbackHistory_created_at"), table_name="TheoryFeedbackHistory")
    op.drop_index(op.f("ix_TheoryFeedbackHistory_course_id"), table_name="TheoryFeedbackHistory")
    op.drop_table("TheoryFeedbackHistory")

    with op.batch_alter_table("TheoryBlocks", schema=None) as batch_op:
        batch_op.drop_constraint("fk_TheoryBlocks_group_id_TheoryGroups", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_TheoryBlocks_position"))
        batch_op.drop_index(batch_op.f("ix_TheoryBlocks_group_id"))
        batch_op.drop_column("position")
        batch_op.drop_column("description")
        batch_op.drop_column("group_id")

    op.drop_index(op.f("ix_TheoryGroups_position"), table_name="TheoryGroups")
    op.drop_index(op.f("ix_TheoryGroups_created_by"), table_name="TheoryGroups")
    op.drop_index(op.f("ix_TheoryGroups_course_id"), table_name="TheoryGroups")
    op.drop_table("TheoryGroups")
