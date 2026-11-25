"""The offline collection adapter retains outcomes without classifier filtering."""
import runpy
from pathlib import Path

from campus_backend.collection.http import FetchError


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/quality/collect_development.py"


def test_corpus_retains_failed_details_and_ignores_production_title_filter(tmp_path):
    module = runpy.run_path(str(SCRIPT))

    class HTTP:
        def get(self, url, hosts, **kwargs):
            if "list" in url:
                html = '<ul><li><a href="/info/1/10.htm">普通活动报道</a> 2026-11-01</li><li><a href="/info/1/11.htm">不可访问公告</a> 2026-11-02</li></ul>'
            elif "11.htm" in url:
                raise FetchError("access_restricted", "login")
            else:
                html = '<html><article>现场报道<a href="/file.pdf">附件</a></article></html>'
                if url.endswith(".pdf"):
                    raise FetchError("http_error", "HTTP 404")
            return dict(url=url, data=html.encode(), media_type="text/html", encoding="utf-8", headers={})

    source = dict(source_id="test", unit_id="u", url="https://example.com/list",
                  name="test", allowed_hosts=["example.com"], title_include_pattern="考试")
    outcome = module["collect"](HTTP(), [source], tmp_path, limit=5)
    entries = outcome["items"]
    assert len(entries) == 2
    assert entries[0]["status"] == "partial"
    assert entries[0]["published_at"].startswith("2026-11-01")
    assert entries[0]["assets"][1]["error"]["code"] == "http_error"
    assert entries[0]["responses"][0]["sha256"]
    assert entries[1]["status"] == "title_only"
    assert entries[1]["errors"][0]["code"] == "access_restricted"
    assert outcome["sources"][0]["response"]["sha256"]


def test_document_manifest_tracks_hashes_and_same_text_group(tmp_path):
    from datetime import datetime, timezone
    import hashlib
    import json

    from campus_backend.core.artifacts import write_artifact
    from campus_backend.collection.service import title_only

    module = runpy.run_path(str(SCRIPT.with_name("prepare_documents.py")))
    root = tmp_path / "batch"
    (root / "assets").mkdir(parents=True)
    source = {"source_id": "s", "name": "source"}
    manifest = {"items": []}
    for i in (1, 2, 3):
        url = f"https://example.com/info/{i}"
        artifact = title_only(source, {"title": "本科生通告", "url": url},
                              code="not_read", message="missing", now=datetime.now(timezone.utc))
        if i <= 2:
            artifact.update(status="complete", errors=[])
            artifact["payload"].update(body_status="full", html="<p>本科生通告正文。</p>")
        name = f"raw/{i}.json"
        write_artifact(root / name, artifact)
        manifest["items"].append(dict(notice_id=artifact["notice_id"], source_ids=["s"], raw_path=name, url=url))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    index = module["prepare"](tmp_path, ["batch"])
    a, b, c = index["items"]
    assert a["group_id"] == b["group_id"] != c["group_id"]
    assert a["family_status"] == "exact_title_and_body_match"
    assert c["family_status"] == "cross_url_review_pending"
    assert c["body_status"] == "title_only"
    assert a["document_sha256"] == hashlib.sha256((tmp_path / a["document_file"]).read_bytes()).hexdigest()
    assert a["raw_sha256"] == hashlib.sha256((tmp_path / a["raw_file"]).read_bytes()).hexdigest()


def test_document_preparation_does_not_overwrite_a_frozen_snapshot(tmp_path):
    import json
    import pytest
    module = runpy.run_path(str(SCRIPT.with_name('prepare_documents.py')))
    batch = tmp_path / 'batch'
    (batch / 'document').mkdir(parents=True)
    saved = batch / 'document/n1.json'
    saved.write_text('frozen-document')
    (batch / 'manifest.json').write_text(json.dumps({'items': [
        {'notice_id': 'n1', 'raw_path': 'raw/n1.json', 'url': 'https://example.edu/1', 'source_ids': ['s']}
    ]}))
    with pytest.raises(ValueError, match='frozen'):
        module['prepare'](tmp_path, ['batch'])
    assert saved.read_text() == 'frozen-document'


def test_document_index_cli_rejects_existing_file_and_dangling_symlink(tmp_path, monkeypatch, capsys):
    import pytest
    script = SCRIPT.with_name("prepare_documents.py")
    main = runpy.run_path(str(script))["main"]
    monkeypatch.setitem(main.__globals__, "__file__", str(tmp_path / "scripts/quality/prepare_documents.py"))
    monkeypatch.setattr("sys.argv", [str(script), "new-batch"])

    def unexpected_prepare(*args):
        pytest.fail("index conflicts must be detected before document extraction")

    monkeypatch.setitem(main.__globals__, "prepare", unexpected_prepare)
    root = tmp_path / ".runtime/s2-rule-corpus"
    root.mkdir(parents=True)
    destination = root / "document-index.json"
    destination.write_text("frozen")
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "already exists" in capsys.readouterr().err
    assert destination.read_text() == "frozen"

    destination.unlink()
    target = root / "missing.json"
    destination.symlink_to(target)
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "already exists" in capsys.readouterr().err
    assert destination.is_symlink()
    assert not target.exists()


def test_document_index_cli_preserves_racing_writer_and_accepts_new_name(tmp_path, monkeypatch, capsys):
    import json
    import pytest

    script = SCRIPT.with_name("prepare_documents.py")
    main = runpy.run_path(str(script))["main"]
    monkeypatch.setitem(main.__globals__, "__file__", str(tmp_path / "scripts/quality/prepare_documents.py"))
    monkeypatch.setattr("sys.argv", [str(script), "--index-name", "new-index.json", "new-batch"])
    root = tmp_path / ".runtime/s2-rule-corpus"
    root.mkdir(parents=True)
    destination = root / "new-index.json"

    def racing_prepare(*args):
        destination.write_text("winner")
        return {"items": []}

    monkeypatch.setitem(main.__globals__, "prepare", racing_prepare)
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "already exists" in capsys.readouterr().err
    assert destination.read_text() == "winner"
    assert list(root.iterdir()) == [destination]

    destination.unlink()
    monkeypatch.setitem(main.__globals__, "prepare", lambda *args: {"items": []})
    main()
    assert json.loads(destination.read_text()) == {"items": []}
    assert list(root.iterdir()) == [destination]
