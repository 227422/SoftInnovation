"""Explicit schema upgrade/seed management, never triggered on API import."""
from alembic import command
from alembic.config import Config

from .core.config import BACKEND_ROOT, Settings
from .core.db import build_engine, ensure_database_directory, make_session_factory
from .catalog.persistence.seed import seed_catalog


def migration_config(settings: Settings) -> Config:
    config = Config()
    config.set_main_option('script_location', str(BACKEND_ROOT / 'migrations'))
    config.set_main_option('sqlalchemy.url', settings.database_url.replace('%', '%%'))
    return config


def initialize_database(settings: Settings, *, seed: bool = True) -> None:
    ensure_database_directory(settings.database_url)
    engine = build_engine(settings.database_url)
    try:
        config = migration_config(settings)
        with engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        if seed:
            with make_session_factory(engine)() as session:
                seed_catalog(session)
    finally:
        engine.dispose()
