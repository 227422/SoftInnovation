import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from campus_backend.core.config import Settings
from campus_backend.core.db import build_engine, ensure_database_directory


@pytest.mark.parametrize("entrypoint", [Settings, build_engine, ensure_database_directory])
@pytest.mark.parametrize("database_url", [
    "",
    "sqlite://",
    "sqlite:///",
    "sqlite:///:memory:",
    "sqlite:///file::memory:?cache=shared&uri=true",
    "sqlite:///file:example?mode=memory&uri=true",
    "sqlite:///file:example?vfs=memdb&uri=true",
    "sqlite:///file%3Aexample.db",
    "sqlite:///ordinary.db?uri=true",
    "sqlite:///ordinary.db?mode=memory",
    "sqlite://localhost/database.db",
    "postgresql://localhost/database",
])
def test_database_entrypoints_require_file_backed_sqlite(entrypoint, database_url, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="file-backed SQLite"):
        entrypoint(database_url)


@pytest.mark.parametrize("database_url", ["", "sqlite:///:memory:"])
def test_explicit_environment_database_url_cannot_fall_back_to_default(database_url, monkeypatch):
    monkeypatch.setenv("CAMPUS_DATABASE_URL", database_url)
    with pytest.raises(ValueError, match="file-backed SQLite"):
        Settings.from_env()


@pytest.mark.parametrize("offline", [False, True])
def test_standalone_alembic_config_requires_file_backed_sqlite(offline):
    from alembic import command
    from alembic.config import Config
    from campus_backend.core.config import BACKEND_ROOT

    config = Config()
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "sqlite:///:memory:")
    with pytest.raises(ValueError, match="file-backed SQLite"):
        command.upgrade(config, "head", sql=offline)


@pytest.mark.parametrize("relative", [False, True])
def test_file_name_with_memory_in_it_creates_a_persistent_database(tmp_path, monkeypatch, relative):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "nested" / "memory.db"
    filename = db_path.relative_to(tmp_path) if relative else db_path
    settings = Settings(database_url=f"sqlite:///{filename}?timeout=5")
    ensure_database_directory(settings.database_url)
    engine = build_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE persistence_test (value TEXT)")
            connection.exec_driver_sql("INSERT INTO persistence_test VALUES ('on disk')")
    finally:
        engine.dispose()
    assert db_path.is_file()
    reopened = build_engine(settings.database_url)
    try:
        with reopened.connect() as connection:
            assert connection.exec_driver_sql("SELECT value FROM persistence_test").scalar_one() == "on disk"
    finally:
        reopened.dispose()


def test_service_starts_without_creating_database(tmp_path):
    from campus_backend.app import create_app
    file = tmp_path / "uninitialized.db"
    app = create_app(Settings(database_url=f"sqlite:///{file}", cookie_secure=False))
    with TestClient(app) as client:
        assert client.get('/health/live').json() == {'status': 'ok'}
    assert not file.exists()


def test_validation_does_not_echo_password_or_input(client, app):
    class Payload(BaseModel):
        password: int

    @app.post('/test-validation')
    def endpoint(body: Payload):
        return {'ok': True}

    response = client.post('/test-validation', json={'password': 'PRIVATE-PASSWORD'})
    assert response.status_code == 422
    assert 'PRIVATE-PASSWORD' not in response.text
    assert response.json()['error']['code'] == 'validation_error'
    assert response.json()['error']['request_id']


def test_database_failure_returns_retryable_error_without_internal_sql(app):
    @app.get('/test-db-error')
    def broken():
        raise OperationalError('SECRET SQL', {}, Exception('private db path'))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test-db-error')
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'storage_unavailable'
    assert 'SECRET' not in response.text and 'private db' not in response.text


def test_cross_origin_write_and_form_auth_are_rejected(client):
    response = client.post('/v1/auth/login', json={'email': 'a@example.com', 'password': 'password123'}, headers={'Origin': 'https://attacker.example'})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'origin_forbidden'
    response = client.post('/v1/auth/login', content='email=a@example.com&password=secret', headers={'Content-Type': 'application/x-www-form-urlencoded'})
    assert response.status_code == 415


def test_no_wildcard_credentials_origin_configuration():
    with pytest.raises(ValueError):
        Settings(allowed_origins=('*',))


def test_streamed_oversized_registration_is_rejected_before_account_creation(client, db):
    from sqlalchemy import func, select
    from campus_backend.auth.models import User
    body = b' ' * 70000 + b'{"email":"stream@example.com","password":"password123"}'
    response = client.post('/v1/auth/register', content=(body[i:i+4096] for i in range(0, len(body), 4096)), headers={'Content-Type': 'application/json'})
    assert response.status_code == 413
    assert response.json()['error']['code'] == 'payload_too_large'
    assert db.scalar(select(func.count()).select_from(User)) == 0


def test_small_streamed_json_still_authenticates(client):
    body = b'{"email":"small@example.com","password":"password123"}'
    response = client.post('/v1/auth/register', content=iter([body[:10], body[10:]]), headers={'Content-Type': 'application/json'})
    assert response.status_code == 201
    assert client.get('/v1/auth/session').status_code == 200


def test_dev_cli_ipv6_origin_can_reach_authentication(app, monkeypatch):
    import sys
    from campus_backend import cli
    monkeypatch.setenv('CAMPUS_DATABASE_URL', app.state.settings.database_url)
    monkeypatch.setattr(sys, 'argv', ['campus-backend', 'serve', '--dev', '--host', '::1', '--port', '8081'])
    results = []

    def run(application, **kwargs):
        with TestClient(application, base_url='http://127.0.0.1:8081') as http:
            response = http.post('/v1/auth/login', json={'email': 'ipv6@example.com', 'password': 'password123'}, headers={'Origin': 'http://[::1]:8081'})
            results.append(response.json()['error']['code'])

    monkeypatch.setattr(cli.uvicorn, 'run', run)
    cli.main()
    assert results == ['invalid_credentials']
