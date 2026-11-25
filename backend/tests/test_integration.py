"""Acceptance evidence across real storage and fresh HTTP client sessions."""
from datetime import datetime, timezone
from pathlib import Path
import os
import socket
import subprocess
import sys
import time

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from campus_backend.app import create_app
from campus_backend.core.config import Settings


def choice(client):
    school = client.get('/v1/catalog/schools', params={'prefix': '中'}).json()['items'][0]
    colleges = client.get(f'/v1/catalog/schools/{school["id"]}/colleges').json()['items']
    college = next(x for x in colleges if x['name'] == '计算机学院')
    majors = client.get(f'/v1/catalog/schools/{school["id"]}/colleges/{college["id"]}/majors').json()['items']
    return {'school_id': school['id'], 'college_id': college['id'], 'major_id': majors[0]['id'], 'grade': 1, 'expected_version': 0}


def test_clean_migration_is_repeatable_and_seed_complete(tmp_path):
    from campus_backend.database import initialize_database
    from campus_backend.core.db import build_engine
    settings = Settings(database_url=f'sqlite:///{tmp_path / "db" / "campus.db"}')
    initialize_database(settings)
    initialize_database(settings)
    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        assert connection.scalar(text('select count(*) from catalog_schools')) == 1
        assert connection.scalar(text('select count(*) from catalog_colleges')) == 31
        assert connection.scalar(text('select count(*) from catalog_majors')) == 101
        assert connection.scalar(text('select version_num from alembic_version')) == '0006_notice_follows'
        assert {'auth_sessions', 'student_preferences', 'preferences_idempotency'} <= set(
            inspect(connection).get_table_names()
        )
    engine.dispose()


def test_fresh_app_and_other_client_recover_same_profile(app, client):
    body = {'email': 'restart@example.com', 'password': 'test-password-strong'}
    auth = client.post('/v1/auth/register', json=body).json()
    cookie = client.cookies.get('campus_session')
    response = client.patch('/v1/me/profile', json={**choice(client), 'education_stage': 'undergraduate', 'admission_year': 2026},
                            headers={'X-CSRF-Token': auth['csrf_token'], 'Idempotency-Key': 'integration-save-1'})
    assert response.status_code == 200, response.text
    expected = response.json()
    assert expected['profile']['education_stage'] == 'undergraduate'
    assert expected['profile']['admission_year'] == 2026
    with TestClient(create_app(app.state.settings)) as restarted:
        restarted.cookies.set('campus_session', cookie)
        assert restarted.get('/v1/auth/session').status_code == 200
        assert restarted.get('/v1/me/profile').json()['profile'] == expected['profile']
    with TestClient(create_app(app.state.settings)) as other:
        assert other.get('/v1/me/profile').status_code == 401
        assert other.post('/v1/auth/login', json=body).status_code == 200
        assert other.get('/v1/me/profile').json()['profile'] == expected['profile']


def test_real_server_process_restart_preserves_cookie_profile_and_preference_replay(tmp_path):
    """Real TCP and new process; deliberately NOT a browser-close test."""
    from campus_backend.database import initialize_database
    settings = Settings(database_url=f'sqlite:///{tmp_path / "process.db"}', cookie_secure=False)
    initialize_database(settings)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, CAMPUS_DATABASE_URL=settings.database_url, PYTHONPATH=str(root / 'src'), PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-m', 'campus_backend', 'serve', '--dev', '--port', str(port)]
    url = f'http://127.0.0.1:{port}'
    log = open(tmp_path / 'server.log', 'w+')

    def start():
        process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=log)
        for _ in range(120):
            if process.poll() is not None:
                log.seek(0)
                raise AssertionError(log.read())
            try:
                if httpx.get(url + '/health/live', timeout=.3, trust_env=False).status_code == 200:
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        process.terminate()
        process.wait(timeout=5)
        raise AssertionError('Server did not become ready')

    process = start()
    try:
        with httpx.Client(base_url=url, trust_env=False) as client:
            auth = client.post('/v1/auth/register', json={'email': 'process@example.com', 'password': 'restart-password'}).json()
            response = client.patch('/v1/me/profile', json=choice(client), headers={'X-CSRF-Token': auth['csrf_token'], 'Idempotency-Key': 'process-save-1'})
            assert response.status_code == 200, response.text
            profile = response.json()['profile']
            token = client.cookies.get('campus_session')
            preference_body = {'course_ids': [], 'skill_ids': ['skill_python'], 'goal_ids': [],
                               'interest_ids': [], 'expected_version': 0}
            preference_headers = {'X-CSRF-Token': auth['csrf_token'], 'Idempotency-Key': 'process-preference-1'}
            first = client.patch('/v1/me/preferences', json=preference_body, headers=preference_headers)
            assert first.status_code == 200, first.text
            second = client.patch('/v1/me/preferences', json={**preference_body, 'skill_ids': [], 'expected_version': 1},
                                  headers={**preference_headers, 'Idempotency-Key': 'process-preference-2'})
            assert second.status_code == 200, second.text
        process.terminate()
        process.wait(timeout=5)
        process = start()
        with httpx.Client(base_url=url, cookies={'campus_session': token}, trust_env=False) as resumed:
            assert resumed.get('/v1/auth/session').json()['expires_at'] == auth['expires_at']
            assert resumed.get('/v1/me/profile').json()['profile'] == profile
            assert resumed.get('/v1/me/preferences').json() == second.json()
            replayed = resumed.patch('/v1/me/preferences', json=preference_body, headers=preference_headers)
            assert replayed.status_code == 200, replayed.text
            assert replayed.json() == first.json()
            assert resumed.get('/v1/me/preferences').json() == second.json()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        log.close()
