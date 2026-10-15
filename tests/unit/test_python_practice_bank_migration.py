import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_adds_new_bank_without_changing_existing_tasks():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    tasks = sa.Table(
        "Tasks", metadata,
        sa.Column("task_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("course_id", sa.Integer),
        sa.Column("task_number", sa.Integer, nullable=False),
        sa.Column("task_group_id", sa.String(64)),
        sa.Column("site_task_id", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("source_name", sa.String(160)),
        sa.Column("source_year", sa.SmallInteger),
        sa.Column("source_task_number", sa.SmallInteger),
        sa.Column("exam_year", sa.SmallInteger),
        sa.Column("source_key", sa.String(190), unique=True),
        sa.Column("content_fingerprint", sa.String(64)),
        sa.Column("prototype_status", sa.String(20)),
        sa.Column("ingest_status", sa.String(20)),
        sa.Column("content_html", sa.Text, nullable=False),
        sa.Column("answer", sa.Text),
        sa.Column("attached_files", sa.Text),
        sa.Column("created_by_id", sa.Integer),
        sa.Column("last_scraped", sa.DateTime),
        sa.Column("knowledge_node_id", sa.Integer),
        sa.Column("difficulty_level", sa.Integer),
        sa.Column("hints", sa.JSON),
        sa.Column("source_prototype", sa.String(256)),
        sa.Column("bank_origin", sa.String(32)),
        sa.Column("starter_code", sa.Text),
        sa.Column("answer_spec", sa.JSON),
        sa.Column("is_active", sa.Boolean),
        sa.Column("kege_source_tag", sa.String(64)),
        sa.Column("kege_difficulty_tier", sa.Integer),
        sa.Column("max_score", sa.Integer),
    )
    solutions = sa.Table(
        "TaskSolutions", metadata,
        sa.Column("solution_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer, nullable=False),
        sa.Column("solution_text", sa.Text, nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("needs_manual_review", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(tasks.insert(), [
            {"task_number": number % 27 + 1, "source_key": f"existing-final-test-{number:03d}", "content_html": f"existing item {number}", "answer": str(number)}
            for number in range(200)
        ])

    migration_path = Path(__file__).parents[2] / "migrations" / "versions" / "20261015_python_practice_bank.py"
    spec = importlib.util.spec_from_file_location("python_practice_bank_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()
        migrated_tasks = sa.Table("Tasks", sa.MetaData(), autoload_with=connection)
        assert connection.scalar(sa.select(sa.func.count()).select_from(migrated_tasks)) == 1200
        assert connection.scalar(sa.select(sa.func.count()).select_from(migrated_tasks).where(migrated_tasks.c.source_key.like("boo-python-v1-%"))) == 1000
        assert connection.scalar(sa.select(sa.func.count()).select_from(migrated_tasks).where(migrated_tasks.c.bank_category == "python_practice")) == 1000
        assert connection.scalar(sa.select(sa.func.count()).select_from(migrated_tasks).where(migrated_tasks.c.bank_category == "exam")) == 200
        assert connection.scalar(sa.text('SELECT count(*) FROM "TaskSolutions"')) == 1000
        assert connection.scalar(sa.text('SELECT count(*) FROM "TaskCodeTestSuites"')) == 250
        unchanged = connection.execute(
            sa.select(migrated_tasks.c.source_key, migrated_tasks.c.content_html, migrated_tasks.c.answer)
            .where(migrated_tasks.c.source_key.like("existing-final-test-%"))
            .order_by(migrated_tasks.c.source_key)
        ).all()
        assert len(unchanged) == 200
        assert unchanged[0].content_html == "existing item 0"
        assert unchanged[-1].answer == "199"
