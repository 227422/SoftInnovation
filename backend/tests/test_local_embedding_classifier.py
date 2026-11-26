from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/quality'))


def test_views_preserve_student_action_in_a_long_sports_notice():
    from v11_embedding import views
    headline = '体育科技作品比赛通知'
    text = ('一般说明。' * 100 + '申请对象为本科生，须提交训练器材设计作品。'
            + '其他提示。' * 100 + '最终评审作品并公布结果。')
    full, action = views(headline, text)
    assert headline in full and headline in action
    assert '申请对象为本科生' in action and '设计作品' in action
    assert '最终评审作品' in full


def test_candidate_input_contains_no_collector_metadata():
    from v3_classifier import validate_inputs
    with pytest.raises(ValueError):
        validate_inputs([dict(case_id='x', title='t', body='b', reference_category='daily')])


def test_snapshot_requires_the_registered_model_files():
    from v11_embedding import check_source
    with pytest.raises(ValueError):
        check_source(ROOT, {'revision': 'wrong', 'files': {}})


def test_two_embedding_heads_learn_and_reload_without_object_serialization(tmp_path):
    import os
    import subprocess
    runtime = os.environ.get('ML_PYTHON')
    if not runtime:
        pytest.skip('requires project ML runtime')
    check = """
import sys
import numpy as np
from v11_embedding import fit, probabilities
rng = np.random.default_rng(114)
labels = np.repeat(np.arange(4), 10)
x = rng.normal(size=(40, 2, 16)) * .1
for i, label in enumerate(labels):
    x[i, :, label*4:label*4+4] += 1
x /= np.linalg.norm(x, axis=2, keepdims=True)
params = fit(x, labels)
np.savez_compressed(sys.argv[1], **params)
with np.load(sys.argv[1], allow_pickle=False) as saved:
    p = probabilities(x, saved)
assert np.allclose(p.sum(axis=1), 1) and np.array_equal(p.argmax(axis=1), labels)
assert np.allclose(p[::-1], probabilities(x[::-1], params))
"""
    subprocess.run([runtime, '-c', check, str(tmp_path / 'heads.npz')],
                   cwd=ROOT / 'scripts/quality', check=True, timeout=60)


def test_text_encoder_can_be_reproduced_from_a_pinned_source():
    import json
    from v11_embedding import FILES, REVISION
    source = json.loads((ROOT / 'docs/quality/training/v11-embedding-source.json').read_bytes())
    assert source['revision'] == REVISION and source['license'] == 'apache-2.0'
    assert set(source['source_sha256']) == FILES
    assert all(len(digest) == 64 for digest in source['source_sha256'].values())


def test_published_embedding_experiment_keeps_development_and_formal_results_separate():
    import hashlib
    import json
    folder = ROOT / 'docs/quality/training'
    report = json.loads((folder / 'v11-model-development.json').read_bytes())
    extra = json.loads((folder / 'v11-model-extra59.json').read_bytes())
    manifest = folder / 'v11-model-development-only.json'
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == report['manifest_sha256'] == extra['manifest_sha256']
    assert not report['promoted'] and not report['seen_new_school_holdout'] and not extra['count_for_milestones']
    assert report['results']['guard']['chosen']['correct'] == 319
    assert report['results']['guard']['document']['correct'] == 311
    assert report['results']['guard']['chosen']['total'] == 336
    assert report['results']['hard77']['chosen']['correct'] == 70
    assert extra['scores']['chosen']['correct'] == 46 and extra['scores']['chosen']['total'] == 59
    assert extra['reload_count'] == 7 and extra['reload_same_categories']
    protocol = folder / 'v11-embedding-protocol.json'
    assert report['protocol_sha256'] == hashlib.sha256(protocol.read_bytes()).hexdigest()


def test_development_reports_are_discoverable_from_project_handoffs():
    report = ROOT / 'docs/verification/s2/multischool-classifier-stages-2026-11-18.md'
    text = report.read_text()
    for name in ('v10-model-method.md', 'v11-model-method.md', 'sealed-eighth-receipt.json'):
        assert name in text
    for prefix in ('07', '08', '09', '10'):
        assert str(report.relative_to(ROOT)) in next(ROOT.glob(prefix + '_*.md')).read_text()


def test_transfer_error_overlap_reconciles_with_all_three_frozen_models():
    import json
    folder = ROOT / 'docs/quality/training'
    proof = json.loads((folder / 'role-model-error-overlap.json').read_bytes())
    guard = proof['totals']['guard']
    errors = proof['guard_cases_where_any_was_wrong']
    assert guard['by_number_correct'] == [11, 4, 11, 310]
    assert not proof['prospective_milestone'] and sum(guard['by_number_correct']) == guard['total'] == 336
    assert len(errors) == len({r['case_id'] for r in errors}) == 26
    for name in ('v10', 'v10b', 'v11'):
        import hashlib
        manifest = folder / (name + '-model-development-only.json')
        assert proof['manifest_sha256'][name] == hashlib.sha256(manifest.read_bytes()).hexdigest()
        report = json.loads((folder / (name + '-model-development.json')).read_bytes())
        metric = report['results']['guard']
        s = metric.get('scores', metric)['chosen']
        assert s['correct'] == guard['by_number_correct'][3] + sum(r[name] == r['reference'] for r in errors)
