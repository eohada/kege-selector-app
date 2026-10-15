"""Create BooStudy's standalone 1,000-task Python practice bank.

Revision ID: python_practice_bank_20261015
Revises: task_provenance_20261014
Create Date: 2026-10-15 00:00:00.000000
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "python_practice_bank_20261015"
down_revision = "task_provenance_20261014"
branch_labels = None
depends_on = None


def _table(bind, expected_name):
    names = sa.inspect(bind).get_table_names()
    actual = next((name for name in names if name.lower() == expected_name.lower()), None)
    return sa.Table(actual, sa.MetaData(), autoload_with=bind) if actual else None


def upgrade():
    bind = op.get_bind()
    tasks = _table(bind, "Tasks")
    if tasks is None:
        raise RuntimeError("Tasks table must exist before installing the Python practice bank")

    if "bank_category" not in {column.name for column in tasks.columns}:
        op.add_column(
            tasks.name,
            sa.Column("bank_category", sa.String(length=40), nullable=False, server_default="exam"),
        )
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes(tasks.name)}
    if "ix_Tasks_bank_category" not in existing_indexes:
        op.create_index("ix_Tasks_bank_category", tasks.name, ["bank_category"], unique=False)

    if _table(bind, "TaskCodeTestSuites") is None:
        op.create_table(
            "TaskCodeTestSuites",
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("test_cases", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], [f"{tasks.name}.task_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("task_id"),
        )

    # Keep the migration payload deterministic; skip already inserted stable source keys on recovery.
    from app.utils.python_practice_bank import generate_python_practice_bank

    items = generate_python_practice_bank()
    refreshed_tasks = _table(bind, "Tasks")
    solutions = _table(bind, "TaskSolutions")
    suites = _table(bind, "TaskCodeTestSuites")
    if solutions is None or suites is None:
        raise RuntimeError("TaskSolutions and TaskCodeTestSuites tables are required")

    existing_keys = set(
        bind.execute(
            sa.select(refreshed_tasks.c.source_key).where(refreshed_tasks.c.source_key.like("boo-python-v1-%"))
        ).scalars()
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    task_rows = []
    for item in items:
        if item["source_key"] in existing_keys:
            continue
        task_rows.append({
            "course_id": None,
            "bank_category": "python_practice",
            "task_number": 0,
            "task_group_id": None,
            "site_task_id": None,
            "source_url": None,
            "source_name": "Авторский банк BooStudy",
            "source_year": None,
            "source_task_number": None,
            "exam_year": None,
            "source_key": item["source_key"],
            "content_fingerprint": item["content_fingerprint"],
            "prototype_status": "practice_only",
            "ingest_status": "ready",
            "content_html": item["content_html"],
            "answer": item["answer"],
            "attached_files": None,
            "created_by_id": None,
            "last_scraped": now,
            "knowledge_node_id": None,
            "difficulty_level": item["difficulty_level"],
            "hints": item["hints"],
            "source_prototype": item["source_prototype"],
            "bank_origin": "authored",
            "starter_code": item["starter_code"],
            "answer_spec": item["answer_spec"],
            "is_active": True,
            "kege_source_tag": None,
            "kege_difficulty_tier": None,
            "max_score": 1,
        })
    if task_rows:
        bind.execute(refreshed_tasks.insert(), task_rows)

    seeded = bind.execute(
        sa.select(refreshed_tasks.c.task_id, refreshed_tasks.c.source_key).where(
            refreshed_tasks.c.source_key.like("boo-python-v1-%")
        )
    ).mappings().all()
    ids_by_key = {row["source_key"]: row["task_id"] for row in seeded}
    solution_rows = []
    suite_rows = []
    for item in items:
        task_id = ids_by_key.get(item["source_key"])
        if task_id is None:
            raise RuntimeError(f"Python bank task was not inserted: {item['source_key']}")
        solution_rows.append({
            "task_id": task_id,
            "solution_text": item["solution_text"],
            "source": "manual",
            "needs_manual_review": False,
            "created_at": now,
            "updated_at": now,
        })
        if item["tests"]:
            suite_rows.append({"task_id": task_id, "test_cases": item["tests"], "created_at": now})

    existing_solution_ids = set(bind.execute(sa.select(solutions.c.task_id)).scalars())
    solution_rows = [row for row in solution_rows if row["task_id"] not in existing_solution_ids]
    if solution_rows:
        bind.execute(solutions.insert(), solution_rows)
    existing_suite_ids = set(bind.execute(sa.select(suites.c.task_id)).scalars())
    suite_rows = [row for row in suite_rows if row["task_id"] not in existing_suite_ids]
    if suite_rows:
        bind.execute(suites.insert(), suite_rows)


def downgrade():
    bind = op.get_bind()
    tasks = _table(bind, "Tasks")
    if tasks is None:
        return
    seed_ids = sa.select(tasks.c.task_id).where(tasks.c.source_key.like("boo-python-v1-%"))
    solutions = _table(bind, "TaskSolutions")
    suites = _table(bind, "TaskCodeTestSuites")
    if suites is not None:
        bind.execute(suites.delete().where(suites.c.task_id.in_(seed_ids)))
    if solutions is not None:
        bind.execute(solutions.delete().where(solutions.c.task_id.in_(seed_ids)))
    bind.execute(tasks.delete().where(tasks.c.source_key.like("boo-python-v1-%")))
    if suites is not None:
        op.drop_table(suites.name)
    if "bank_category" in {column.name for column in tasks.columns}:
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes(tasks.name)}
        if "ix_Tasks_bank_category" in indexes:
            op.drop_index("ix_Tasks_bank_category", table_name=tasks.name)
        op.drop_column(tasks.name, "bank_category")
