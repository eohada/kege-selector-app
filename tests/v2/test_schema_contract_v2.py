import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models import db
from app.utils.schema_contract import schema_contract_report


def test_schema_audit_accepts_complete_mapped_schema(app):
    with app.app_context():
        report = schema_contract_report(app)
        assert report['ok'] is True
        assert report['issues'] == []


def test_schema_audit_detects_missing_teacher_student_table(app):
    with app.app_context():
        db.session.execute(text('DROP TABLE teacher_students'))
        db.session.commit()

        report = schema_contract_report(app)
        assert {'kind': 'table', 'table': 'teacher_students', 'name': 'teacher_students'} in report['issues']


def test_profile_onboarding_migration_is_safe_after_schema_bootstrap():
    """The schema bootstrap may have created this newer column already."""
    project_root = Path(__file__).resolve().parents[2]
    migration_path = project_root / 'migrations' / 'versions' / 'f8c9d0e1f2a3_profile_onboarding_state.py'
    spec = importlib.util.spec_from_file_location('profile_onboarding_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE "UserProfiles" '
            '(id INTEGER PRIMARY KEY, profile_onboarding_completed_at DATETIME)'
        ))
        connection.execute(text(
            'CREATE INDEX ix_UserProfiles_profile_onboarding_completed_at '
            'ON "UserProfiles" (profile_onboarding_completed_at)'
        ))
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        migration.upgrade()

        columns = {item['name'] for item in sa.inspect(connection).get_columns('UserProfiles')}
        index_names = {item['name'] for item in sa.inspect(connection).get_indexes('UserProfiles')}

    assert 'profile_onboarding_completed_at' in columns
    assert 'ix_UserProfiles_profile_onboarding_completed_at' in index_names


def test_schema_bootstrap_then_onboarding_migration_on_empty_database(app):
    """A fresh recovery path must not fail after bootstrap created current columns."""
    project_root = Path(__file__).resolve().parents[2]

    def load_migration(filename, module_name):
        spec = importlib.util.spec_from_file_location(
            module_name,
            project_root / 'migrations' / 'versions' / filename,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    bootstrap = load_migration('f7b8c9d0e1f2_schema_contract_bootstrap.py', 'schema_bootstrap_migration')
    onboarding = load_migration('f8c9d0e1f2a3_profile_onboarding_state.py', 'profile_onboarding_migration_after_bootstrap')
    promo_usage = load_migration('f9d0e1f2a3b4_promocode_usage_unique.py', 'promocode_usage_migration_after_bootstrap')
    referral_usage = load_migration('fa0b1c2d3e4f_referral_usage_unique.py', 'referral_usage_migration_after_bootstrap')
    engine = sa.create_engine('sqlite://')

    with app.app_context(), engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        bootstrap.op = operations
        onboarding.op = operations
        promo_usage.op = operations
        referral_usage.op = operations

        bootstrap.upgrade()
        onboarding.upgrade()
        promo_usage.upgrade()
        referral_usage.upgrade()

        columns = {item['name'] for item in sa.inspect(connection).get_columns('UserProfiles')}
        promo_constraints = {
            item['name'] for item in sa.inspect(connection).get_unique_constraints('PromoCodeUsage') if item.get('name')
        }
        referral_constraints = {
            item['name'] for item in sa.inspect(connection).get_unique_constraints('ReferralUsage') if item.get('name')
        }

    assert 'profile_onboarding_completed_at' in columns
    assert 'uq_promocode_usage_per_user' in promo_constraints
    assert 'uq_referral_usage_per_user' in referral_constraints
