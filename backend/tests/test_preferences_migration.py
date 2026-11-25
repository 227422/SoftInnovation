"""Upgrade a populated 0003 database with no legacy preference import."""
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from campus_backend.app import create_app
from campus_backend.core.config import Settings
from campus_backend.core.db import build_engine
from campus_backend.database import initialize_database, migration_config
from test_preferences import INITIAL, PREFERENCES, SELECTED, save
from test_profile import account, save as save_profile
from test_profile_migration import LEGACY_SELECTION, insert_legacy_profile


def test_upgrade_adds_empty_preferences_without_rewriting_profile_session_or_replay(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'before-preferences.db'}", cookie_secure=False)
    command.upgrade(migration_config(settings), "0003_profile_education_stage")
    engine = build_engine(settings.database_url)
    try:
        from campus_backend.catalog.persistence.seed import seed_catalog
        from campus_backend.core.db import make_session_factory

        with make_session_factory(engine)() as db:
            seed_catalog(db)
        with TestClient(create_app(settings)) as legacy:
            auth = account(legacy)
            cookie = legacy.cookies.get(settings.cookie_name)
            assert cookie is not None
        body = {**LEGACY_SELECTION, "expected_version": 0, "education_stage": "undergraduate"}
        with engine.begin() as connection:
            assert "student_preferences" not in inspect(connection).get_table_names()
            assert "preferences_idempotency" not in inspect(connection).get_table_names()
            _, original = insert_legacy_profile(connection, auth["user"]["id"], "prefs-migration", body)
        expected_profile = {**original, "profile": {**original["profile"], "admission_year": None, "major_group": None}}

        initialize_database(settings, seed=False)
        with engine.connect() as connection:
            for table in ("student_preferences", "preferences_idempotency"):
                assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        with TestClient(create_app(settings)) as upgraded:
            upgraded.cookies.set(settings.cookie_name, cookie)
            assert upgraded.get("/v1/auth/session").json() == auth
            assert upgraded.get("/v1/me/profile").json() == expected_profile
            assert upgraded.get(PREFERENCES).json() == INITIAL
            preferred = save(upgraded, auth, SELECTED, key="prefs-migration")
            assert preferred.status_code == 200, preferred.text
            assert preferred.json()["version"] == 1
            replay = save_profile(upgraded, auth, body, key="prefs-migration")
            assert replay.status_code == 200, replay.text
            assert replay.json() == expected_profile
            assert upgraded.get(PREFERENCES).json() == preferred.json()
    finally:
        engine.dispose()
