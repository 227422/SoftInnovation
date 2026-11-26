"""Authentication rules depend only on plain storage contracts."""
from datetime import datetime
import hashlib
import secrets
from uuid import uuid4

from pwdlib import PasswordHash

from campus_backend.core.errors import AppError
from .ports import AuthStore, Principal, RateLimitCharge, SessionRecord, UserRecord


SESSION_SECONDS = 30 * 24 * 60 * 60
THROTTLE_SECONDS = 15 * 60
password_hash = PasswordHash.recommended()
# An unknown account still incurs the same Argon2 verification work.
_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def charge_attempt(store: AuthStore, action: str, email: str, client_ip: str, now: datetime) -> None:
    timestamp = int(now.timestamp())
    charges = tuple(RateLimitCharge(digest_token(f"{action}:{scope}:{value}"), limit, timestamp + THROTTLE_SECONDS)
                    for scope, value, limit in (("email", email, 10), ("ip", client_ip, 60)))
    if not store.charge_attempts(charges, timestamp):
        raise AppError(429, "auth_rate_limited", "尝试次数过多，请稍后重试")


def _new_session(user_id: str, now: datetime) -> tuple[SessionRecord, str]:
    timestamp = int(now.timestamp())
    raw_token = secrets.token_urlsafe(32)
    session = SessionRecord(
        id=str(uuid4()), user_id=user_id, token_digest=digest_token(raw_token),
        csrf_token=secrets.token_urlsafe(32), created_at=timestamp,
        expires_at=timestamp + SESSION_SECONDS,
    )
    return session, raw_token


def register_account(store: AuthStore, email: str, password: str, now: datetime):
    if store.get_user_by_email(email) is not None:
        raise AppError(409, "email_in_use", "该邮箱已注册，请登录")
    user = UserRecord(id=str(uuid4()), email=email, password_hash=password_hash.hash(password),
                      created_at=int(now.timestamp()))
    session, raw_token = _new_session(user.id, now)
    if not store.create_account_with_session(user, session):
        raise AppError(409, "email_in_use", "该邮箱已注册，请登录")
    return user, session, raw_token


def login_account(store: AuthStore, email: str, password: str, now: datetime):
    user = store.get_user_by_email(email)
    verified = password_hash.verify(password, user.password_hash if user else _dummy_hash)
    if user is None or not verified:
        raise AppError(401, "invalid_credentials", "邮箱或密码不正确，请检查后重试")
    session, raw_token = _new_session(user.id, now)
    if not store.create_session_if_password_matches(user.id, user.password_hash, session):
        raise AppError(401, "invalid_credentials", "邮箱或密码不正确，请检查后重试")
    return user, session, raw_token


def change_password_and_revoke_sessions(store: AuthStore, user_id: str, new_password: str, now: datetime) -> None:
    """Trusted internal boundary; callers must verify ownership/recovery first.

    No HTTP password-recovery or password-update endpoint is exposed in v1.
    Password update and revoking every previous session commit together.
    """
    if not 8 <= len(new_password) <= 128:
        raise AppError(422, "invalid_password", "密码须为8至128个字符")
    if not store.change_password_and_revoke_sessions(user_id, password_hash.hash(new_password), int(now.timestamp())):
        raise AppError(404, "account_not_found", "账号不存在")


def authenticate_session(store: AuthStore, token: str | None, now: datetime) -> Principal:
    if not token or len(token) > 256:
        raise AppError(401, "session_invalid", "请重新登录")
    record = store.get_session_by_digest(digest_token(token))
    if record is None or record.session.revoked_at is not None or int(now.timestamp()) >= record.session.expires_at:
        raise AppError(401, "session_invalid", "请重新登录")
    return Principal(record.user.id, record.user.email, record.session.id,
                     record.session.expires_at, record.session.csrf_token)


def logout_session(store: AuthStore, session_id: str, now: datetime) -> None:
    store.revoke_session(session_id, int(now.timestamp()))
