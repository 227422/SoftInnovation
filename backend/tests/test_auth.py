from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select


NOW = datetime.now(timezone.utc).replace(microsecond=0)
PASSWORD = "correct horse battery staple"


def register(client, email="student@example.com", password=PASSWORD):
    return client.post("/v1/auth/register", json={"email": email, "password": password})


def login(client, email="student@example.com", password=PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def test_register_hashes_password_and_issues_persistent_opaque_cookie(app, client, db):
    from campus_backend.auth.models import AuthSession, User

    app.state.clock = lambda: NOW
    result = register(client, "  Student@Example.COM  ")
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["user"]["email"] == "student@example.com"
    assert body["expires_at"] == int(NOW.timestamp()) + 2592000
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Max-Age=2592000" in cookie and "expires=" in cookie.lower()
    assert "Path=/" in cookie
    assert "password" not in result.text
    user = db.scalar(select(User))
    session = db.scalar(select(AuthSession))
    raw_token = client.cookies.get(app.state.settings.cookie_name)
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert session.token_digest != raw_token
    assert raw_token not in repr(session.__dict__)
    assert session.user_id == body["user"]["id"]
    assert len(body["csrf_token"]) >= 32
    assert client.get("/v1/auth/session").json() == body


def test_login_normalizes_email_and_rejects_wrong_and_unknown_identically(client):
    assert register(client).status_code == 201
    wrong = login(client, password="wrong password")
    unknown = login(client, email="unknown@example.com", password="wrong password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert login(client, email="  STUDENT@example.COM ").status_code == 200
    assert register(client, "STUDENT@EXAMPLE.COM").status_code == 409


def test_fixed_expiry_refresh_requires_csrf_and_never_slides(app, client):
    app.state.clock = lambda: NOW
    created = register(client).json()
    app.state.clock = lambda: NOW + timedelta(days=29, hours=23, minutes=59, seconds=59)
    assert client.get("/v1/auth/session").json()["expires_at"] == created["expires_at"]
    assert client.post("/v1/auth/refresh").status_code == 403
    refreshed = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": created["csrf_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["expires_at"] == created["expires_at"]
    if "set-cookie" in refreshed.headers:
        assert "Max-Age=1" in refreshed.headers["set-cookie"]
    app.state.clock = lambda: NOW + timedelta(days=30)
    assert client.get("/v1/auth/session").status_code == 401
    assert client.post("/v1/auth/refresh", headers={"X-CSRF-Token": created["csrf_token"]}).status_code == 401
    renewed = login(client)
    assert renewed.status_code == 200
    assert renewed.json()["expires_at"] == int(NOW.timestamp()) + 5184000


def test_logout_revokes_only_current_session_and_requires_its_csrf(app, client):
    first = register(client).json()
    first_token = client.cookies.get(app.state.settings.cookie_name)
    with TestClient(app) as other:
        second = login(other).json()
        assert client.post("/v1/auth/logout").status_code == 403
        assert client.post("/v1/auth/logout", headers={"X-CSRF-Token": second["csrf_token"]}).status_code == 403
        result = client.post("/v1/auth/logout", headers={"X-CSRF-Token": first["csrf_token"]})
        assert result.status_code == 204
        assert "Max-Age=0" in result.headers["set-cookie"]
        assert client.get("/v1/auth/session").status_code == 401
        client.cookies.set(app.state.settings.cookie_name, first_token)
        assert client.get("/v1/auth/session").status_code == 401
        assert other.get("/v1/auth/session").status_code == 200


def test_auth_validation_does_not_leak_password(client):
    for payload in [
        {"email": "bad", "password": PASSWORD},
        {"email": "student@example.com", "password": "short!"},
        {"email": "student@example.com", "password": "S" * 129},
    ]:
        response = client.post("/v1/auth/register", json=payload)
        assert response.status_code == 422
        assert payload["password"] not in response.text
    assert client.get("/v1/auth/session").status_code == 401


def test_login_throttle_persists_across_clients_and_expires(app, client):
    app.state.clock = lambda: NOW
    assert register(client).status_code == 201
    for _ in range(10):
        assert login(client, password="wrong password").status_code == 401
    with TestClient(app) as other:
        assert login(other, password="wrong password").status_code == 429
    app.state.clock = lambda: NOW + timedelta(minutes=15)
    assert login(client).status_code == 200


def test_production_cookie_has_secure_attribute(app, client):
    from dataclasses import replace

    app.state.settings = replace(app.state.settings, cookie_secure=True)
    response = register(client)
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]


def test_equal_passwords_have_distinct_salted_hashes(client, db):
    from campus_backend.auth.models import User

    assert register(client, "one@example.com").status_code == 201
    assert register(client, "two@example.com").status_code == 201
    hashes = list(db.scalars(select(User.password_hash)))
    assert len(hashes) == 2 and hashes[0] != hashes[1]


def test_password_change_boundary_revokes_all_sessions_preserving_account(app, client, db):
    from campus_backend.auth.service import change_password_and_revoke_sessions
    from campus_backend.auth.persistence.repository import SQLAlchemyAuthStore

    account = register(client).json()["user"]
    with TestClient(app) as other:
        assert login(other).status_code == 200
        change_password_and_revoke_sessions(SQLAlchemyAuthStore(db), account["id"], "new correct password", NOW)
        assert client.get("/v1/auth/session").status_code == 401
        assert other.get("/v1/auth/session").status_code == 401
        assert login(client).status_code == 401
        result = login(client, password="new correct password")
        assert result.status_code == 200
        assert result.json()["user"] == account


def test_client_ip_throttle_covers_attempts_against_many_accounts(app, client):
    app.state.clock = lambda: NOW
    for number in range(60):
        result = login(client, email=f"unknown{number}@example.com", password="wrong password")
        assert result.status_code == 401
    result = login(client, email="another-unknown@example.com", password="wrong password")
    assert result.status_code == 429


def test_concurrent_login_attempts_cannot_bypass_email_throttle(app):
    from concurrent.futures import ThreadPoolExecutor

    app.state.clock = lambda: NOW

    def attempt(_):
        with TestClient(app) as independent:
            return login(independent, email="unknown@example.com", password="wrong password").status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(attempt, range(14)))
    assert statuses.count(401) == 10
    assert statuses.count(429) == 4


def test_stale_password_verification_cannot_create_session_after_credential_change(app, client, monkeypatch):
    from campus_backend.auth import service
    from campus_backend.auth.persistence.repository import SQLAlchemyAuthStore

    account = register(client).json()["user"]
    original_verify = service.password_hash.verify

    def verify_then_change(password, hashed):
        verified = original_verify(password, hashed)
        with app.state.session_factory() as other_db:
            service.change_password_and_revoke_sessions(SQLAlchemyAuthStore(other_db), account["id"], "new correct password", NOW)
        return verified

    monkeypatch.setattr(service.password_hash, "verify", verify_then_change)
    result = login(client)
    assert result.status_code == 401
    assert client.get("/v1/auth/session").status_code == 401


def test_auth_account_and_session_roll_back_together_but_attempts_remain_charged(client, db):
    from sqlalchemy import func, text
    from campus_backend.auth.models import AuthRateLimit, AuthSession, User

    db.execute(text("CREATE TRIGGER reject_session BEFORE INSERT ON auth_sessions "
                    "BEGIN SELECT RAISE(ABORT, 'injected session insert failure'); END"))
    db.commit()
    response = register(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "injected" not in response.text
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert list(db.scalars(select(AuthRateLimit.attempts))) == [1, 1]


def test_auth_password_and_all_session_revocations_roll_back_together(app, client, db):
    from sqlalchemy import text
    import pytest
    from campus_backend.auth.models import AuthSession, User
    from campus_backend.auth.persistence.repository import SQLAlchemyAuthStore
    from campus_backend.auth.service import change_password_and_revoke_sessions
    from campus_backend.core.storage import StorageConflict

    account = register(client).json()["user"]
    assert login(client).status_code == 200
    original_hash = db.scalar(select(User.password_hash).where(User.id == account["id"]))
    db.execute(text("CREATE TRIGGER reject_revocation BEFORE UPDATE ON auth_sessions "
                    "BEGIN SELECT RAISE(ABORT, 'injected revocation failure'); END"))
    db.commit()
    with pytest.raises(StorageConflict):
        change_password_and_revoke_sessions(SQLAlchemyAuthStore(db), account["id"], "new correct password", NOW)
    assert db.scalar(select(User.password_hash).where(User.id == account["id"])) == original_hash
    sessions = list(db.scalars(select(AuthSession)))
    assert len(sessions) == 2
    assert all(session.revoked_at is None for session in sessions)
    assert client.get("/v1/auth/session").status_code == 200


def test_email_and_ip_throttle_counters_roll_back_together(db):
    import pytest
    from campus_backend.auth.models import AuthRateLimit
    from campus_backend.auth.persistence.repository import SQLAlchemyAuthStore
    from campus_backend.auth.service import charge_attempt, digest_token
    from campus_backend.core.errors import AppError

    timestamp = int(NOW.timestamp())
    ip_key = digest_token("login:ip:127.0.0.1")
    email_key = digest_token("login:email:new@example.com")
    db.add(AuthRateLimit(key=ip_key, attempts=60, window_expires_at=timestamp + 900))
    db.commit()
    with pytest.raises(AppError) as limited:
        charge_attempt(SQLAlchemyAuthStore(db), "login", "new@example.com", "127.0.0.1", NOW)
    assert limited.value.status_code == 429
    assert db.get(AuthRateLimit, email_key) is None
    assert db.get(AuthRateLimit, ip_key).attempts == 60
