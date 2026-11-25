from alembic import context
from sqlalchemy import engine_from_config, pool
from campus_backend.core.config import require_file_sqlite_url
from campus_backend.metadata import metadata

config = context.config


def run_with_connection(connection):
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    url = require_file_sqlite_url(config.get_main_option('sqlalchemy.url'))
    context.configure(url=url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif connection := config.attributes.get('connection'):
    run_with_connection(connection)
else:
    require_file_sqlite_url(config.get_main_option('sqlalchemy.url'))
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix='sqlalchemy.', poolclass=pool.NullPool)
    with engine.connect() as connection:
        run_with_connection(connection)
    engine.dispose()
