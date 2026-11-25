"""SQLAlchemy persistence; no mapped objects escape this adapter."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, fields
from typing import Iterator

from sqlalchemy import update
from sqlalchemy.orm import Session

from campus_backend.catalog.persistence.repository import SQLAlchemyCatalogStore
from campus_backend.core.persistence import storage_errors, write_transaction

from ..ports import IdempotencyRecord, ProfileRecord, ProfileTransaction
from .models import ProfileIdempotency, StudentProfile


def _profile_record(row: StudentProfile | None) -> ProfileRecord | None:
    if row is None:
        return None
    return ProfileRecord(**{field.name: getattr(row, field.name) for field in fields(ProfileRecord)})


class _SQLAlchemyProfileTransaction:
    def __init__(self, db: Session):
        self.db = db
        self.catalog = SQLAlchemyCatalogStore(db)

    def get_idempotency(self, user_id: str, key: str) -> IdempotencyRecord | None:
        return _idempotency_record(self.db, user_id, key)

    def get_profile(self, user_id: str) -> ProfileRecord | None:
        return _profile_record(self.db.get(StudentProfile, user_id))

    def save_profile(self, user_id: str, profile: ProfileRecord, expected_version: int) -> bool:
        values = asdict(profile)
        if expected_version == 0:
            self.db.add(StudentProfile(user_id=user_id, **values))
            self.db.flush()
            return True
        changed = self.db.execute(update(StudentProfile).where(
            StudentProfile.user_id == user_id,
            StudentProfile.version == expected_version,
        ).values(**values).execution_options(synchronize_session=False))
        return changed.rowcount == 1

    def add_idempotency(self, user_id: str, key: str, request_hash: str, result: dict) -> None:
        self.db.add(ProfileIdempotency(user_id=user_id, key=key, request_hash=request_hash,
                                       result=deepcopy(result)))
        self.db.flush()


def _idempotency_record(db: Session, user_id: str, key: str) -> IdempotencyRecord | None:
    row = db.get(ProfileIdempotency, (user_id, key))
    if row is None:
        return None
    return IdempotencyRecord(request_hash=row.request_hash, result=deepcopy(row.result))


class SQLAlchemyProfileStore:
    def __init__(self, db: Session):
        self.db = db

    def get_profile(self, user_id: str) -> ProfileRecord | None:
        with storage_errors():
            return _profile_record(self.db.get(StudentProfile, user_id))

    def get_idempotency(self, user_id: str, key: str) -> IdempotencyRecord | None:
        with storage_errors():
            return _idempotency_record(self.db, user_id, key)

    @contextmanager
    def transaction(self) -> Iterator[ProfileTransaction]:
        # This starts before replay and selection reads. In particular catalog
        # disabling cannot commit between selection validation and this save.
        with write_transaction(self.db):
            yield _SQLAlchemyProfileTransaction(self.db)
