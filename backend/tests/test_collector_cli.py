"""Local CLI integration: real stores and controlled public HTTP, never account data."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from campus_backend.core.artifacts import make_artifact, read_artifact
from campus_backend.core.config import Settings
from campus_backend.database import initialize_database
from campus_backend.providers import build_collector

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)
SOURCE = {'source_id': 's1', 'school_id': 'csu', 'unit_id': 'u1', 'name': '测试公开源',
          'url': 'https://csu.edu.cn/list', 'allowed_hosts': ['csu.edu.cn'], 'status': 'enabled',
          'article_selector': 'a', 'article_url_pattern': '/info/', 'body_selector': 'article'}


@pytest.fixture
def environment(tmp_path, monkeypatch):
    from campus_backend.collection.http import PublicHTTPClient
    settings = Settings(database_url=f'sqlite:///{tmp_path / "cli.db"}', collector_data_dir=tmp_path/'collector')
    initialize_database(settings, seed=False)
    monkeypatch.setattr(Settings, 'from_env', classmethod(lambda cls: settings))
    responses = {'/list': '<a href="/info/n.htm">全校学生竞赛通知</a>',
                 '/info/n.htm': '<article><p>全校学生竞赛通知，报名截止2026年11月5日。</p></article>'}
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=responses[request.url.path], headers={'content-type': 'text/html; charset=utf-8'}))
    client = PublicHTTPClient(transport=transport, min_interval=0)
    worker, engine = build_collector(settings, clock=lambda: NOW, http=client)
    # Only substitute assembly; all command/service/storage logic remains real.
    import campus_backend.providers as providers
    monkeypatch.setattr(providers, 'build_collector', lambda settings: build_collector(
        settings, clock=lambda: NOW, http=PublicHTTPClient(transport=transport, min_interval=0)))
    registry = tmp_path/'registry.json'
    registry.write_text(json.dumps({'schema_version': '1.0', 'school_id': 'csu', 'sources': [SOURCE]}))
    yield settings, worker, registry
    client.close()
    engine.dispose()


def invoke(capsys, args):
    from campus_backend.cli import main
    result = main(args)
    captured = capsys.readouterr()
    return result, json.loads(captured.out or captured.err)


def test_sources_sync_is_idempotent_and_retains_disabled_source(environment, capsys):
    _, worker, registry = environment
    for _ in range(2):
        code, output = invoke(capsys, ['sources-sync', '--registry', str(registry)])
        assert code == 0
        assert output['sources'] == 1
    assert len(worker.sources.list()) == 1
    registry.write_text(json.dumps({'schema_version': '1.0', 'sources': []}))
    assert invoke(capsys, ['sources-sync', '--registry', str(registry)])[0] == 0
    assert worker.sources.get('s1')['status'] == 'disabled'


def test_collect_once_processes_only_requested_source_and_job_budget(environment, capsys):
    _, worker, registry = environment
    invoke(capsys, ['sources-sync', '--registry', str(registry)])
    worker.sources.sync([SOURCE, SOURCE | {'source_id': 's0'}], NOW)
    worker.sources.schedule(NOW)
    code, output = invoke(capsys, ['collect-once', '--source', 's1', '--source', 's1', '--max-jobs', '1'])
    assert code == 0
    assert output['processed'] == 1
    assert worker.sources.get('s1')['checks'] == 1
    assert worker.sources.get('s0')['checks'] == 0
    # Request typo must fail without silently collecting all sources.
    code, output = invoke(capsys, ['collect-once', '--source', 'missing'])
    assert code == 2
    assert output['error']['code'] == 'invalid_command'


def populate(worker, *, version='v1', publish=True):
    asset = worker.assets.put(b'<p>public original</p>', filename='original.html', media_type='text/html')
    payload = {'title': '公开通知', 'source_id': 's1', 'source_name': '官网', 'school_id': 'csu',
               'school': '中南大学', 'source_url': 'https://csu.edu.cn/info/n.htm', 'published_at': None,
               'body_status': 'complete', 'html': '<p>public original</p>', 'assets': [asset]}
    raw = make_artifact('raw', 'n1', version, payload, now=NOW)
    worker.sources.sync([SOURCE], NOW)
    worker.notices.save_raw(raw, NOW)
    if publish:
        document = make_artifact('document', 'n1', version, payload | {'content': 'public original', 'segments': []}, now=NOW)
        analysis = make_artifact('analysis', 'n1', version, {'classification': {'category': 'competition'}}, now=NOW)
        worker.notices.publish(document, analysis, NOW)
    return asset


def test_reprocess_queues_latest_version_and_does_not_republish_old_snapshot(environment, capsys):
    _, worker, _ = environment
    populate(worker)
    # Finish initial jobs, then queue exactly latest, even though current is v1.
    while (job := worker.jobs.claim(NOW)) is not None:
        worker.jobs.finish(job, NOW)
    populate(worker, version='v2', publish=False)
    while (job := worker.jobs.claim(NOW)) is not None:
        worker.jobs.finish(job, NOW)
    code, output = invoke(capsys, ['reprocess-notice', 'n1'])
    assert code == 0
    assert output['content_version'] == 'v2'
    job = worker.jobs.claim(NOW)
    assert job['kind'] == 'document'
    assert job['payload'] == {'notice_id': 'n1', 'content_version': 'v2'}
    assert worker.notices.get('n1')['current_version'] == 'v1'
    assert invoke(capsys, ['reprocess-notice', 'missing'])[0] == 2


def test_bounded_worker_and_argument_validation(environment, capsys):
    _, worker, registry = environment
    code, output = invoke(capsys, ['collector-worker', '--registry', str(registry), '--duration', '0.08', '--workers', '2'])
    assert code == 0
    assert output['workers'] == 2
    assert worker.sources.get('s1') is not None
    for arguments in (['collect-once', '--max-jobs', '0'], ['collector-worker', '--workers', '0'],
                      ['collector-worker', '--duration', '-1'], ['collector-worker', '--duration', 'nan']):
        with pytest.raises(SystemExit) as exc:
            from campus_backend.cli import main
            main(arguments)
        assert exc.value.code == 2
        capsys.readouterr()


def test_schema_accepts_shared_stages_rejects_unknown_version_and_preserves_extensions():
    from jsonschema import Draft202012Validator, FormatChecker
    schema_path = Path(__file__).resolve().parents[1]/'docs/collector/stage.schema.json'
    schema = json.loads(schema_path.read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for stage in ('raw', 'document', 'analysis', 'enhancement', 'personal_result'):
        artifact = make_artifact(stage, 'notice', 'v1', {'extension': {'kept': True}}, now=NOW)
        validator.validate(artifact)
        artifact['schema_version'] = '2.0'
        assert list(validator.iter_errors(artifact))
    artifact['schema_version'] = '1.0'
    artifact['created_at'] = '2026-10-31T00:00:00'
    assert list(validator.iter_errors(artifact))


def test_module_returns_nonzero_for_invalid_registry_without_touching_database(tmp_path):
    import os
    import subprocess
    import sys
    registry = tmp_path/'bad.json'
    registry.write_text('{"schema_version": "2.0", "sources": []}')
    database = tmp_path/'never-created.db'
    environment = dict(os.environ, CAMPUS_DATABASE_URL=f'sqlite:///{database}')
    result = subprocess.run([sys.executable, '-m', 'campus_backend', 'sources-sync', '--registry', str(registry)],
                            env=environment, text=True, capture_output=True, timeout=20)
    assert result.returncode == 2
    assert json.loads(result.stderr)['error']['code'] == 'invalid_command'
    assert not database.exists()


def test_worker_lane_failure_stops_other_lanes_promptly():
    from threading import Event
    from campus_backend.collection.cli import _run_workers
    source_stopped = []
    detail_started = Event()

    class FailingWorker:
        def run_forever(self, *, stop, duration, kinds, schedule):
            if kinds == ['source']:
                assert schedule is True
                assert detail_started.wait(1)
                source_stopped.append(stop.wait(0.5))
            else:
                assert kinds == ['history', 'detail', 'document']
                assert schedule is False
                detail_started.set()
                raise ValueError('controlled lane failure')

    with pytest.raises(ValueError):
        _run_workers(FailingWorker(), 2, None)
    assert source_stopped == [True]


def test_unknown_operator_failure_is_redacted_and_nonzero(environment, capsys, monkeypatch):
    import campus_backend.providers as providers

    def unavailable(settings):
        raise RuntimeError('secret connection details')

    monkeypatch.setattr(providers, 'build_collector', unavailable)
    code, output = invoke(capsys, ['collect-once'])
    assert code == 2
    assert output['error']['code'] == 'collector_unavailable'
    assert 'secret' not in json.dumps(output)
