"""Plain profile snapshots and transactional storage contracts."""
from dataclasses import dataclass
from typing import ContextManager, Literal, Protocol

from campus_backend.catalog.ports import CatalogStore

EducationStage = Literal["undergraduate"]


@dataclass(frozen=True)
class ProfileRecord:
    school_id: str
    school_name: str
    college_id: str
    college_name: str
    major_id: str
    major_name: str
    grade: int
    version: int
    education_stage: EducationStage | None = None
    admission_year: int | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    request_hash: str
    result: dict


class ProfileTransaction(Protocol):
    """Reserve writes before replay/validation and commit all changes together.

    The catalog view shares this transaction's connection and ordering guarantee.
    A failed operation or commit must roll back both profile and replay changes.
    """
    catalog: CatalogStore

    def get_idempotency(self, user_id: str, key: str) -> IdempotencyRecord | None: ...
    def get_profile(self, user_id: str) -> ProfileRecord | None: ...
    def save_profile(self, user_id: str, profile: ProfileRecord, expected_version: int) -> bool: ...
    def add_idempotency(self, user_id: str, key: str, request_hash: str, result: dict) -> None: ...


class ProfileStore(Protocol):
    def get_profile(self, user_id: str) -> ProfileRecord | None: ...
    def get_idempotency(self, user_id: str, key: str) -> IdempotencyRecord | None: ...
    def transaction(self) -> ContextManager[ProfileTransaction]: ...
