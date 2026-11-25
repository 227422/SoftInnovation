import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.facts_input import build_document_bundle
from campus_backend.providers import build_fact_worker


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'docs/quality/examples'
DOCUMENT_FILE = EXAMPLE / 'synthetic-document.json'
REPLAY = EXAMPLE / 'synthetic-responses.json'
ENV_KEYS = {
    'S2_RESPONSES_BASE_URL': 'https://responses.example/v1',
    'S2_RESPONSES_MODEL': 'pinned-test-model',
    'S2_RESPONSES_CONTEXT_LIMIT': '20000',
    'S2_RESPONSES_API_KEY': 'test-secret',
}
CLI = [sys.executable, '-m', 'campus_backend.classification.processing_cli']


def document():
    return build_document_bundle(json.loads(DOCUMENT_FILE.read_text()))


def cli(root, *arguments, env=None):
    run = subprocess.run([*CLI, '--run-dir', str(root), *map(str, arguments)],
                         env=env, capture_output=True, text=True, check=False, cwd=ROOT)
    return run.returncode, json.loads(run.stdout or run.stderr)


def failing_transport(request):
    if request.url.path.endswith('/input_tokens'):
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
    return httpx.Response(502, text='provider exception mentioning test-secret')


def state(root, job_key):
    return json.loads((root / job_key / 'state.json').read_text())


def test_replay_runs_pure_verifier_and_reuses_result(tmp_path):
    status, prepared = cli(tmp_path, 'prepare', '--document', DOCUMENT_FILE, '--replay', REPLAY)
    assert status == 0
    args = 'process', '--job-key', prepared['job_key'], '--replay', REPLAY

    status, first = cli(tmp_path, *args)
    cached_status, cached = cli(tmp_path, *args)

    assert status == cached_status == 0
    assert first['status'] == 'complete' and first['facts']['category'] == 'daily'
    assert first['facts']['requirements']['conditions'][0]['verification'] == 'confirmed'
    assert not first['cached'] and cached['cached']
    assert first['facts'] == cached['facts']
    stored = state(tmp_path, prepared['job_key'])
    assert stored['attempts'] == 1
    assert [call['stage'] for call in stored['calls']] == ['extract', 'independent', 'compare']
    assert all(len(call['request_fingerprint']) == 64 for call in stored['calls'])


def test_cli_without_config_does_not_fall_back_to_replay(tmp_path):
    env = {name: value for name, value in os.environ.items() if name not in ENV_KEYS}
    status, result = cli(tmp_path, 'prepare', '--document', DOCUMENT_FILE, env=env)
    assert status == 2
    assert result['error_code'] == 'missing_model_configuration'
    assert not list(tmp_path.iterdir())


def test_method_change_and_content_version_use_independent_keys(tmp_path):
    worker = build_fact_worker(tmp_path, replay=REPLAY)
    original = document()
    original_key = worker.prepare(original)
    assert worker.run(original_key).state.facts.complete
    original_state = (tmp_path / original_key / 'state.json').read_bytes()
    original_input = (tmp_path / original_key / 'input.json').read_bytes()
    assert worker.prepare(original) == original_key
    assert (tmp_path / original_key / 'input.json').read_bytes() == original_input

    changed = original.model_copy(update={'content_version': 'synthetic-v2'})
    # Same input bytes have a separate task version, even before changing the model method.
    assert original.input_fingerprint == changed.input_fingerprint
    changed_key = worker.prepare(changed)
    assert changed_key != original_key
    assert worker.run(changed_key).state.error_code == 'invalid_replay'

    new_fixture = tmp_path / 'different.json'
    new_fixture.write_text(json.dumps(json.loads(REPLAY.read_text())))
    changed_method = build_fact_worker(tmp_path, replay=new_fixture)
    method_key = changed_method.prepare(original)
    assert method_key not in (original_key, changed_key)
    assert (tmp_path / original_key / 'state.json').read_bytes() == original_state
    status, failure = cli(tmp_path, 'process', '--job-key', original_key, '--replay', new_fixture)
    assert status == 2 and failure['error_code'] == 'method_mismatch'
    assert (tmp_path / original_key / 'state.json').read_bytes() == original_state


def test_large_input_is_preserved_and_has_no_generation(tmp_path, monkeypatch):
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)
    text = '超长公开正文完整保留。' * 5000
    bundle = build_document_bundle(make_artifact('document', 'long', 'v1', {
        'title': '超长正文', 'source_url': 'https://example.edu.cn/long', 'body_status': 'complete', 'content': text,
    }))
    seen = []

    def handle(request):
        assert request.url.path.endswith('/input_tokens')
        seen.append(request)
        user = json.loads(json.loads(request.content)['input'][1]['content'])
        assert user['document']['segments'][1]['text'] == text
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 12001})

    worker = build_fact_worker(tmp_path, transport=httpx.MockTransport(handle))
    key = worker.prepare(bundle)
    outcome = worker.run(key)
    assert outcome.state.status == 'incomplete' and outcome.state.error_code == 'context_limit'
    assert outcome.state.facts is None
    stored = json.loads((tmp_path / key / 'input.json').read_text())
    assert stored['document']['segments'][1]['text'] == text
    assert len(seen) == 1


def test_call_budget_survives_worker_restart_and_errors_are_sanitized(tmp_path, monkeypatch):
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)
    transport = httpx.MockTransport(failing_transport)
    key = build_fact_worker(tmp_path, transport=transport).prepare(document())
    for _ in range(16):
        result = build_fact_worker(tmp_path, transport=transport).run(key)
        assert result.state.error_code == 'model_http_failed'
    result = build_fact_worker(tmp_path, transport=transport).run(key)
    assert result.state.error_code == 'model_call_budget'
    assert result.state.status == 'incomplete'
    assert result.state.attempts == 16 and len(result.state.calls) == 16
    assert 'test-secret' not in (tmp_path / key / 'state.json').read_text()
    assert 'test-secret' not in (tmp_path / key / 'input.json').read_text()


def test_600_seconds_budget_survives_worker_restart(tmp_path, monkeypatch):
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)
    clock = [0.0]

    def handle(request):
        if not request.url.path.endswith('/input_tokens'):
            clock[0] += 60
        return failing_transport(request)

    transport = httpx.MockTransport(handle)
    key = build_fact_worker(tmp_path, transport=transport).prepare(document())
    for _ in range(10):
        build_fact_worker(tmp_path, transport=transport, clock=lambda: clock[0]).run(key)
    result = build_fact_worker(tmp_path, transport=transport, clock=lambda: clock[0]).run(key)

    assert result.state.charged_ms == 600_000
    assert result.state.error_code == 'model_time_budget'
    assert result.state.attempts == 10 and len(result.state.calls) == 10


def test_crash_retains_precharged_call_and_concurrent_process_is_excluded(tmp_path, monkeypatch):
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)
    key = build_fact_worker(tmp_path, transport=httpx.MockTransport(failing_transport)).prepare(document())
    child_code = """
import os, sys
import httpx
from campus_backend.providers import build_fact_worker

def handle(request):
    if request.url.path.endswith('/input_tokens'):
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
    print('generation entered', flush=True)
    sys.stdin.readline()
    os._exit(71)

build_fact_worker(sys.argv[1], transport=httpx.MockTransport(handle)).run(sys.argv[2])
"""
    with subprocess.Popen([sys.executable, '-c', child_code, str(tmp_path), key], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=5)
            assert child.stdout.readline().strip() == 'generation entered'
            stored = state(tmp_path, key)
            assert stored['status'] == 'running'
            assert stored['attempts'] == 1 and len(stored['calls']) == 1
            assert stored['charged_ms'] >= 60_000
            status, busy = cli(tmp_path, 'process', '--job-key', key, '--replay', REPLAY)
            assert status == 2 and busy['error_code'] == 'run_busy'
            child.communicate('crash\n', timeout=5)
            assert child.returncode == 71
        finally:
            if child.poll() is None:
                child.kill()

    result = build_fact_worker(tmp_path, transport=httpx.MockTransport(failing_transport)).run(key)
    assert result.state.attempts == 2 and len(result.state.calls) == 2
    assert result.state.charged_ms >= 60_000
    assert result.state.calls[0].elapsed_ms is None


def test_invalid_job_path_and_symlink_manifest_cannot_escape_storage(tmp_path):
    worker = build_fact_worker(tmp_path, replay=REPLAY)
    key = worker.prepare(document())
    manifest = tmp_path / key / 'input.json'
    outside = tmp_path.parent / 'external-manifest'
    outside.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(outside)

    status, result = cli(tmp_path, 'process', '--job-key', key, '--replay', REPLAY)
    assert status == 2 and result['error_code'] == 'invalid_run_storage'
    status, result = cli(tmp_path, 'process', '--job-key', '../external-manifest', '--replay', REPLAY)
    assert status == 2 and result['error_code'] == 'invalid_job_key'
    assert not (tmp_path / key / 'state.json').exists()


def test_replay_rejects_same_stage_and_document_with_wrong_request_binding(tmp_path):
    fixture = json.loads(REPLAY.read_text())
    fixture['responses'][1]['request_fingerprint'] = '0' * 64
    wrong = tmp_path / 'wrong-request.json'
    wrong.write_text(json.dumps(fixture))

    worker = build_fact_worker(tmp_path, replay=wrong)
    key = worker.prepare(document())
    result = worker.run(key)

    assert result.state.error_code == 'invalid_replay'
    assert result.state.facts is None
    assert [call.stage for call in result.state.calls] == ['extract', 'independent']


def test_unexpected_adapter_exception_persists_only_stable_code(tmp_path, monkeypatch):
    for name, value in ENV_KEYS.items():
        monkeypatch.setenv(name, value)

    def handle(request):
        raise RuntimeError('provider internal error with test-secret')

    worker = build_fact_worker(tmp_path, transport=httpx.MockTransport(handle))
    key = worker.prepare(document())
    result = worker.run(key)

    assert result.state.error_code == 'processing_failed'
    assert result.state.facts is None
    assert 'test-secret' not in (tmp_path / key / 'state.json').read_text()


def test_crashed_repair_still_consumes_the_one_repair_for_that_task(tmp_path):
    from campus_backend.classification.fact_worker import FactWorker
    from campus_backend.classification.persistence.local_runs import LocalFactRunStore
    from campus_backend.classification.run_contract import RunMethod

    method = RunMethod(provider='synthetic-replay-1', fixture_digest='a' * 64, token_counts_per_call=0)
    outputs = {entry['stage']: entry['output'] for entry in json.loads(REPLAY.read_text())['responses']}
    outputs['compare']['coverage_complete'] = False
    outputs['compare']['missing_facts'] = ['需要复核例外条件']

    class Model:
        def complete(self, request, *, timeout_seconds=60):
            return outputs[request.stage]

    worker = FactWorker(LocalFactRunStore(tmp_path), Model(), method)
    key = worker.prepare(document())
    child_code = """
import json, os, sys
from campus_backend.classification.fact_worker import FactWorker
from campus_backend.classification.persistence.local_runs import LocalFactRunStore
from campus_backend.classification.run_contract import RunMethod

outputs = json.loads(sys.argv[3])
class Model:
    def complete(self, request, *, timeout_seconds=60):
        if request.stage == 'repair':
            os._exit(72)
        return outputs[request.stage]

method = RunMethod(provider='synthetic-replay-1', fixture_digest='a' * 64, token_counts_per_call=0)
FactWorker(LocalFactRunStore(sys.argv[1]), Model(), method).run(sys.argv[2])
"""
    child = subprocess.run([sys.executable, '-c', child_code, str(tmp_path), key, json.dumps(outputs)],
                           capture_output=True, text=True, cwd=ROOT, timeout=5)
    assert child.returncode == 72

    result = worker.run(key)

    assert result.state.attempts == 2
    assert [call.stage for call in result.state.calls] == [
        'extract', 'independent', 'compare', 'repair', 'extract', 'independent', 'compare',
    ]
    assert result.state.status == 'incomplete'
    assert result.state.facts.checks.missing_facts == ('需要复核例外条件',)
    assert result.state.error_code is None


@pytest.mark.parametrize('missing_facts', [[], ['需要复核例外条件']], ids=['late-complete', 'repair-timeout'])
def test_time_budget_overrun_retains_verified_facts_and_caches_incomplete(tmp_path, missing_facts):
    from campus_backend.classification.fact_worker import FactWorker
    from campus_backend.classification.persistence.local_runs import LocalFactRunStore
    from campus_backend.classification.ports import ModelCallError
    from campus_backend.classification.run_contract import RunMethod

    method = RunMethod(provider='synthetic-replay-1', fixture_digest='a' * 64, token_counts_per_call=0)
    outputs = {entry['stage']: entry['output'] for entry in json.loads(REPLAY.read_text())['responses']}
    outputs['compare'].update(coverage_complete=not missing_facts, missing_facts=missing_facts)
    late_stage = 'repair' if missing_facts else 'compare'
    clock = [0.0]
    previous_durations = iter([60] * 9 + [59])
    called_stages = []

    class Model:
        def complete(self, request, *, timeout_seconds=60):
            called_stages.append(request.stage)
            duration = next(previous_durations, None)
            if duration is not None:
                clock[0] += duration
                raise ModelCallError('model_timeout')
            if request.stage == late_stage:
                assert timeout_seconds == 1
                clock[0] += 1.125
                if late_stage == 'repair':
                    raise ModelCallError('model_timeout')
            return outputs[request.stage]

    worker = FactWorker(LocalFactRunStore(tmp_path), Model(), method, clock=lambda: clock[0])
    key = worker.prepare(document())
    for _ in range(10):
        assert worker.run(key).state.error_code == 'model_timeout'

    first = worker.run(key)

    assert first.state.charged_ms == 600_125
    assert first.state.status == 'incomplete' and first.state.error_code == 'model_time_budget'
    assert first.state.facts is not None
    assert first.state.facts.complete == (not missing_facts)
    assert first.state.facts.checks.missing_facts == tuple(missing_facts)
    assert first.state.facts.actions[0].id == 'lecture-registration'
    assert state(tmp_path, key)['facts'] == first.state.facts.model_dump(mode='json')

    calls_before_read = called_stages.copy()
    restarted = FactWorker(LocalFactRunStore(tmp_path), Model(), method, clock=lambda: clock[0])
    cached = restarted.run(key)

    assert cached.cached
    assert cached.state == first.state
    assert called_stages == calls_before_read
