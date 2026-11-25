"""Plain authentication records and semantic, atomic storage operations."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    created_at: int


@dataclass(frozen=True)
class SessionRecord:
    id: str
    user_id: str
    token_digest: str
    csrf_token: str
    created_at: int
    expires_at: int
    revoked_at: int | None = None


@dataclass(frozen=True)
class AuthenticatedSession:
    session: SessionRecord
    user: UserRecord


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    session_id: str
    expires_at: int
    csrf_token: str


@dataclass(frozen=True)
class RateLimitCharge:
    key: str
    limit: int
    window_expires_at: int


class AuthStore(Protocol):
    def get_user_by_email(self, email: str) -> UserRecord | None: ...

    def get_session_by_digest(self, token_digest: str) -> AuthenticatedSession | None: ...

    def charge_attempts(self, charges: tuple[RateLimitCharge, ...], now: int) -> bool:
        """Commit all counters together; return False and change none if limited."""
        ...

    def create_account_with_session(self, user: UserRecord, session: SessionRecord) -> bool:
        """Commit account and session together; False means email already exists."""
        ...

    def create_session_if_password_matches(
        self, user_id: str, expected_hash: str, session: SessionRecord,
    ) -> bool:
        """Atomically check the verified hash and insert; False means stale credentials."""
        ...

    def change_password_and_revoke_sessions(self, user_id: str, new_hash: str, revoked_at: int) -> bool:
        """Commit password and every session revocation together; False means no account."""
        ...

    def revoke_session(self, session_id: str, revoked_at: int) -> None: ...
