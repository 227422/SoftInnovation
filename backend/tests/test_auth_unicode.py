"""Reject malformed Unicode passwords before hashing or account writes."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from campus_backend.auth.persistence.models import AuthSession, User


@pytest.mark.parametrize("surrogate", ["\ud800", "\udc00"], ids=["high-surrogate", "low-surrogate"])
@pytest.mark.parametrize("action,existing", [
    ("register", False), ("login", False), ("login", True),
], ids=["register", "unknown-login", "existing-login"])
def test_lone_surrogate_password_is_validation_error_without_account_writes(app, surrogate, action, existing):
    email = "unicode-password@example.com"
    password = "private-password-marker-" + surrogate
    with TestClient(app, raise_server_exceptions=False) as client:
        if existing:
            assert client.post("/v1/auth/register", json={
                "email": email, "password": "valid-test-password",
            }).status_code == 201

        # JSON escapes are valid UTF-8 bytes; the decoded password is not valid Unicode.
        response = client.post(f"/v1/auth/{action}",
                               content=json.dumps({"email": email, "password": password}).encode("ascii"),
                               headers={"Content-Type": "application/json"})

        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert error["request_id"]
        assert [detail["field"] for detail in error["details"]] == ["body.password"]
        assert "private-password-marker" not in response.text
        assert surrogate not in response.text
        assert "set-cookie" not in response.headers
        with app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(User)) == int(existing)
            assert db.scalar(select(func.count()).select_from(AuthSession)) == int(existing)


@pytest.mark.parametrize("password", ["这是安全测试密码", "valid-密码-🎓🔑"], ids=["chinese", "emoji"])
@pytest.mark.parametrize("ensure_ascii", [False, True], ids=["utf8", "json-escapes"])
def test_valid_unicode_password_registers_and_logs_in(client, password, ensure_ascii):
    body = json.dumps({"email": "valid-unicode@example.com", "password": password},
                      ensure_ascii=ensure_ascii).encode("utf-8")
    registered = client.post("/v1/auth/register", content=body, headers={"Content-Type": "application/json"})
    assert registered.status_code == 201, registered.text
    account = registered.json()["user"]
    client.cookies.clear()

    logged_in = client.post("/v1/auth/login", content=body, headers={"Content-Type": "application/json"})
    assert logged_in.status_code == 200, logged_in.text
    assert logged_in.json()["user"] == account
    assert client.get("/v1/auth/session").json()["user"] == account
