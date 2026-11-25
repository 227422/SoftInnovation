"""Per-request sessions; concrete feature storage adapters own transactions."""
from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import require_file_sqlite_url


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    url = require_file_sqlite_url(database_url)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 10})

    @event.listens_for(engine, 'connect')
    def configure_sqlite(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')

    return engine


def ensure_database_directory(database_url: str):
    filename = require_file_sqlite_url(database_url).database
    Path(filename).resolve().parent.mkdir(parents=True, exist_ok=True)


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
