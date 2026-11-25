"""SQLAlchemy implementation of the authentication storage contract."""
from dataclasses import asdict

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from campus_backend.core.persistence import storage_errors, write_transaction
from ..ports import AuthenticatedSession, RateLimitCharge, SessionRecord, UserRecord
from .models import AuthRateLimit, AuthSession, User


class _RateLimited(Exception):
    """Abort the entire counter transaction without exposing persistence details."""


def _user_record(user: User) -> UserRecord:
    return UserRecord(user.id, user.email, user.password_hash, user.created_at)


def _session_record(session: AuthSession) -> SessionRecord:
    return SessionRecord(session.id, session.user_id, session.token_digest, session.csrf_token,
                         session.created_at, session.expires_at, session.revoked_at)


class SQLAlchemyAuthStore:
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with storage_errors():
            user = self.db.scalar(select(User).where(User.email == email))
            return _user_record(user) if user else None

    def get_session_by_digest(self, token_digest: str) -> AuthenticatedSession | None:
        with storage_errors():
            row = self.db.execute(select(AuthSession, User).join(User, User.id == AuthSession.user_id)
                                  .where(AuthSession.token_digest == token_digest)).one_or_none()
            return AuthenticatedSession(_session_record(row[0]), _user_record(row[1])) if row else None

    def charge_attempts(self, charges: tuple[RateLimitCharge, ...], now: int) -> bool:
        try:
            with write_transaction(self.db):
                self.db.execute(delete(AuthRateLimit).where(AuthRateLimit.window_expires_at <= now))
                for charge in charges:
                    statement = insert(AuthRateLimit).values(
                        key=charge.key, attempts=1, window_expires_at=charge.window_expires_at,
                    ).on_conflict_do_update(
                        index_elements=[AuthRateLimit.key],
                        set_={"attempts": AuthRateLimit.attempts + 1},
                        where=AuthRateLimit.attempts < charge.limit,
                    ).returning(AuthRateLimit.key)
                    if self.db.execute(statement).scalar_one_or_none() is None:
                        raise _RateLimited()
        except _RateLimited:
            return False
        return True

    def create_account_with_session(self, user: UserRecord, session: SessionRecord) -> bool:
        with write_transaction(self.db):
            if self.db.scalar(select(User.id).where(User.email == user.email)) is not None:
                return False
            self.db.add(User(**asdict(user)))
            self.db.flush()
            self.db.add(AuthSession(**asdict(session)))
        return True

    def create_session_if_password_matches(
        self, user_id: str, expected_hash: str, session: SessionRecord,
    ) -> bool:
        with write_transaction(self.db):
            unchanged = self.db.execute(
                update(User).where(User.id == user_id, User.password_hash == expected_hash)
                .values(password_hash=User.password_hash)
            ).rowcount
            if unchanged != 1:
                return False
            self.db.add(AuthSession(**asdict(session)))
        return True

    def change_password_and_revoke_sessions(self, user_id: str, new_hash: str, revoked_at: int) -> bool:
        with write_transaction(self.db):
            updated = self.db.execute(update(User).where(User.id == user_id).values(password_hash=new_hash)).rowcount
            if updated != 1:
                return False
            self.db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                            .values(revoked_at=revoked_at))
        return True

    def revoke_session(self, session_id: str, revoked_at: int) -> None:
        with write_transaction(self.db):
            self.db.execute(update(AuthSession).where(AuthSession.id == session_id).values(revoked_at=revoked_at))
