"""Follow rows keyed by account and notice; version guards concurrent devices."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_backend.core.persistence import storage_errors, write_transaction

from .models import NoticeFollow


def _iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def _view(row):
    return {'notice_id': row.notice_id, 'starred': bool(row.starred),
            'followed_at': _iso(row.followed_at), 'version': row.version}


def empty_view(notice_id, version=0):
    return {'notice_id': notice_id, 'starred': False, 'followed_at': None, 'version': version}


class SQLAlchemyFollowStore:
    def __init__(self, db: Session):
        self.db = db

    def starred(self, user_id: str, notice_ids) -> dict:
        ids = list(dict.fromkeys(notice_ids))
        if not ids:
            return {}
        with storage_errors():
            rows = self.db.scalars(
                select(NoticeFollow).where(NoticeFollow.user_id == user_id, NoticeFollow.notice_id.in_(ids))
            )
            return {row.notice_id: _view(row) for row in rows}

    def starred_ids(self, user_id: str) -> list[str]:
        with storage_errors():
            rows = self.db.scalars(
                select(NoticeFollow).where(
                    NoticeFollow.user_id == user_id, NoticeFollow.starred.is_(True)
                )
            )
            return [row.notice_id for row in rows]

    def set(self, user_id: str, notice_id: str, starred: bool, expected_version, now: float):
        """Returns the new state, or None when expected_version no longer matches."""
        with write_transaction(self.db):
            row = self.db.get(NoticeFollow, (user_id, notice_id))
            current = row.version if row is not None else 0
            if expected_version is not None and int(expected_version) != current:
                return None
            if row is None:
                row = NoticeFollow(user_id=user_id, notice_id=notice_id, starred=starred, version=1,
                                   followed_at=now if starred else None, updated_at=now)
                self.db.add(row)
            else:
                row.starred = starred
                if starred and row.followed_at is None:
                    row.followed_at = now
                row.version = current + 1
                row.updated_at = now
            self.db.flush()
            return _view(row)
