"""Profile business rules work with an in-memory transactional adapter."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from campus_backend.catalog.ports import CollegeRecord, MajorRecord, SchoolRecord
from campus_backend.core.errors import AppError
from campus_backend.core.storage import StorageConflict, StorageError
from campus_backend.profile.schemas import ProfileUpdate
from campus_backend.profile.service import get_profile, save_profile


BASE = dict(school_id="school", college_id="college", major_id="major", grade=2, expected_version=0)


class MemoryProfileStore:
    """Rollback staged state exactly when the transaction fails."""
    def __init__(self):
        self.profiles = {}
        self.replays = {}
        self.active = False
        self.fail_commit = False
        self.catalog = self
        self.major_enabled = True

    def get_profile(self, user_id):
        return self.profiles.get(user_id)

    def get_idempotency(self, user_id, key):
        return self.replays.get((user_id, key))

    def get_school(self, school_id):
        assert self.active, "catalog validation must run inside the write transaction"
        return SchoolRecord(id="school", name="学校") if school_id == "school" else None

    def get_college(self, college_id):
        assert self.active
        return CollegeRecord(id="college", school_id="school", name="学院") if college_id == "college" else None

    def get_major(self, major_id):
        assert self.active
        return MajorRecord(id="major", school_id="school", college_id="college", name="专业", enabled=self.major_enabled) if major_id == "major" else None

    @contextmanager
    def transaction(self):
        assert not self.active
        old = deepcopy((self.profiles, self.replays))
        self.active = True
        try:
            yield self
            if self.fail_commit:
                raise StorageError("simulated commit failure")
        except Exception:
            self.profiles, self.replays = old
            raise
        finally:
            self.active = False

    def save_profile(self, user_id, profile, expected_version):
        assert self.active
        old = self.profiles.get(user_id)
        if expected_version == 0 and old is not None:
            raise StorageConflict("already exists")
        if expected_version and (old is None or old.version != expected_version):
            return False
        self.profiles[user_id] = profile
        return True

    def add_idempotency(self, user_id, key, request_hash, result):
        assert self.active
        if (user_id, key) in self.replays:
            raise StorageConflict("key exists")
        self.replays[user_id, key] = SimpleNamespace(request_hash=request_hash, result=deepcopy(result))


def test_profile_service_reads_plain_records_and_preserves_replay_history():
    store = MemoryProfileStore()
    assert get_profile(store, "user") == {"completed": False, "profile": None, "version": 0}
    first = save_profile(store, "user", ProfileUpdate(**BASE), "first-key")
    second = save_profile(store, "user", ProfileUpdate(**{**BASE, "grade": 3, "expected_version": 1}), "second-key")
    store.major_enabled = False
    assert save_profile(store, "user", ProfileUpdate(**BASE), "first-key") == first
    assert first["profile"]["major_name"] == "专业"
    assert get_profile(store, "user") == second
    assert get_profile(store, "other") == {"completed": False, "profile": None, "version": 0}


def test_profile_service_transaction_failure_restores_prior_profile_and_unused_key():
    store = MemoryProfileStore()
    original = save_profile(store, "user", ProfileUpdate(**BASE), "first-key")
    edit = ProfileUpdate(**{**BASE, "grade": 4, "expected_version": 1, "education_stage": "undergraduate"})
    store.fail_commit = True
    with pytest.raises(StorageError):
        save_profile(store, "user", edit, "retry-key")
    assert get_profile(store, "user") == original
    assert ("user", "retry-key") not in store.replays
    assert not store.active
    store.fail_commit = False
    retried = save_profile(store, "user", edit, "retry-key")
    assert retried["version"] == 2
    assert retried["profile"]["education_stage"] == "undergraduate"
    assert save_profile(store, "user", edit, "retry-key") == retried


def test_profile_service_invalid_selection_leaves_prior_profile_and_key_available():
    store = MemoryProfileStore()
    original = save_profile(store, "user", ProfileUpdate(**BASE), "first-key")
    invalid = ProfileUpdate(**{**BASE, "major_id": "missing", "expected_version": 1})
    with pytest.raises(AppError) as rejected:
        save_profile(store, "user", invalid, "retry-key")
    assert rejected.value.code == "major_not_available"
    assert get_profile(store, "user") == original
    assert ("user", "retry-key") not in store.replays
    assert not store.active
    valid = ProfileUpdate(**{**BASE, "expected_version": 1})
    assert save_profile(store, "user", valid, "retry-key")["version"] == 2


@pytest.mark.parametrize("payload,key,code", [
    ({**BASE, "grade": 4}, "first-key", "key_payload_conflict"),
    ({**BASE, "grade": 4}, "different-key", "version_conflict"),
    ({**BASE, "expected_version": 5}, "different-key", "version_conflict"),
])
def test_profile_service_conflicts_preserve_prior_state(payload, key, code):
    store = MemoryProfileStore()
    original = save_profile(store, "user", ProfileUpdate(**BASE), "first-key")
    with pytest.raises(AppError) as rejected:
        save_profile(store, "user", ProfileUpdate(**payload), key)
    assert rejected.value.code == code
    assert get_profile(store, "user") == original
    assert len(store.replays) == 1
