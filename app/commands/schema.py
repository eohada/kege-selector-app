"""Database schema contract command."""
from __future__ import annotations

import json

import click
from flask import current_app
from flask.cli import with_appcontext

from app.utils.schema_contract import schema_contract_report


@click.command('schema-audit')
@click.option('--json-output', is_flag=True, help='Print the report as JSON.')
@with_appcontext
def schema_audit_command(json_output):
    """Fail when the connected database differs from the mapped application schema."""
    report = schema_contract_report(current_app)
    if json_output:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
    elif report['ok']:
        click.echo('Schema contract: OK')
    else:
        click.echo('Schema contract: FAILED')
        for issue in report['issues']:
            click.echo(f"- missing {issue['kind']}: {issue['table']}.{issue['name']}")

    if not report['ok']:
        raise click.ClickException('Database schema does not match the application model. Run flask db upgrade.')
