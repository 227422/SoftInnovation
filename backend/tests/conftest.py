from datetime import datetime, timezone
from importlib import import_module
from importlib.util import find_spec

import pytest
from fastapi.testclient import TestClient

from campus_backend.app import create_app
from campus_backend.core.config import Settings
from campus_backend.core.db import Base


@pytest.fixture
def app(tmp_path):
    for feature in ('auth', 'catalog', 'profile'):
        name = f'campus_backend.{feature}'
        if find_spec(name) and find_spec(f'{name}.models'):
            import_module(f'{name}.models')
    application = create_app(Settings(database_url=f'sqlite:///{tmp_path / "test.db"}', cookie_secure=False),
                             clock=lambda: datetime.now(timezone.utc).replace(microsecond=0))
    Base.metadata.create_all(application.state.engine)
    if find_spec('campus_backend.catalog') and find_spec('campus_backend.catalog.seed'):
        with application.state.session_factory() as session:
            import_module('campus_backend.catalog.seed').seed_catalog(session)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db(app):
    with app.state.session_factory() as session:
        yield session
