"""Atomic full-profile business rules with versions and durable replay."""
import hashlib
import json
from dataclasses import asdict

from campus_backend.catalog.service import validate_selection
from campus_backend.core.errors import AppError
from campus_backend.core.storage import StorageConflict

from .ports import IdempotencyRecord, ProfileRecord, ProfileStore
from .schemas import ProfileUpdate


def get_profile(store: ProfileStore, user_id: str) -> dict:
    profile = store.get_profile(user_id)
    if profile is None:
        return {"completed": False, "profile": None, "version": 0}
    return {"completed": True, "profile": asdict(profile), "version": profile.version}


def _replay(record: IdempotencyRecord, request_hash: str) -> dict:
    if record.request_hash != request_hash:
        raise AppError(409, "key_payload_conflict", "该提交标识已用于其他内容，请使用新的提交标识")
    return record.result


def _version_conflict() -> AppError:
    return AppError(409, "version_conflict", "个人资料已更新，请重新读取后再保存")


def save_profile(store: ProfileStore, user_id: str, payload: ProfileUpdate, key: str) -> dict:
    # Omitted optional fields must not change the historical request fingerprint.
    request_hash = hashlib.sha256(json.dumps(payload.model_dump(exclude_unset=True), sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    try:
        with store.transaction() as tx:
            record = tx.get_idempotency(user_id, key)
            if record is not None:
                return _replay(record, request_hash)

            selection = validate_selection(tx.catalog, payload.school_id, payload.college_id, payload.major_id)
            education_stage = payload.education_stage
            admission_year = payload.admission_year
            preserve_year = "admission_year" not in payload.model_fields_set
            if payload.expected_version > 0 and (education_stage is None or preserve_year):
                current = tx.get_profile(user_id)
                if current is not None:
                    if education_stage is None:
                        education_stage = current.education_stage
                    if preserve_year:
                        admission_year = current.admission_year
            profile = ProfileRecord(**asdict(selection), grade=payload.grade,
                                    version=payload.expected_version + 1, education_stage=education_stage,
                                    admission_year=admission_year)
            if not tx.save_profile(user_id, profile, payload.expected_version):
                raise _version_conflict()
            result = {"completed": True, "profile": asdict(profile), "version": profile.version}
            tx.add_idempotency(user_id, key, request_hash, result)
        return result
    except StorageConflict:
        # A storage adapter rolls back before yielding control here. A winning
        # identical submission replays; a winning first save becomes a version
        # conflict. Never silently repeat a write after a constraint failure.
        record = store.get_idempotency(user_id, key)
        if record is not None:
            return _replay(record, request_hash)
        if payload.expected_version == 0 and store.get_profile(user_id) is not None:
            raise _version_conflict() from None
        raise
