"""HTTP profile contracts; fixtures include a fictional second school only for isolation."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

PASSWORD = "correct horse battery staple"
BASE = {"school_id": "test-school", "college_id": "test-college", "major_id": "test-major", "grade": 2, "expected_version": 0}


@pytest.fixture
def profile_catalog(db):
    from campus_backend.catalog.models import School, College, Major
    db.add_all([School(id="test-school", name="测试大学"), School(id="other-school", name="隔离测试大学")])
    db.flush()
    db.add_all([College(id="test-college", school_id="test-school", name="测试学院"), College(id="other-college", school_id="other-school", name="隔离测试学院")])
    db.flush()
    db.add_all([Major(id="test-major", school_id="test-school", college_id="test-college", name="测试专业"), Major(id="other-major", school_id="other-school", college_id="other-college", name="隔离测试专业")])
    db.commit()


def account(client, email="profile@example.com"):
    response = client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


def save(client, auth, payload=None, key="profile-save-0001"):
    return client.patch("/v1/me/profile", json=BASE if payload is None else payload,
                        headers={"X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": key})


def test_empty_and_atomic_save_returns_canonical_profile(client, profile_catalog):
    auth = account(client)
    assert client.get("/v1/me/profile").json() == {"completed": False, "profile": None, "version": 0}
    result = save(client, auth)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "completed": True,
        "profile": {
            "school_id": "test-school", "school_name": "测试大学",
            "college_id": "test-college", "college_name": "测试学院",
            "major_id": "test-major", "major_name": "测试专业",
            "grade": 2, "version": 1, "education_stage": None, "admission_year": None, "major_group": None,
        },
        "version": 1,
    }
    assert client.get("/v1/me/profile").json() == result.json()


def test_old_client_edit_preserves_confirmed_undergraduate_stage(client, profile_catalog):
    auth = account(client)
    first = save(client, auth, {**BASE, "education_stage": "undergraduate"})
    assert first.status_code == 200, first.text
    assert first.json()["profile"]["education_stage"] == "undergraduate"
    assert first.json()["profile"]["major_group"] is None
    assert client.get("/v1/me/profile").json() == first.json()

    edited = save(client, auth, {**BASE, "grade": 8, "expected_version": 1}, key="legacy-client-edit")
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 2
    assert edited.json()["profile"]["grade"] == 8
    assert edited.json()["profile"]["education_stage"] == "undergraduate"
    assert client.get("/v1/me/profile").json() == edited.json()


@pytest.mark.parametrize("stage_fields", [{}, {"education_stage": "undergraduate"}])
def test_admission_year_survives_omitted_edit_and_can_be_cleared(client, profile_catalog, stage_fields):
    auth = account(client)
    first = save(client, auth, {**BASE, "admission_year": 2026, "education_stage": "undergraduate"})
    assert first.status_code == 200, first.text
    assert first.json()["profile"]["admission_year"] == 2026
    assert client.get("/v1/me/profile").json() == first.json()

    omitted = {**BASE, "grade": 8, "expected_version": 1}
    edited = save(client, auth, {**omitted, **stage_fields}, key="legacy-year-edit")
    assert edited.status_code == 200, edited.text
    assert edited.json()["profile"]["grade"] == 8
    assert edited.json()["profile"]["admission_year"] == 2026
    assert client.get("/v1/me/profile").json() == edited.json()

    cleared = save(client, auth, {**omitted, "admission_year": None, "expected_version": 2}, key="clear-year")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["profile"]["admission_year"] is None
    assert cleared.json()["profile"]["education_stage"] == "undergraduate"
    assert client.get("/v1/me/profile").json() == cleared.json()


@pytest.mark.parametrize("year,error_type", [
    ("2026", "int_type"), (True, "int_type"), (2026.0, "int_type"),
    (1899, "greater_than_equal"), (2101, "less_than_equal"),
])
def test_admission_year_rejects_invalid_input_without_writing(client, profile_catalog, year, error_type):
    auth = account(client)
    response = save(client, auth, {**BASE, "admission_year": year})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"] == [{"field": "body.admission_year", "type": error_type}]
    assert client.get("/v1/me/profile").json() == {"completed": False, "profile": None, "version": 0}


@pytest.mark.parametrize("year", [1900, 2100])
def test_admission_year_accepts_recording_boundaries(client, profile_catalog, year):
    auth = account(client)
    response = save(client, auth, {**BASE, "admission_year": year})
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["admission_year"] == year
    assert response.json()["profile"]["major_group"] is None


@pytest.mark.parametrize("first_fields,next_fields", [({}, {"admission_year": None}), ({"admission_year": None}, {})])
def test_profile_replay_distinguishes_omitted_year_from_null(client, profile_catalog, first_fields, next_fields):
    auth = account(client)
    first = save(client, auth, {**BASE, **first_fields})
    assert first.status_code == 200, first.text
    conflict = save(client, auth, {**BASE, **next_fields})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "key_payload_conflict"
    replay = save(client, auth, {**BASE, **first_fields})
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert client.get("/v1/me/profile").json() == first.json()


def test_stale_edit_cannot_clear_admission_year(client, profile_catalog):
    auth = account(client)
    first = save(client, auth, {**BASE, "admission_year": 2024})
    assert first.status_code == 200, first.text
    second = save(client, auth, {**BASE, "admission_year": 2025, "expected_version": 1}, key="correct-year")
    assert second.status_code == 200, second.text
    stale = save(client, auth, {**BASE, "admission_year": None, "expected_version": 1}, key="stale-year-edit")
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "version_conflict"
    current = client.get("/v1/me/profile").json()
    assert current["profile"]["admission_year"] == 2025
    assert current == second.json()
    assert save(client, auth, {**BASE, "admission_year": 2024}).json() == first.json()
    assert client.get("/v1/me/profile").json() == current


@pytest.mark.parametrize("major_code", ["080901", "080902"])
def test_seeded_csu_major_with_year_does_not_confirm_school_major_group(client, major_code):
    auth = account(client)
    college = "csu-college-70de3a80ef24d4d4"
    majors = client.get(f"/v1/catalog/schools/csu/colleges/{college}/majors").json()["items"]
    major = next(item for item in majors if item["code"] == major_code)
    assert major["degree"] == "工学"
    response = save(client, auth, {
        **BASE, "school_id": "csu", "college_id": college, "major_id": major["id"],
        "grade": 1, "education_stage": "undergraduate", "admission_year": 2026,
    })
    assert response.status_code == 200, response.text
    assert response.json()["profile"]["admission_year"] == 2026
    assert response.json()["profile"]["major_group"] is None
    assert client.get("/v1/me/profile").json() == response.json()


def test_profile_is_account_owned_across_sessions_and_user_ids_rejected(app, client, profile_catalog):
    auth = account(client)
    first = save(client, auth, {**BASE, "education_stage": "undergraduate", "admission_year": 2026})
    assert first.status_code == 200, first.text
    saved = first.json()
    assert saved["profile"]["admission_year"] == 2026
    with TestClient(app) as other:
        other_auth = account(other, "second@example.com")
        assert other.get("/v1/me/profile").json()["profile"] is None
        assert other.get("/v1/me/profile", params={"user_id": auth["user"]["id"]}).json()["profile"] is None
        assert save(other, other_auth, {**BASE, "user_id": auth["user"]["id"]}).status_code == 422
        second = save(other, other_auth, {**BASE, "grade": 3})
        assert second.status_code == 200, second.text
        assert second.json()["profile"]["education_stage"] is None
        assert second.json()["profile"]["admission_year"] is None
        assert client.get("/v1/me/profile").json() == saved
    assert client.post("/v1/auth/logout", headers={"X-CSRF-Token": auth["csrf_token"]}).status_code == 204
    login = client.post("/v1/auth/login", json={"email": "profile@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert client.get("/v1/me/profile").json() == saved


@pytest.mark.parametrize("changes,expected_status,expected_code", [
    ({"school_id": "missing"}, 404, "school_not_supported"),
    ({"major_id": "missing"}, 422, "major_not_available"),
    ({"college_id": "other-college"}, 404, "college_not_available"),
    ({"major_id": "other-major"}, 422, "major_not_available"),
])
def test_invalid_catalog_combinations_preserve_saved_profile(client, profile_catalog, changes, expected_status, expected_code):
    auth = account(client)
    original = save(client, auth).json()
    response = save(client, auth, {**BASE, "expected_version": 1, **changes}, key="invalid-selection")
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert client.get("/v1/me/profile").json() == original


@pytest.mark.parametrize("grade", [True, "2", 0, 9, 2.0])
def test_grade_requires_allowed_integer(client, profile_catalog, grade):
    auth = account(client)
    assert save(client, auth, {**BASE, "grade": grade}).status_code == 422
    assert client.get("/v1/me/profile").json()["profile"] is None


def test_versions_and_idempotent_replay_do_not_repeat_stale_edit(client, profile_catalog):
    auth = account(client)
    first = save(client, auth)
    assert first.status_code == 200
    second = save(client, auth, {**BASE, "grade": 3, "expected_version": 1, "education_stage": "undergraduate"},
                  key="profile-save-0002")
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert save(client, auth).json() == first.json()
    assert client.get("/v1/me/profile").json() == second.json()
    conflict = save(client, auth, {**BASE, "grade": 4}, key="stale-profile-key")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "version_conflict"
    changed = save(client, auth, {**BASE, "grade": 4})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "key_payload_conflict"
    assert client.get("/v1/me/profile").json() == second.json()


@pytest.mark.parametrize("changes,field", [
    ({"education_stage": None}, "education_stage"),
    ({"education_stage": "graduate"}, "education_stage"),
    ({"major_group": {"id": "user-group", "name": "自填专业大类"}}, "major_group"),
])
def test_profile_rejects_unconfirmed_stage_values_and_user_supplied_major_group(client, profile_catalog, changes, field):
    auth = account(client)
    response = save(client, auth, {**BASE, **changes})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert f"body.{field}" in {item["field"] for item in error["details"]}
    assert client.get("/v1/me/profile").json()["profile"] is None


def test_expected_version_header_does_not_replace_body_field(client, profile_catalog):
    auth = account(client)
    payload = {field: value for field, value in BASE.items() if field != "expected_version"}
    response = client.patch("/v1/me/profile", json=payload, headers={
        "X-CSRF-Token": auth["csrf_token"], "Idempotency-Key": "missing-body-version", "X-Expected-Version": "0",
    })
    assert response.status_code == 422
    assert {"field": "body.expected_version", "type": "missing"} in response.json()["error"]["details"]
    assert client.get("/v1/me/profile").json()["profile"] is None


def test_disabled_directory_rejects_edit_but_keeps_history_and_replay(client, db, profile_catalog):
    from campus_backend.catalog.models import Major
    auth = account(client)
    first = save(client, auth).json()
    db.get(Major, "test-major").enabled = False
    db.commit()
    assert save(client, auth).json() == first
    assert save(client, auth, {**BASE, "expected_version": 1}, key="disabled-major").status_code == 422
    assert client.get("/v1/me/profile").json() == first


def test_idempotency_key_and_csrf_are_required(client, profile_catalog):
    auth = account(client)
    assert client.patch("/v1/me/profile", json=BASE).status_code == 403
    headers = {"X-CSRF-Token": auth["csrf_token"]}
    assert client.patch("/v1/me/profile", json=BASE, headers=headers).status_code == 422
    for key in ("short", "a" * 129):
        assert save(client, auth, key=key).status_code == 422


def test_expired_session_cannot_read_or_change_profile(app, client, profile_catalog):
    auth = account(client)
    assert save(client, auth).status_code == 200
    now = app.state.clock()
    app.state.clock = lambda: now + timedelta(days=30)
    assert client.get("/v1/me/profile").status_code == 401
    assert save(client, auth, {**BASE, "expected_version": 1}, key="expired-session").status_code == 401


def test_profile_and_replay_record_roll_back_together(app, client, db, profile_catalog):
    auth = account(client)
    first = save(client, auth, {**BASE, "admission_year": 2025})
    assert first.status_code == 200, first.text
    update = {**BASE, "grade": 4, "expected_version": 1, "admission_year": 2026}
    engine = db.get_bind()
    def fail_replay_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into profile_idempotency"):
            raise RuntimeError("private database fault")
    event.listen(engine, "before_cursor_execute", fail_replay_insert)
    try:
        with TestClient(app, raise_server_exceptions=False) as failing:
            failing.cookies.update(client.cookies)
            response = save(failing, auth, update, key="retry-after-fault")
        assert response.status_code == 500
        assert "private database fault" not in response.text
    finally:
        event.remove(engine, "before_cursor_execute", fail_replay_insert)
    assert client.get("/v1/me/profile").json() == first.json()
    retry = save(client, auth, update, key="retry-after-fault")
    assert retry.status_code == 200
    assert retry.json()["version"] == 2
    assert retry.json()["profile"]["grade"] == 4
    assert retry.json()["profile"]["admission_year"] == 2026


def test_profile_read_fault_is_error_not_empty_state(app, client, db, profile_catalog):
    auth = account(client)
    saved = save(client, auth).json()
    engine = db.get_bind()
    def fail_profile_read(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select") and "student_profiles" in statement:
            raise RuntimeError("private read fault")
    event.listen(engine, "before_cursor_execute", fail_profile_read)
    try:
        with TestClient(app, raise_server_exceptions=False) as failing:
            failing.cookies.update(client.cookies)
            response = failing.get("/v1/me/profile")
        assert response.status_code == 500
        assert "private read fault" not in response.text
        assert "completed" not in response.json()
    finally:
        event.remove(engine, "before_cursor_execute", fail_profile_read)
    assert client.get("/v1/me/profile").json() == saved


def test_failed_first_save_does_not_leave_partial_profile_or_used_key(app, client, db, profile_catalog):
    auth = account(client)
    engine = db.get_bind()
    def fail_replay_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into profile_idempotency"):
            raise RuntimeError("private first save fault")
    event.listen(engine, "before_cursor_execute", fail_replay_insert)
    try:
        with TestClient(app, raise_server_exceptions=False) as failing:
            failing.cookies.update(client.cookies)
            assert save(failing, auth).status_code == 500
    finally:
        event.remove(engine, "before_cursor_execute", fail_replay_insert)
    assert client.get("/v1/me/profile").json() == {"completed": False, "profile": None, "version": 0}
    assert save(client, auth).json()["version"] == 1


def test_profile_requires_authentication(client):
    assert client.get("/v1/me/profile").status_code == 401
    assert client.patch("/v1/me/profile", json=BASE, headers={"Idempotency-Key": "anonymous-key"}).status_code == 401


@pytest.mark.parametrize("expected_version", [0, 1])
@pytest.mark.parametrize("same_key,same_content,conflict_code", [
    (True, True, None),
    (True, False, "key_payload_conflict"),
    (False, False, "version_conflict"),
])
def test_concurrent_submissions_commit_once(app, client, db, profile_catalog,
                                           expected_version, same_key, same_content, conflict_code):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    auth = account(client)
    if expected_version:
        assert save(client, auth).status_code == 200
    gate = Barrier(2)
    engine = db.get_bind()
    def align_writes(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lstrip().lower()
        # Both devices reach their write-transaction attempt together; the
        # writer reservation then serializes their validation and saves.
        if sql == "begin immediate":
            gate.wait(timeout=5)
    def submit(index):
        with TestClient(app) as device:
            device.cookies.update(client.cookies)
            payload = {**BASE, "grade": 3 if same_content else 3 + index, "expected_version": expected_version}
            key = "concurrent-same-key" if same_key else f"concurrent-key-{index}"
            return save(device, auth, payload, key=key)
    event.listen(engine, "before_cursor_execute", align_writes)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", align_writes)
    if conflict_code is None:
        assert [r.status_code for r in responses] == [200, 200]
        assert responses[0].json() == responses[1].json()
    else:
        assert sorted(r.status_code for r in responses) == [200, 409]
        rejected = next(r for r in responses if r.status_code == 409)
        assert rejected.json()["error"]["code"] == conflict_code
    current = client.get("/v1/me/profile").json()
    assert current["version"] == expected_version + 1
    assert current == next(r for r in responses if r.status_code == 200).json()


@pytest.mark.parametrize("payload", [
    {**BASE, "expected_version": True},
    {**BASE, "expected_version": "0"},
    {**BASE, "expected_version": -1},
    {"school_id": "test-school", "grade": 2, "expected_version": 0},
])
def test_save_requires_full_fields_and_a_nonnegative_integer_version(client, profile_catalog, payload):
    auth = account(client)
    assert save(client, auth, payload).status_code == 422
    assert client.get("/v1/me/profile").json() == {"completed": False, "profile": None, "version": 0}


@pytest.mark.parametrize("version", [9223372036854775807, 9223372036854775808, 10**100])
def test_version_exceeding_sqlite_increment_range_is_validation_error(app, client, profile_catalog, version):
    auth = account(client)
    original = save(client, auth).json()
    with TestClient(app, raise_server_exceptions=False) as device:
        device.cookies.update(client.cookies)
        response = save(device, auth, {**BASE, "expected_version": version}, key="invalid-version-key")
    assert response.status_code == 422, response.text
    assert client.get("/v1/me/profile").json() == original


def test_last_safe_expected_version_saves_without_integer_overflow(client, db, profile_catalog):
    from sqlalchemy import update
    from campus_backend.profile.models import StudentProfile
    auth = account(client)
    assert save(client, auth).status_code == 200
    db.execute(update(StudentProfile).values(version=9223372036854775806))
    db.commit()
    response = save(client, auth, {**BASE, "grade": 4, "expected_version": 9223372036854775806}, key="last-safe-version")
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 9223372036854775807
    assert client.get("/v1/me/profile").json() == response.json()


def test_save_and_directory_disable_have_a_serial_commit_order(app, client, profile_catalog, monkeypatch):
    """A competing directory write cannot commit between validation and profile save."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import update
    from sqlalchemy.exc import OperationalError
    from campus_backend.catalog.models import Major
    from campus_backend.profile import service

    auth = account(client)
    validated, competitor_observed, save_finished = Event(), Event(), Event()
    order = []
    original = service.validate_selection

    def validate_and_coordinate(*args):
        selected = original(*args)
        validated.set()
        assert competitor_observed.wait(5), "competing writer did not finish its first attempt"
        return selected

    def disable_major():
        assert validated.wait(5)
        with app.state.session_factory() as competitor:
            competitor.connection().exec_driver_sql("PRAGMA busy_timeout=0")
            try:
                competitor.execute(update(Major).where(Major.id == "test-major").values(enabled=False))
                competitor.commit()
                order.append("directory_committed")
            except OperationalError as exc:
                assert "locked" in str(exc).lower()
                competitor.rollback()
                order.append("directory_waiting")
            finally:
                competitor_observed.set()
            if "directory_committed" not in order:
                assert save_finished.wait(5), "profile did not release its transaction"
                competitor.execute(update(Major).where(Major.id == "test-major").values(enabled=False))
                competitor.commit()
                order.append("directory_committed")

    monkeypatch.setattr(service, "validate_selection", validate_and_coordinate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        competing = pool.submit(disable_major)
        try:
            response = save(client, auth)
            order.append("profile_confirmed")
        finally:
            save_finished.set()
        competing.result(timeout=5)
    assert response.status_code == 200, response.text
    assert order == ["directory_waiting", "profile_confirmed", "directory_committed"]
    assert client.get("/v1/me/profile").json() == response.json()
    # A later edit observes the now-disabled directory and keeps historical data.
    monkeypatch.setattr(service, "validate_selection", original)
    rejected = save(client, auth, {**BASE, "expected_version": 1}, key="post-disable-edit")
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "major_not_available"
    assert client.get("/v1/me/profile").json() == response.json()


def test_directory_writer_winning_lock_is_seen_before_profile_validation(app, client, profile_catalog):
    """An already-started directory change commits first; waiting save rejects it."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import update
    from campus_backend.catalog.models import Major

    auth = account(client)
    original = save(client, auth).json()
    save_attempting, directory_confirmed = Event(), Event()
    engine = app.state.engine
    order = []
    def observe_save_attempt(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().lower() == "begin immediate":
            save_attempting.set()
    def submit():
        with TestClient(app) as device:
            device.cookies.update(client.cookies)
            result = save(device, auth, {**BASE, "grade": 4, "expected_version": 1}, key="directory-won-first")
            assert directory_confirmed.wait(5), "directory commit was never confirmed"
            order.append("profile_rejected")
            return result

    with app.state.session_factory() as directory:
        directory.connection().exec_driver_sql("BEGIN IMMEDIATE")
        directory.execute(update(Major).where(Major.id == "test-major").values(enabled=False))
        event.listen(engine, "before_cursor_execute", observe_save_attempt)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(submit)
                try:
                    assert save_attempting.wait(5), "profile save never attempted its transaction"
                    directory.commit()
                    order.append("directory_committed")
                    directory_confirmed.set()
                finally:
                    directory.rollback()
                response = pending.result(timeout=5)
        finally:
            event.remove(engine, "before_cursor_execute", observe_save_attempt)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "major_not_available"
    assert order == ["directory_committed", "profile_rejected"]
    assert client.get("/v1/me/profile").json() == original
