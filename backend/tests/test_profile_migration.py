"""Upgrade populated historical databases without rewriting profiles or replays."""
import hashlib
import json

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, inspect, select

from campus_backend.app import create_app
from campus_backend.core.config import Settings
from campus_backend.core.db import build_engine
from campus_backend.database import initialize_database, migration_config


LEGACY_SELECTION = {
    "school_id": "csu", "college_id": "csu-college-70de3a80ef24d4d4",
    "major_id": "csu-college-70de3a80ef24d4d4-080901-59318b4c25", "grade": 2,
}


def insert_legacy_profile(db, user_id, key, body):
    # Use the database's old schema and request format, independent of the current models.
    profiles = Table("student_profiles", MetaData(), autoload_with=db)
    replays = Table("profile_idempotency", MetaData(), autoload_with=db)
    profile = {**LEGACY_SELECTION, "school_name": "中南大学", "college_name": "计算机学院",
               "major_name": "计算机科学与技术", "version": 1}
    if "education_stage" in body:
        profile["education_stage"] = body["education_stage"]
    result = {"completed": True, "profile": profile, "version": 1}
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    db.execute(profiles.insert().values(user_id=user_id, **profile))
    db.execute(replays.insert().values(user_id=user_id, key=key, request_hash=request_hash, result=result))
    return request_hash, result


@pytest.mark.parametrize("revision,extra", [
    ("0002_public_collector", {}),
    ("0004_preferences", {"education_stage": "undergraduate"}),
])
def test_upgrade_preserves_legacy_profile_session_and_replay(tmp_path, revision, extra):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'legacy.db'}", cookie_secure=False)
    command.upgrade(migration_config(settings), revision)
    body = {**LEGACY_SELECTION, "expected_version": 0, **extra}
    legacy_key = "before-migration"

    with TestClient(create_app(settings)) as previous:
        registration = previous.post("/v1/auth/register", json={
            "email": "legacy-profile@example.com", "password": "test-password-strong",
        })
        assert registration.status_code == 201, registration.text
        session = registration.json()
        cookie = previous.cookies.get(settings.cookie_name)
        assert cookie is not None

    user_id = session["user"]["id"]
    engine = build_engine(settings.database_url)
    try:
        with engine.begin() as db:
            columns = {column["name"] for column in inspect(db).get_columns("student_profiles")}
            assert "admission_year" not in columns
            assert ("education_stage" in columns) == bool(extra)
            request_hash, legacy_result = insert_legacy_profile(db, user_id, legacy_key, body)

        initialize_database(settings)
        with TestClient(create_app(settings)) as upgraded:
            upgraded.cookies.set(settings.cookie_name, cookie)
            restored_session = upgraded.get("/v1/auth/session")
            assert restored_session.status_code == 200, restored_session.text
            assert restored_session.json() == session
            restored_profile = upgraded.get("/v1/me/profile")
            assert restored_profile.status_code == 200, restored_profile.text
            expected = {**legacy_result, "profile": {
                "education_stage": None, **legacy_result["profile"], "admission_year": None, "major_group": None,
            }}
            assert restored_profile.json() == expected

            headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": legacy_key}
            new_body = {**body, "education_stage": "undergraduate", "admission_year": 2026}
            updated = upgraded.patch("/v1/me/profile", json={**new_body, "expected_version": 1},
                                     headers={**headers, "Idempotency-Key": "after-migration"})
            assert updated.status_code == 200, updated.text
            assert updated.json()["version"] == 2
            assert updated.json()["profile"]["education_stage"] == "undergraduate"
            assert updated.json()["profile"]["admission_year"] == 2026

            replayed = upgraded.patch("/v1/me/profile", json=body, headers=headers)
            assert replayed.status_code == 200, replayed.text
            assert replayed.json() == expected
            conflict = upgraded.patch("/v1/me/profile", json={**body, "admission_year": None}, headers=headers)
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "key_payload_conflict"
            assert upgraded.get("/v1/me/profile").json() == updated.json()

        with engine.connect() as db:
            replays = Table("profile_idempotency", MetaData(), autoload_with=db)
            stored = db.execute(select(replays.c.request_hash, replays.c.result).where(
                replays.c.user_id == user_id, replays.c.key == legacy_key,
            )).one()
            assert stored == (request_hash, legacy_result)
    finally:
        engine.dispose()
