"""Second-round claims must keep the new-test denominator and pre-test selection."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'docs/quality/training'
CORPUS = ROOT / 'docs/quality/corpus/daily-v2-2026-11-18'
PREFIX = 'daily-v2-2026-11-18'


def read(path):
    return json.loads(path.read_text())


def test_new_corpus_is_frozen_and_test_schools_were_never_development():
    config = read(FOLDER / (PREFIX + '.protocol.json'))
    split = read(FOLDER / (PREFIX + '.split.json'))
    old = read(ROOT / config['prior_reference_path'])
    new = read(CORPUS / 'references.json')
    test = read(CORPUS / 'test-references.json')
    assert len(new) == 420 and len(test) == 240
    assert set(config['schools']['test']).isdisjoint({r['university'] for r in old})
    assert {r['case_id'] for r in test} == {r['case_id'] for r in split['records'] if r['split'] == 'test'}
    assert len({r['family_key'] for r in test}) == 240
    assert len({r['university'] for r in test}) == 12
    assert sum(r['reference_category'] == 'daily' for r in test) == 96
    assert split['corpus_audit']['old_corpus_is_development'] is True
    assert 'v2-n-129' not in {r['case_id'] for r in new}
    for name, expected in read(CORPUS / 'freeze.json')['files_sha256'].items():
        assert hashlib.sha256((CORPUS / name).read_bytes()).hexdigest() == expected


def test_new_results_recompute_from_all_240_cases_and_keep_validation_selection(monkeypatch):
    result = read(FOLDER / (PREFIX + '.results.json'))
    selection = read(FOLDER / (PREFIX + '.selection.json'))
    split = read(FOLDER / (PREFIX + '.split.json'))
    test = [r for r in split['records'] if r['split'] == 'test']
    monkeypatch.syspath_prepend(str(ROOT / 'scripts/quality'))
    score = runpy.run_path(str(ROOT / 'scripts/quality/expanded_classifier_experiment.py'))['fresh_score']
    assert result['selection_basis'] == 'validation_only'
    assert result['selected_candidate_id'] == selection['selected_candidate_id']
    assert datetime.fromisoformat(selection['frozen_before_test_at']) < datetime.fromisoformat(result['evaluated_at'])
    assert result['selection_sha256'] == hashlib.sha256((FOLDER/(PREFIX+'.selection.json')).read_bytes()).hexdigest()
    for candidate in [*result['models'].values(), result['rule_baseline']]:
        recalculated = score(test, candidate['cases'])
        for key in ['overall', 'daily', 'included', 'classification_target_met', 'formal_s2_acceptance']:
            assert candidate[key] == recalculated[key]
        assert candidate['overall']['total'] == 240
        assert candidate['daily']['total'] == 96
        assert candidate['formal_s2_acceptance'] is False


def test_v2_delivery_binds_actual_learning_and_documents_only_local_experiment():
    report = read(FOLDER / (PREFIX + '.delivery.json'))
    assert report['training_completed'] is True
    assert report['tags_trained'] is report['production_integrated'] is False
    assert report['bert_recipes_completed'] == ['warm-last2', 'fresh-last4']
    assert report['new_test_evaluation_count'] == 1
    for name, sha in report['files_sha256'].items():
        assert hashlib.sha256((FOLDER/name).read_bytes()).hexdigest() == sha
    for recipe in report['bert_recipes_completed']:
        proof = report['learning_evidence'][recipe]
        assert proof['encoder_updated'] and proof['head_updated'] and proof['frozen_layers_unchanged']


@pytest.mark.parametrize('name', [
    '07_本科生首版范围与开发顺序.md', '08_模块实现与前后端接口规范.md',
    '09_开发问题与处理规范.md', '10_交付前端的首版修正说明.md',
])
def test_v2_report_link_and_scope_are_synchronized(name):
    text = (ROOT/name).read_text()
    assert 'docs/verification/s2/daily-classifier-v2-2026-11-18.md' in text
    assert '标签' in text and '类别' in text


def test_career_competition_clarification_preserves_historical_reference():
    old_test = read(CORPUS / 'test-references.json')
    assert next(r for r in old_test if r['case_id'] == 'v2-e-235')['reference_category'] == 'daily'
    change = read(FOLDER / 'career-competition-clarification.json')
    assert change['development_overrides'] == {'v2-e-235': 'research_innovation'}
    assert change['historical_score'] == {'correct': 224, 'total': 240}
    for name in ['07_本科生首版范围与开发顺序.md','08_模块实现与前后端接口规范.md',
                 '09_开发问题与处理规范.md','10_交付前端的首版修正说明.md']:
        assert '职业规划大赛' in (ROOT / name).read_text()
