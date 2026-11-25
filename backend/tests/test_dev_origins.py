"""Development startup must preserve the configured browser access boundary."""

import pytest
from fastapi.testclient import TestClient

from campus_backend import cli
from campus_backend.app import create_app
from campus_backend.core.config import Settings


@pytest.fixture
def dev_server(app, monkeypatch):
    monkeypatch.setenv('CAMPUS_DATABASE_URL', app.state.settings.database_url)

    def launch(*, origins=None, port=8000):
        if origins is None:
            monkeypatch.delenv('CAMPUS_ALLOWED_ORIGINS', raising=False)
        else:
            monkeypatch.setenv('CAMPUS_ALLOWED_ORIGINS', origins)
        applications = []
        # Keep actual CLI configuration, app assembly, middleware and storage;
        # replace only the blocking server process with an in-process client.
        monkeypatch.setattr(cli.uvicorn, 'run', lambda application, **kwargs: applications.append(application))
        cli.main(['serve', '--dev', '--port', str(port)])
        return TestClient(applications[0], base_url=f'http://127.0.0.1:{port}')

    return launch


def preflight(client, origin):
    return client.options('/v1/auth/register', headers={
        'Origin': origin,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type',
    })


def test_dev_cli_preserves_custom_origin_preflight(dev_server):
    with dev_server(origins='http://localhost:5173') as client:
        response = preflight(client, 'http://localhost:5173')
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert response.headers['access-control-allow-credentials'] == 'true'


def test_dev_cli_custom_origin_can_register_and_restore_session(dev_server):
    with dev_server(origins='http://localhost:5173') as client:
        response = client.post('/v1/auth/register', json={
            'email': 'browser@example.com', 'password': 'password123',
        }, headers={'Origin': 'http://localhost:5173'})
        assert response.status_code == 201
        assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
        assert client.get('/v1/auth/session').status_code == 200


@pytest.mark.parametrize('origin', [
    'http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::1]:8000',
    'https://untrusted.example',
])
def test_dev_cli_explicit_origins_do_not_gain_default_or_untrusted_origins(dev_server, origin):
    with dev_server(origins='http://localhost:5173') as client:
        assert preflight(client, origin).status_code == 400
        response = client.post('/v1/auth/login', json={
            'email': 'browser@example.com', 'password': 'password123',
        }, headers={'Origin': origin})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'origin_forbidden'


@pytest.mark.parametrize('origins', ['', ' , '])
def test_dev_cli_explicit_empty_origins_reject_browser_writes(dev_server, origins):
    with dev_server(origins=origins) as client:
        assert preflight(client, 'http://localhost:8000').status_code == 400
        response = client.post('/v1/auth/login', json={
            'email': 'browser@example.com', 'password': 'password123',
        }, headers={'Origin': 'http://localhost:8000'})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'origin_forbidden'


@pytest.mark.parametrize('origins', ['', '   ', ' , '])
def test_explicit_empty_origins_also_disable_browser_writes_outside_dev(app, monkeypatch, origins):
    monkeypatch.setenv('CAMPUS_DATABASE_URL', app.state.settings.database_url)
    monkeypatch.setenv('CAMPUS_ALLOWED_ORIGINS', origins)
    with TestClient(create_app(Settings.from_env())) as client:
        assert preflight(client, 'http://localhost:8000').status_code == 400
        response = client.post('/v1/auth/login', json={
            'email': 'browser@example.com', 'password': 'password123',
        }, headers={'Origin': 'http://localhost:8000'})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'origin_forbidden'


@pytest.mark.parametrize('origins', ['http://localhost:5173', ''])
def test_dev_cli_native_requests_without_origin_can_authenticate(dev_server, origins):
    with dev_server(origins=origins) as client:
        response = client.post('/v1/auth/register', json={
            'email': 'native@example.com', 'password': 'password123',
        })
        assert response.status_code == 201
        assert client.get('/v1/auth/session').status_code == 200


@pytest.mark.parametrize(('port', 'origin'), [
    (8000, 'http://127.0.0.1:8000'),
    (8000, 'http://localhost:8000'),
    (8000, 'http://[::1]:8000'),
    (8081, 'http://127.0.0.1:8081'),
    (8081, 'http://localhost:8081'),
    (8081, 'http://[::1]:8081'),
])
def test_dev_cli_unconfigured_origins_follow_actual_server_port(dev_server, port, origin):
    with dev_server(port=port) as client:
        assert preflight(client, origin).status_code == 200
        response = client.post('/v1/auth/login', json={
            'email': 'unknown@example.com', 'password': 'password123',
        }, headers={'Origin': origin})
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'invalid_credentials'


def test_dev_cli_still_rejects_public_binding(app, monkeypatch):
    monkeypatch.setenv('CAMPUS_DATABASE_URL', app.state.settings.database_url)
    monkeypatch.setenv('CAMPUS_ALLOWED_ORIGINS', 'http://localhost:5173')

    def run(*args, **kwargs):
        pytest.fail('Development server must not start on a public interface')

    monkeypatch.setattr(cli.uvicorn, 'run', run)
    with pytest.raises(SystemExit) as error:
        cli.main(['serve', '--dev', '--host', '0.0.0.0'])
    assert error.value.code == 2
