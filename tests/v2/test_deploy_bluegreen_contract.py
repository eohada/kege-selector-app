"""Regression checks for the production blue-green deployment contract."""
from pathlib import Path


def test_blue_green_deploy_recovers_only_orphaned_alembic_history():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'deploy_blue_green.sh').read_text(
        encoding='utf-8'
    )

    assert 'MIGRATION_RECOVERY_ANCHOR="${MIGRATION_RECOVERY_ANCHOR:-f2b3c4d5e6f7}"' in script
    assert "Can't locate revision identified" in script
    assert 'flask db stamp "$MIGRATION_RECOVERY_ANCHOR" --purge -d /app/migrations' in script
    assert 'flask schema-audit' in script
    assert 'wait_ready "$target"' in script
    assert 'write_nginx_upstream "$target"' in script


def test_blue_green_deploy_keeps_traffic_on_current_service_until_readiness():
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'deploy_blue_green.sh').read_text(
        encoding='utf-8'
    )

    assert script.index('wait_ready "$target"') < script.index('write_nginx_upstream "$target"')
