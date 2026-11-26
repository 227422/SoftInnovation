"""Business rules run against a plain in-memory port, without a database."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from campus_backend.auth import service
from campus_backend.core.errors import AppError

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
PASSWORD = "correct horse battery staple"


class MemoryAuthStore:
    def __init__(self):
        self.users = {}
        self.sessions = {}
        self.reject_verified_password = False
        self.rate_limits_allowed = True
        self.charges = ()

    def get_user_by_email(self, email):
        return next((user for user in self.users.values() if user.email == email), None)

    def create_account_with_session(self, user, session):
        if self.get_user_by_email(user.email):
            return False
        self.users[user.id] = user
        self.sessions[session.id] = session
        return True

    def create_session_if_password_matches(self, user_id, expected_hash, session):
        if self.reject_verified_password or self.users[user_id].password_hash != expected_hash:
            return False
        self.sessions[session.id] = session
        return True

    def change_password_and_revoke_sessions(self, user_id, new_hash, revoked_at):
        if user_id not in self.users:
            return False
        self.users[user_id] = replace(self.users[user_id], password_hash=new_hash)
        self.sessions = {key: replace(value, revoked_at=revoked_at) if value.user_id == user_id
                         and value.revoked_at is None else value for key, value in self.sessions.items()}
        return True

    def charge_attempts(self, charges, now):
        self.charges = charges
        return self.rate_limits_allowed

    def get_session_by_digest(self, token_digest):
        from campus_backend.auth.ports import AuthenticatedSession
        session = next((s for s in self.sessions.values() if s.token_digest == token_digest), None)
        return AuthenticatedSession(session, self.users[session.user_id]) if session else None

    def revoke_session(self, session_id, revoked_at):
        self.sessions[session_id] = replace(self.sessions[session_id], revoked_at=revoked_at)


def test_register_uses_plain_store_and_fixed_expiry():
    store = MemoryAuthStore()
    user, session, token = service.register_account(store, "student@example.com", PASSWORD, NOW)
    assert session.user_id == user.id
    assert session.expires_at == int(NOW.timestamp()) + 2592000
    assert session.token_digest == service.digest_token(token)
    assert user.password_hash != PASSWORD
    assert service.password_hash.verify(PASSWORD, user.password_hash)
    assert store.sessions[session.id] == session
    with pytest.raises(AppError) as duplicate:
        service.register_account(store, user.email, PASSWORD, NOW)
    assert duplicate.value.code == "email_in_use"


def test_verified_password_must_still_match_before_session_is_written():
    store = MemoryAuthStore()
    user, _, _ = service.register_account(store, "student@example.com", PASSWORD, NOW)
    store.reject_verified_password = True
    with pytest.raises(AppError) as rejected:
        service.login_account(store, user.email, PASSWORD, NOW)
    assert rejected.value.code == "invalid_credentials"
    assert len(store.sessions) == 1


def test_internal_password_change_validates_then_revokes_all_sessions():
    store = MemoryAuthStore()
    user, _, _ = service.register_account(store, "student@example.com", PASSWORD, NOW)
    service.login_account(store, user.email, PASSWORD, NOW)
    with pytest.raises(AppError) as invalid:
        service.change_password_and_revoke_sessions(store, user.id, "short", NOW)
    assert invalid.value.code == "invalid_password"
    assert all(session.revoked_at is None for session in store.sessions.values())
    service.change_password_and_revoke_sessions(store, user.id, "new correct password", NOW)
    assert all(session.revoked_at == int(NOW.timestamp()) for session in store.sessions.values())
    with pytest.raises(AppError):
        service.login_account(store, user.email, PASSWORD, NOW)
    assert service.login_account(store, user.email, "new correct password", NOW)[0].id == user.id


def test_session_expiry_is_fixed_and_revocation_is_enforced():
    store = MemoryAuthStore()
    user, session, token = service.register_account(store, "student@example.com", PASSWORD, NOW)
    principal = service.authenticate_session(store, token, NOW)
    assert principal.user_id == user.id
    assert principal.expires_at == session.expires_at
    expires = datetime.fromtimestamp(session.expires_at, timezone.utc)
    with pytest.raises(AppError) as expired:
        service.authenticate_session(store, token, expires)
    assert expired.value.code == "session_invalid"
    service.logout_session(store, session.id, NOW)
    with pytest.raises(AppError):
        service.authenticate_session(store, token, NOW)


def test_throttle_business_limits_and_redacted_keys():
    store = MemoryAuthStore()
    service.charge_attempt(store, "login", "student@example.com", "127.0.0.1", NOW)
    assert [charge.limit for charge in store.charges] == [10, 60]
    assert all(charge.window_expires_at == int(NOW.timestamp()) + 900 for charge in store.charges)
    assert "student@example.com" not in repr(store.charges)
    assert "127.0.0.1" not in repr(store.charges)
    store.rate_limits_allowed = False
    with pytest.raises(AppError) as limited:
        service.charge_attempt(store, "login", "student@example.com", "127.0.0.1", NOW)
    assert limited.value.status_code == 429
