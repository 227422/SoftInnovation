"""A trained checkpoint and an exploratory score must not become an S2 claim."""
import hashlib
import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'docs/quality/training'


def test_committed_training_results_keep_holdout_and_rule_denominators():
    path = FOLDER / 'multischool-pilot-2026-11-18.results.json'
    assert path.exists(), 'The real frozen evaluation results must be delivered'
    result = json.loads(path.read_text())
    split = json.loads((FOLDER / 'multischool-pilot-2026-11-18.split.json').read_text())
    tests = [r for r in split['records'] if r['split'] == 'test']
    scorer = runpy.run_path(str(ROOT / 'scripts/quality/small_classifier_experiment.py'))['score_predictions']
    assert len(tests) == 60
    assert result['formal_s2_acceptance'] is False
    assert result['selection_basis'] == 'validation_only'
    for score in [*result['models'].values(), result['historical_rule_baseline']]:
        assert score['overall'] == scorer(tests, score['cases'])['overall']
        assert score['included']['total'] == 45
        assert set(score['by_school']) == set(split['schools']['test'])
        assert score['formal_s2_acceptance'] is False


def test_training_manifest_binds_learning_evidence_without_private_payloads():
    path = FOLDER / 'multischool-pilot-2026-11-18.delivery.json'
    assert path.exists(), 'The delivered report must bind its files and actual training'
    evidence = json.loads(path.read_text())
    assert evidence['production_integrated'] is False
    assert evidence['tags_trained'] is False
    assert evidence['training_completed'] is True
    assert evidence['bert_encoder_updated'] is True
    assert evidence['bert_head_updated'] is True
    assert evidence['bert_frozen_layers_unchanged'] is True
    for filename, expected in evidence['files_sha256'].items():
        assert hashlib.sha256((FOLDER / filename).read_bytes()).hexdigest() == expected
    assert not list(FOLDER.glob('*.safetensors'))
    assert not list(FOLDER.glob('*.npz'))


@pytest.mark.parametrize('name', [
    '07_本科生首版范围与开发顺序.md', '08_模块实现与前后端接口规范.md',
    '09_开发问题与处理规范.md', '10_交付前端的首版修正说明.md',
])
def test_training_status_is_synchronized(name):
    text = (ROOT / name).read_text()
    assert 'docs/verification/s2/small-classifier-2026-11-18.md' in text
    assert '类别' in text and '标签' in text
