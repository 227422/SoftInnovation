"""Store preference selections and their replay outcomes in one transaction."""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from campus_backend.core.persistence import storage_errors, write_transaction

from ..ports import PreferenceReplay, PreferencesTransaction
from ..schemas import PreferencesView
from .models import PreferencesIdempotency, StudentPreferences


class _SQLAlchemyPreferencesTransaction:
    def __init__(self, db: Session):
        self.db = db

    def get_replay(self, user_id: str, key: str) -> PreferenceReplay | None:
        row = self.db.get(PreferencesIdempotency, (user_id, key))
        if row is None:
            return None
        return PreferenceReplay(row.request_hash, PreferencesView.model_validate(row.result))

    def save_preferences(self, user_id: str, snapshot: PreferencesView, expected_version: int) -> bool:
        current = self.db.get(StudentPreferences, user_id)
        actual_version = current.version if current is not None else 0
        if actual_version != expected_version:
            return False
        values = snapshot.model_dump()
        if current is None:
            self.db.add(StudentPreferences(user_id=user_id, **values))
        else:
            for field, value in values.items():
                setattr(current, field, value)
        self.db.flush()
        return True

    def add_replay(self, user_id: str, key: str, replay: PreferenceReplay) -> None:
        self.db.add(PreferencesIdempotency(user_id=user_id, key=key, request_hash=replay.request_hash,
                                           result=replay.result.model_dump()))


class SQLAlchemyPreferencesStore:
    def __init__(self, db: Session):
        self.db = db

    def get_preferences(self, user_id: str) -> PreferencesView | None:
        with storage_errors():
            row = self.db.get(StudentPreferences, user_id)
            if row is None:
                return None
            return PreferencesView.model_validate(row, from_attributes=True)

    @contextmanager
    def transaction(self) -> Iterator[PreferencesTransaction]:
        with write_transaction(self.db):
            yield _SQLAlchemyPreferencesTransaction(self.db)
