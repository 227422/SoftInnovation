"""Exercise preference contracts through authenticated HTTP and a real SQLite database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from campus_backend.app import create_app
from test_integration import choice
from test_profile import PASSWORD, account, save as save_profile

PREFERENCES = "/v1/me/preferences"
CATALOG = "/v1/catalog/preferences"
EMPTY = {"course_ids": [], "skill_ids": [], "goal_ids": [], "interest_ids": []}
INITIAL = {**EMPTY, "version": 0}
FIRST = {**EMPTY, "expected_version": 0}
SELECTED = {**FIRST, "skill_ids": ["skill_writing", "skill_python"],
            "goal_ids": ["goal_research"], "interest_ids": ["interest_volunteering"]}


def save(client, auth, payload=FIRST, key="preferences-first"):
    return client.patch(PREFERENCES, json=payload,
                        headers={"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": key})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"]
    return error


def test_empty_preferences_can_be_saved_or_skipped_independently_of_profile(client):
    auth = account(client)
    profile_before = client.get("/v1/me/profile").json()
    assert client.get(PREFERENCES).status_code == 200
    assert client.get(PREFERENCES).json() == INITIAL
    saved = save(client, auth)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {**EMPTY, "version": 1}
    assert client.get("/v1/me/profile").json() == profile_before

    profile = save_profile(client, auth, choice(client), key="preferences-first")
    assert profile.status_code == 200, profile.text
    assert profile.json()["version"] == 1
    assert client.get(PREFERENCES).json() == saved.json()
    edited = save(client, auth, {**SELECTED, "expected_version": 1}, key="preferences-edit")
    assert edited.status_code == 200, edited.text
    assert edited.json() == {
        "course_ids": [], "skill_ids": ["skill_writing", "skill_python"],
        "goal_ids": ["goal_research"], "interest_ids": ["interest_volunteering"], "version": 2,
    }
    assert client.get("/v1/me/profile").json() == profile.json()


@pytest.mark.parametrize("kind,entries", [
    ("course", []),
    ("skill", [("skill_python", "Python编程"), ("skill_data_analysis", "数据分析"),
               ("skill_writing", "文字写作"), ("skill_design", "平面设计"),
               ("skill_presentation", "演讲表达")]),
    ("goal", [("goal_research", "了解科研机会"), ("goal_competition", "参与学科竞赛"),
              ("goal_further_study", "了解升学交流"), ("goal_employment", "了解实习就业")]),
    ("interest", [("interest_science_technology", "科学与技术"), ("interest_humanities_social", "人文与社会"),
                  ("interest_arts_sports", "文艺与体育"), ("interest_volunteering", "志愿与社会实践")]),
])
def test_catalog_exposes_only_published_self_reported_options(client, kind, entries):
    response = client.get(CATALOG, params={"kind": kind})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"] == [{"id": item_id, "name": name} for item_id, name in entries]
    if kind == "course":
        assert payload["message"] == "课程目录尚待核验，可跳过"
    else:
        assert "自述" in payload["message"] and "非资格核验" in payload["message"]


@pytest.mark.parametrize("params", [{}, {"kind": "major"}, {"kind": "Course"}])
def test_catalog_requires_a_supported_kind(client, params):
    assert_error(client.get(CATALOG, params=params), 422, "validation_error")


@pytest.mark.parametrize("changes,field,error_type", [
    ({"course_ids": ["course_unverified"]}, "course_ids", "value_error"),
    ({"goal_ids": ["skill_python"]}, "goal_ids", "value_error"),
    ({"skill_ids": ["skill_unknown"]}, "skill_ids", "value_error"),
    ({"skill_ids": ["skill_python", "skill_python"]}, "skill_ids", "value_error"),
    ({"interest_ids": [""]}, "interest_ids.0", "string_too_short"),
    ({"interest_ids": ["x" * 129]}, "interest_ids.0", "string_too_long"),
    ({"interest_ids": [123]}, "interest_ids.0", "string_type"),
    ({"goal_ids": "goal_research"}, "goal_ids", "list_type"),
    ({"skill_ids": [f"skill_{i}" for i in range(101)]}, "skill_ids", "too_long"),
    ({"expected_version": False}, "expected_version", "int_type"),
    ({"expected_version": "0"}, "expected_version", "int_type"),
    ({"expected_version": 0.0}, "expected_version", "int_type"),
    ({"expected_version": -1}, "expected_version", "greater_than_equal"),
    ({"expected_version": 9223372036854775807}, "expected_version", "less_than_equal"),
    ({"user_id": "other-account"}, "user_id", "extra_forbidden"),
    ({"arbitrary": True}, "arbitrary", "extra_forbidden"),
])
def test_invalid_payload_cannot_advance_preferences_or_consume_key(client, changes, field, error_type):
    auth = account(client)
    error = assert_error(save(client, auth, {**FIRST, **changes}), 422, "validation_error")
    assert {"field": f"body.{field}", "type": error_type} in error["details"]
    assert client.get(PREFERENCES).json() == INITIAL
    assert save(client, auth).json() == {**EMPTY, "version": 1}


@pytest.mark.parametrize("field", FIRST)
def test_patch_requires_every_array_and_version_in_body(client, field):
    auth = account(client)
    payload = {key: value for key, value in FIRST.items() if key != field}
    response = client.patch(PREFERENCES, json=payload, headers={
        "X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": "missing-field", "X-Expected-Version": "0",
    })
    error = assert_error(response, 422, "validation_error")
    assert {"field": f"body.{field}", "type": "missing"} in error["details"]


def test_preferences_are_account_owned_even_with_same_idempotency_key(app, client):
    auth = account(client)
    first = save(client, auth, SELECTED)
    assert first.status_code == 200, first.text
    with TestClient(app) as other:
        other_auth = account(other, "other-preferences@example.com")
        other_view = other.get(PREFERENCES, params={"user_id": auth["user"]["id"]})
        assert other_view.status_code == 200, other_view.text
        assert other_view.json() == INITIAL
        second = save(other, other_auth, {**FIRST, "interest_ids": ["interest_arts_sports"]})
        assert second.status_code == 200, second.text
        assert second.json() == {**EMPTY, "interest_ids": ["interest_arts_sports"], "version": 1}
        assert other.get(PREFERENCES).json() == second.json()
    assert client.get(PREFERENCES).json() == first.json()


def test_preferences_require_cookie_csrf_and_existing_transport_protections(client):
    assert_error(client.get(PREFERENCES), 401, "session_invalid")
    assert_error(client.patch(PREFERENCES, json=FIRST), 401, "session_invalid")
    auth = account(client)
    headers = {"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": "protected-save"}
    assert_error(client.patch(PREFERENCES, json=FIRST, headers={"Idempotency-Key": "protected-save"}),
                 403, "csrf_invalid")
    assert_error(client.patch(PREFERENCES, json=FIRST, headers={**headers, "X-CSRF-Token": "wrong"}),
                 403, "csrf_invalid")
    assert_error(client.patch(PREFERENCES, json=FIRST, headers={**headers, "Origin": "https://other.invalid"}),
                 403, "origin_forbidden")
    assert_error(client.patch(PREFERENCES, content="{}", headers=headers), 415, "json_required")
    assert_error(client.patch(PREFERENCES, content=b" " * 65537,
                              headers={**headers, "Content-Type": "application/json"}),
                 413, "payload_too_large")
    assert client.get(PREFERENCES).json() == INITIAL
    assert client.patch(PREFERENCES, json=FIRST, headers=headers).status_code == 200


@pytest.mark.parametrize("key", [None, "a" * 7, "a" * 129])
def test_preferences_reject_missing_or_out_of_range_idempotency_key(client, key):
    auth = account(client)
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    if key is not None:
        headers["Idempotency-Key"] = key
    assert_error(client.patch(PREFERENCES, json=FIRST, headers=headers), 422, "validation_error")
    assert client.get(PREFERENCES).json() == INITIAL


def test_preferences_session_expires_after_30_days_despite_refresh(app, client):
    started = datetime.now(timezone.utc).replace(microsecond=0)
    app.state.clock = lambda: started
    auth = account(client)
    assert auth["expires_at"] == int((started + timedelta(days=30)).timestamp())
    app.state.clock = lambda: started + timedelta(days=29)
    refresh = client.post("/v1/auth/refresh", headers={"X-CSRF-Token": auth["csrf_token"]})
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["expires_at"] == auth["expires_at"]
    assert client.get(PREFERENCES).status_code == 200
    app.state.clock = lambda: started + timedelta(days=30)
    assert_error(client.get(PREFERENCES), 401, "session_invalid")
    assert_error(save(client, auth), 401, "session_invalid")


def test_replay_precedes_catalog_and_version_checks_after_catalog_changes(app, client):
    auth = account(client)
    original = save(client, auth, SELECTED)
    assert original.status_code == 200, original.text
    current = save(client, auth, {**FIRST, "expected_version": 1}, key="preferences-clear")
    assert current.status_code == 200, current.text

    from campus_backend.catalog.preferences import PreferencesCatalog, load_preferences_catalog

    app.dependency_overrides[load_preferences_catalog] = lambda: PreferencesCatalog(
        course=(), skill=(), goal=(), interest=(),
    )
    assert save(client, auth, SELECTED).json() == original.json()
    changed = save(client, auth, {**SELECTED, "skill_ids": ["skill_python", "skill_writing"]})
    assert_error(changed, 409, "key_payload_conflict")
    changed_version = save(client, auth, {**SELECTED, "expected_version": 1})
    assert_error(changed_version, 409, "key_payload_conflict")
    rejected = save(client, auth, {**SELECTED, "expected_version": 2}, key="removed-skill")
    assert_error(rejected, 422, "validation_error")
    assert client.get(PREFERENCES).json() == current.json()


def test_synthetic_course_catalog_accepts_maximum_ids_in_submitted_order(app, client):
    auth = account(client)
    assert client.get(CATALOG, params={"kind": "course"}).json()["items"] == []

    from campus_backend.catalog.preferences import PreferenceOption, load_preferences_catalog

    ids = [f"course_{index:03d}" + "x" * 118 for index in range(100)]
    assert len(ids[0]) == 128
    catalog = load_preferences_catalog().model_copy(update={
        "course": tuple(PreferenceOption(id=item, name="合成课程") for item in ids),
    })
    app.dependency_overrides[load_preferences_catalog] = lambda: catalog
    listed = client.get(CATALOG, params={"kind": "course"}).json()
    assert [item["id"] for item in listed["items"]] == ids
    saved = save(client, auth, {**FIRST, "course_ids": ids[::-1]}, key="a" * 8)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {**EMPTY, "course_ids": ids[::-1], "version": 1}
    assert client.get(PREFERENCES).json() == saved.json()
    cleared = save(client, auth, {**FIRST, "expected_version": 1}, key="a" * 128)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {**EMPTY, "version": 2}


def test_last_safe_expected_version_can_be_incremented(app, client):
    auth = account(client)
    first = save(client, auth)
    assert first.status_code == 200, first.text
    with app.state.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE student_preferences SET version=9223372036854775806")
    last = save(client, auth, {**SELECTED, "expected_version": 9223372036854775806}, key="last-version")
    assert last.status_code == 200, last.text
    assert last.json()["version"] == 9223372036854775807
    assert client.get(PREFERENCES).json() == last.json()


@pytest.mark.parametrize("existing", [False, True])
def test_sqlite_replay_insert_failure_rolls_back_preferences_but_leaves_profile_usable(app, client, existing):
    auth = account(client)
    prior = INITIAL
    if existing:
        first = save(client, auth, SELECTED)
        assert first.status_code == 200, first.text
        prior = first.json()
    body = {**FIRST, "expected_version": prior["version"], "goal_ids": ["goal_employment"]}
    with app.state.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_preferences_replay BEFORE INSERT ON preferences_idempotency "
            "BEGIN SELECT RAISE(ABORT, 'private replay failure'); END"
        )
    try:
        response = save(client, auth, body, key="preferences-retry")
        assert_error(response, 503, "storage_unavailable")
        assert "private replay failure" not in response.text
        assert client.get(PREFERENCES).json() == prior
        profile = save_profile(client, auth, choice(client), key="preferences-retry")
        assert profile.status_code == 200, profile.text
        assert client.get("/v1/me/profile").json() == profile.json()
    finally:
        with app.state.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER reject_preferences_replay")
    retry = save(client, auth, body, key="preferences-retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["version"] == prior["version"] + 1
    assert client.get(PREFERENCES).json() == retry.json()
    assert client.get("/v1/me/profile").json() == profile.json()


@pytest.mark.parametrize("expected_version", [0, 1])
@pytest.mark.parametrize("same_key,same_body,rejection", [
    (True, True, None),
    (True, False, "key_payload_conflict"),
    (False, False, "version_conflict"),
])
def test_two_device_submissions_serialize_and_commit_once(app, client, expected_version,
                                                        same_key, same_body, rejection):
    auth = account(client)
    email = auth["user"]["email"]
    before = client.get(PREFERENCES)
    assert before.status_code == 200, before.text
    if expected_version:
        assert save(client, auth).status_code == 200

    with TestClient(app) as other:
        login = other.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200, login.text
        gate = Barrier(2)

        def align_writes(conn, cursor, statement, parameters, context, executemany):
            if statement.strip().upper() == "BEGIN IMMEDIATE":
                gate.wait(timeout=5)

        def submit(device, session, index):
            skill_ids = ["skill_python" if same_body or index == 0 else "skill_writing"]
            key = "concurrent-save" if same_key else f"concurrent-save-{index}"
            return save(device, session, {**FIRST, "skill_ids": skill_ids,
                                          "expected_version": expected_version}, key=key)

        event.listen(app.state.engine, "before_cursor_execute", align_writes)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(submit, client, auth, 0), pool.submit(submit, other, login.json(), 1)]
                responses = [future.result(timeout=10) for future in pending]
        finally:
            event.remove(app.state.engine, "before_cursor_execute", align_writes)

        if rejection is None:
            assert [response.status_code for response in responses] == [200, 200]
            assert responses[0].json() == responses[1].json()
        else:
            assert sorted(response.status_code for response in responses) == [200, 409]
            assert_error(next(response for response in responses if response.status_code == 409), 409, rejection)
        winner = next(response.json() for response in responses if response.status_code == 200)
        assert winner["version"] == expected_version + 1
        assert other.get(PREFERENCES).json() == winner
        assert client.get(PREFERENCES).json() == winner


def test_new_app_restores_preference_snapshots_and_replays(app, client):
    auth = account(client)
    first = save(client, auth, SELECTED)
    assert first.status_code == 200, first.text
    second = save(client, auth, {**FIRST, "expected_version": 1}, key="preferences-clear")
    assert second.status_code == 200, second.text

    with TestClient(create_app(app.state.settings)) as restarted:
        restarted.cookies.update(client.cookies)
        assert restarted.get(PREFERENCES).json() == second.json()
        replay = save(restarted, auth, SELECTED)
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()
        assert restarted.get(PREFERENCES).json() == second.json()
