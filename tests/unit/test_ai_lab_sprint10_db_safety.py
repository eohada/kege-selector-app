from app import _should_skip_database_bootstrap, create_app


def test_maintenance_cli_skips_startup_database_bootstrap():
    safe_environment = {'FLASK_RUN_FROM_CLI': 'true'}

    assert _should_skip_database_bootstrap(
        {}, argv=['db', 'heads'], environ=safe_environment
    )
    assert not _should_skip_database_bootstrap(
        {}, argv=['run'], environ=safe_environment
    )


def test_test_app_creation_does_not_create_database_or_bootstrap_rows(tmp_path):
    database_path = tmp_path / 'isolated-test.sqlite'
    app = create_app({
        'TESTING': True,
        'SKIP_DATABASE_BOOTSTRAP': True,
        'SECRET_KEY': 'sprint10-isolated-test',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path.as_posix()}',
    })

    assert app.config['SKIP_DATABASE_BOOTSTRAP'] is True
    assert not database_path.exists()
