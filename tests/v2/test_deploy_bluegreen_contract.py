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


def test_blue_green_rollback_strictly_never_downgrades_database():
    """Rollback policy: NO automated database downgrade during rollback.

    Database schema must remain forward-compatible, with rollback limited to
    traffic redirection back to the previous stable container.
    """
    script = (Path(__file__).resolve().parents[2] / 'scripts' / 'deploy_blue_green.sh').read_text(
        encoding='utf-8'
    )
    rollback_section = script[script.index('rollback() {'):script.index('status() {')]
    assert 'downgrade' not in rollback_section.lower()
    assert 'write_nginx_upstream "$previous"' in rollback_section


def test_staging_preflight_script_exists_and_covers_all_critical_gates():
    """Verify scripts/staging_preflight.sh checks PostgreSQL, Redis, LiveKit, disk, and migrations."""
    preflight = (Path(__file__).resolve().parents[2] / 'scripts' / 'staging_preflight.sh').read_text(
        encoding='utf-8'
    )
    assert 'PostgreSQL' in preflight
    assert 'Redis' in preflight
    assert 'LiveKit' in preflight
    assert 'df -Pk' in preflight
    assert 'flask' in preflight
