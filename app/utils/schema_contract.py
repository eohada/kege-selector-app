"""Read-only verification that a database matches the application's mapped schema."""
from __future__ import annotations

from sqlalchemy import inspect


def _lookup_case_insensitive(names, expected):
    expected_lower = expected.lower()
    return next((name for name in names if name.lower() == expected_lower), None)


def collect_schema_contract_issues(engine, metadata):
    """Return missing mapped tables, columns and explicit model indexes.

    This intentionally does not mutate the schema: schema changes belong to Alembic
    migrations and are caught before an unhealthy release receives traffic.
    """
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    issues = []

    for expected_name, table in sorted(metadata.tables.items()):
        actual_name = _lookup_case_insensitive(actual_tables, expected_name)
        if not actual_name:
            issues.append({'kind': 'table', 'table': expected_name, 'name': expected_name})
            continue

        actual_columns = {column['name'].lower() for column in inspector.get_columns(actual_name)}
        for column in table.columns:
            if column.name.lower() not in actual_columns:
                issues.append({'kind': 'column', 'table': expected_name, 'name': column.name})

        actual_indexes = {
            index['name'].lower()
            for index in inspector.get_indexes(actual_name)
            if index.get('name')
        }
        for index in table.indexes:
            if index.name and index.name.lower() not in actual_indexes:
                issues.append({'kind': 'index', 'table': expected_name, 'name': index.name})

    return issues


def schema_contract_report(app):
    from app.models import db

    issues = collect_schema_contract_issues(db.engine, db.metadata)
    return {'ok': not issues, 'issues': issues}


def schema_contract_is_ready():
    from flask import current_app

    uri = (current_app.config.get('SQLALCHEMY_DATABASE_URI') or '').lower()
    if uri.startswith('sqlite'):
        return True
    try:
        return schema_contract_report(current_app)['ok']
    except Exception:
        return False
