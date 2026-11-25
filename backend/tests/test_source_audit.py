import runpy
from pathlib import Path

import httpx
import pytest

from campus_backend.collection.http import FetchError, PublicHTTPClient


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/quality/audit_sources.py"


def test_public_observer_archives_error_without_changing_fetch_error():
    observed = []
    http = PublicHTTPClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(403, content=b"forbidden", headers={"Set-Cookie": "private"})
    ))
    try:
        with pytest.raises(FetchError, match="官网限制"):
            http.get("https://example.org/notice", ["example.org"], observe=observed.append)
    finally:
        http.close()
    assert observed[0]["status"] == 403
    assert observed[0]["data"] == b"forbidden"
    assert "set-cookie" not in observed[0]


def test_archive_parsing_unfiltered_and_resumes(tmp_path):
    audit = runpy.run_path(str(SCRIPT))
    seen = []

    def handler(req):
        seen.append(str(req.url))
        body = '<a href="/info/1/25.htm">其他通知</a>' if req.url.path == "/" else "<article>正文</article>"
        return httpx.Response(200, text=body)

    source = dict(source_id="s", unit_id="u", name="列表", url="https://example.org/",
                  allowed_hosts=["example.org"], title_include_pattern="仅匹配我")
    http = PublicHTTPClient(transport=httpx.MockTransport(handler), min_interval=0)
    try:
        first = audit["record_task"](http, tmp_path, {"kind": "source", **source})
        second = audit["record_task"](http, tmp_path, {"kind": "source", **source})
    finally:
        http.close()
    assert first == second
    assert first["status"] == "parsed_nonempty"
    assert first["detail"]["status"] == "parsed_body"
    assert first["responses"][0]["sha256"]
    assert seen == ["https://example.org/", "https://example.org/info/1/25.htm"]
    classify = audit["outcome"]
    assert classify(403, "access_restricted") == "http_forbidden"
    assert classify(403, "access_restricted", auth=True) == "access_restricted"
    assert classify(200, "parse_error") == "parse_error"


@pytest.mark.parametrize(("body", "status"), [
    ("<html><main>暂无相关信息</main></html>", "empty_confirmed"),
    ("<html><main>普通首页</main></html>", "parse_error"),
    ('<html><main>暂无相关信息<input type="password"></main></html>', "access_restricted"),
])
def test_source_distinguishes_explicitly_empty_unknown_and_auth(tmp_path, body, status):
    audit = runpy.run_path(str(SCRIPT))
    http = PublicHTTPClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body)))
    source = dict(kind="source", source_id="s", unit_id="u", name="栏目", url="https://example.org/",
                  allowed_hosts=["example.org"])
    try:
        row = audit["record_task"](http, tmp_path, source)
        assert row["http_status"] == 200
        assert row["status"] == status
    finally:
        http.close()


def test_audit_does_not_follow_login_redirect_outside_allowlist(tmp_path):
    audit = runpy.run_path(str(SCRIPT))
    requests = []

    def handler(req):
        requests.append(req.url.host)
        return httpx.Response(302, headers={"Location": "https://cas.csu.edu.cn/login"}, content=b"redirect")

    http = PublicHTTPClient(transport=httpx.MockTransport(handler))
    source = dict(kind="source", source_id="s", unit_id="u", name="栏目", url="https://example.org/",
                  allowed_hosts=["example.org"])
    try:
        row = audit["record_task"](http, tmp_path, source)
        assert requests == ["example.org"]
        assert row["http_status"] == 302
        assert row["status"] == "access_restricted"
        assert row["responses"][0]["redirect_host"] == "cas.csu.edu.cn"
    finally:
        http.close()


def test_entry_candidates_are_from_navigation_and_not_followed(tmp_path):
    audit = runpy.run_path(str(SCRIPT))
    assert audit["discover_entry"](
        '<a href="/notices">通知公告</a><a href="javascript:void(0)">学生工作</a>'
        '<a href="/about">学校简介</a>', "https://example.org/"
    ) == [{"url": "https://example.org/notices", "label": "通知公告"}]


def test_plan_covers_all_registered_sources_and_s0_entry_units():
    import json

    audit = runpy.run_path(str(SCRIPT))
    tasks = audit["load_plan"]()
    registry = json.loads(audit["REGISTRY"].read_bytes())
    inventory = json.loads(audit["INVENTORY"].read_bytes())
    expected_units = {
        unit["unit_id"] for section in ("official_target_units", "associated_units", "school_level_units")
        for unit in inventory[section]
    }
    assert {task["source_id"] for task in tasks if task["kind"] == "source"} == {
        source["source_id"] for source in registry["sources"]
    }
    assert {task["unit_id"] for task in tasks if task["kind"] == "entry"} == expected_units
    assert len({(task["kind"], task["source_id"]) for task in tasks}) == len(tasks)


def test_retries_archive_previous_attempt_and_reuse_successful_checkpoint(tmp_path):
    audit = runpy.run_path(str(SCRIPT))
    codes = iter((503, 404))
    http = PublicHTTPClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(next(codes), content=b"public failure page")), min_interval=0)
    source = dict(kind="source", source_id="s", unit_id="u", name="栏目", url="https://example.org/",
                  allowed_hosts=["example.org"])
    try:
        a = audit["record_task"](http, tmp_path, source)
        b = audit["record_task"](http, tmp_path, source, retry=True)
        c = audit["record_task"](http, tmp_path, source, retry=True)
    finally:
        http.close()
    assert a["http_status"] == 503
    assert b == c
    assert b["status"] == "url_missing"
    assert [attempt["http_status"] for attempt in b["attempts"]] == [503, 404]


def test_archive_records_real_bytes_when_response_exceeds_cap():
    observed = []
    http = PublicHTTPClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"abcdef")))
    try:
        with pytest.raises(FetchError) as failure:
            http.get("https://example.org/", ["example.org"], observe=observed.append, max_bytes=3)
    finally:
        http.close()
    assert failure.value.code == "too_large"
    assert observed[0]["status"] == 200
    assert observed[0]["data"] == b"abc"
    assert observed[0]["truncated"] is True


@pytest.mark.parametrize(("status", "destination", "methods"), [
    (303, "https://other.example.org/next", ["POST", "GET"]),
    (302, "https://example.org/next", ["POST"]),
    (307, "https://other.example.org/next", ["POST"]),
    (308, "https://example.org/next", ["POST", "POST"]),
    (303, "https://outside.example.org/next", ["POST"]),
])
def test_public_post_form_redirect_boundaries(status, destination, methods):
    requests = []

    def handler(request):
        requests.append((request.method, request.content, request.headers.get("Referer")))
        if len(requests) == 1:
            return httpx.Response(status, headers={"Location": destination, "Set-Cookie": "session=x"})
        assert "Cookie" not in request.headers
        return httpx.Response(200, content=b"result", headers={"Content-Type": "application/json"})

    http = PublicHTTPClient(transport=httpx.MockTransport(handler), min_interval=0)
    host = "https://example.org"
    form = {"JLNM": "public-id", "WJFL": "1"}
    try:
        if len(methods) == 1:
            with pytest.raises(FetchError):
                http.post_form(host, ["example.org", "other.example.org"], form, referer=host + "/notice")
        else:
            result = http.post_form(host, ["example.org", "other.example.org"], form, referer=host + "/notice")
            assert result["data"] == b"result"
            assert result["media_type"] == "application/json"
            assert result["url"] == destination
        assert [request[0] for request in requests] == methods
        assert requests[0][1:] == (b"JLNM=public-id&WJFL=1", host + "/notice")
        if methods[-1] == "GET":
            assert requests[-1][1] == b""
    finally:
        http.close()


@pytest.mark.parametrize(("status", "max_bytes", "error"), [(200, 3, "too_large"), (403, 10, "access_restricted")])
def test_public_post_form_shares_response_limits(status, max_bytes, error):
    http = PublicHTTPClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, content=b"abcdef")))
    try:
        with pytest.raises(FetchError) as failure:
            http.post_form("https://example.org/", ["example.org"], {"x": "y"}, max_bytes=max_bytes)
        assert failure.value.code == error
    finally:
        http.close()
