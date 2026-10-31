import logging
from logging.config import fileConfig

from flask import current_app
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


def get_engine():
    try:
        return current_app.extensions['migrate'].db.get_engine()
    except (TypeError, AttributeError):
        return current_app.extensions['migrate'].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace('%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


config.set_main_option('sqlalchemy.url', get_engine_url())
target_db = current_app.extensions['migrate'].db


def get_metadata():
    if hasattr(target_db, 'metadatas'):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


from sqlalchemy import text, Table, MetaData, Column, String, PrimaryKeyConstraint
from alembic.ddl.impl import DefaultImpl

# Ensure Alembic handles revision IDs up to 128 characters
def _patched_version_table_impl(self, *, version_table, version_table_schema, version_table_pk, **kw):
    vt = Table(
        version_table,
        MetaData(),
        Column("version_num", String(128), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        vt.append_constraint(PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
    return vt

DefaultImpl.version_table_impl = _patched_version_table_impl


def run_migrations_online():
    """Run migrations in 'online' mode."""
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    connectable = get_engine()

    with connectable.connect() as connection:
        if connection.dialect.name == 'postgresql':
            try:
                with connection.begin():
                    connection.execute(text("""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns 
                                WHERE table_name = 'alembic_version' 
                                  AND column_name = 'version_num' 
                                  AND (character_maximum_length IS NULL OR character_maximum_length < 128)
                            ) THEN
                                ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128);
                            END IF;
                        END $$;
                    """))
            except Exception as e:
                logger.warning("Pre-migration: could not alter alembic_version column: %s", e)

        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            process_revision_directives=process_revision_directives,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
