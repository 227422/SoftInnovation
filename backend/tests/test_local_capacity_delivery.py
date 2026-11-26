"""Keep the capacity evidence separate from model quality and deployment claims."""
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'docs/verification/local-host'


def test_capacity_snapshot_has_real_overlapping_requests_and_consistent_memory():
    report = json.loads((FOLDER / 'capacity-2026-11-18.json').read_text())
    assert report['status'] == 'passed'
    assert report['total_phase_api_requests'] == sum(p['requests']['total'] for p in report['phases'])
    assert report['total_phase_api_successful_200'] == report['total_phase_api_requests']
    measured = [p for p in report['phases'] if 'inference_latency' in p]
    assert {p['sequence_length_tokens'] for p in measured} == {128, 512}
    for phase in measured:
        assert phase['outputs_finite'] is True
        assert phase['measured_runs'] == len(phase['inference_latency_ms_samples'])
        requests = phase['requests']
        assert requests['overlapping_measured_forward_pass_total'] > 0
        assert requests['overlapping_measured_forward_pass_total'] == requests['overlapping_measured_forward_pass_successful_200']
    samples = report['memory_samples']
    assert all(s['combined_rss_bytes'] == s['backend_rss_bytes'] + s['probe_model_rss_bytes'] for s in samples)
    assert report['overall_memory']['combined_rss_MiB']['peak'] == round(max(s['combined_rss_bytes'] for s in samples) / 1024**2, 3)
    assert all(report['cleanup'].values())


def test_capacity_report_preserves_scope_and_sanitizes_credentials():
    text = (FOLDER / 'capacity-2026-11-18.json').read_text()
    report = json.loads(text)
    assert report['source_kind'] == 'synthetic_runtime'
    assert report['execution']['bound_host'] == '127.0.0.1'
    assert report['model']['device_used'] == 'cpu'
    assert report['model']['trust_remote_code'] is False
    assert report['model']['format'] == 'safetensors'
    assert 'untrained-for-this-project' in report['model']['task']
    limits = ' '.join(report['limitations'])
    for phrase in ('No OCR concurrency', '95% target', 'client scheduling', 'not all-day'):
        assert phrase in limits
    for secret in ('csrf_token', 'campus_session', 'capacity-probe@example.com', 'Set-Cookie'):
        assert secret not in text


def test_capacity_evidence_is_bound_to_the_archived_probe():
    manifest = json.loads((FOLDER / 'evidence-manifest.json').read_text())
    for name, expected in manifest['files_sha256'].items():
        assert hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() == expected
    assert not list(FOLDER.glob('*.safetensors'))
    assert not list(FOLDER.glob('*.db'))


@pytest.mark.parametrize('name', [
    '07_本科生首版范围与开发顺序.md', '08_模块实现与前后端接口规范.md',
    '09_开发问题与处理规范.md', '10_交付前端的首版修正说明.md',
])
def test_four_execution_documents_link_the_capacity_result(name):
    document = (ROOT / name).read_text()
    assert 'docs/verification/local-host/capacity-2026-11-18.md' in document
    assert 'M4' in document
    assert (FOLDER / 'capacity-2026-11-18.md').exists()
