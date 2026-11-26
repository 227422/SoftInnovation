"""Keep the local training pilot separate from fresh acceptance testing."""
import hashlib
import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/quality/small_classifier_experiment.py'


@pytest.fixture
def api():
    assert SCRIPT.is_file(), 'The isolated training experiment runner must exist'
    return runpy.run_path(str(SCRIPT))


def row(i, school='甲校', label='daily', **changes):
    return dict(case_id=str(i), university=school, title='选课通知',
                body=f'本科生办理选课事项，编号{i}。', label=label,
                family_key=f'family-{i}', url=f'https://example.edu.cn/{i}',
                body_sha256=f'hash-{i}') | changes


def test_reference_and_body_hashes_are_verified(api, tmp_path):
    body = tmp_path / 'body.txt'
    body.write_text('完整本科生通知')
    record = row(1)
    record.pop('body')
    record['body_path'] = 'body.txt'
    record['body_sha256'] = hashlib.sha256(body.read_bytes()).hexdigest()
    record['reference_category'] = record.pop('label')
    record['reference_status'] = 'complete'
    reference = tmp_path / 'references.json'
    reference.write_text(json.dumps([record]))
    checksum = hashlib.sha256(reference.read_bytes()).hexdigest()
    assert api['load_corpus'](reference, checksum, tmp_path)[0]['body'] == '完整本科生通知'
    body.write_text('被替换的输入')
    with pytest.raises(ValueError, match='body.*sha256'):
        api['load_corpus'](reference, checksum, tmp_path)
    with pytest.raises(ValueError, match='reference.*sha256'):
        api['load_corpus'](reference, '0' * 64, tmp_path)


def test_school_split_is_exhaustive_and_disjoint(api):
    rows = [row(1, '甲'), row(2, '乙'), row(3, '丙')]
    split = {'train': ['甲'], 'validation': ['乙'], 'test': ['丙']}
    assert [r['case_id'] for r in api['split_records'](rows, split)['test']] == ['3']
    with pytest.raises(ValueError, match='school'):
        api['split_records'](rows, split | {'test': ['甲', '丙']})
    with pytest.raises(ValueError, match='school'):
        api['split_records'](rows + [row(4, '丁')], split)


@pytest.mark.parametrize('field', ['case_id', 'url', 'family_key', 'body_sha256'])
def test_cross_split_duplicate_identity_is_rejected(api, field):
    a, b = row(1, '甲'), row(2, '乙')
    b[field] = a[field]
    with pytest.raises(ValueError, match='duplicate|overlap'):
        api['split_records']([a, b, row(3, '丙')],
                             {'train': ['甲'], 'validation': ['乙'], 'test': ['丙']})


def test_near_duplicate_body_cannot_cross_split(api):
    body = '本科生创新研究项目申报细则与竞赛报名事项' * 15
    split = {'train': [row(1, '甲', body=body)], 'validation': [row(2, '乙', body=body + '更新')], 'test': []}
    with pytest.raises(ValueError, match='near.duplicate'):
        api['audit_similarity'](split, {'shingle_size': 5, 'jaccard_threshold': .25,
                                     'containment_threshold': .70, 'minimum_normalized_chars': 50})


def test_model_input_drops_reference_reasons_and_metadata(api):
    record = row(1, reference_reason='答案线索', reference_evidence='泄漏', school_domain='x')
    assert set(api['model_examples']([record])[0]) == {'case_id', 'title', 'body', 'label'}


def test_missing_and_unknown_predictions_stay_in_denominator(api):
    records = [row(i) for i in range(20)]
    prediction = [{'case_id': str(i), 'prediction': 'daily'} for i in range(19)]
    result = api['score_predictions'](records, prediction)
    assert result['overall'] == {'total': 20, 'correct': 19, 'accuracy': .95, 'exceeds_95': False}
    assert result['confusion_matrix']['daily']['error'] == 1
    assert result['formal_s2_acceptance'] is False
    prediction.append({'case_id': '19', 'prediction': 'unknown'})
    assert api['score_predictions'](records, prediction)['overall']['correct'] == 19


def test_duplicate_predictions_fail_instead_of_last_write_wins(api):
    with pytest.raises(ValueError, match='duplicate'):
        api['score_predictions']([row(1)], [{'case_id': '1', 'prediction': 'daily'}] * 2)


def test_selection_uses_only_validation_and_prefers_lighter_tie(api):
    records = [row(1), row(2, label='excluded')]
    good = [{'case_id': '1', 'prediction': 'daily'}, {'case_id': '2', 'prediction': 'excluded'}]
    candidates = [dict(candidate_id='bert-1', kind='bert', validation_predictions=good,
                       test_accuracy=1),
                  dict(candidate_id='svm-1', kind='svm', validation_predictions=good,
                       test_accuracy=0)]
    result = api['select_candidate'](candidates, records)
    assert result['selected_candidate_id'] == 'svm-1'
    assert result['selection_basis'] == 'validation_only'


def test_evaluation_is_once_and_checks_frozen_artifact_before_predicting(api, tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'weights.json').write_text('{}')
    selection = dict(selected_candidate_id='svm-1', candidates=[dict(candidate_id='svm-1',
        artifact_dir=str(model), artifact_sha256=api['artifact_hashes'](model))])
    calls = []
    def predictor(_path, examples):
        assert all('label' not in r and 'university' not in r for r in examples)
        calls.append(True)
        return [{'case_id': r['case_id'], 'prediction': 'daily'} for r in examples]
    out = tmp_path / 'test-result.json'
    result = api['evaluate_once'](selection, [row(1)], predictor, out)
    assert result['models']['svm-1']['overall']['correct'] == 1
    with pytest.raises(FileExistsError):
        api['evaluate_once'](selection, [row(1)], predictor, out)
    assert len(calls) == 1
    (model / 'weights.json').write_text('changed')
    with pytest.raises(ValueError, match='artifact'):
        api['evaluate_once'](selection, [row(1)], predictor, tmp_path / 'second.json')
    assert len(calls) == 1


def test_artifact_symlink_is_rejected(api, tmp_path):
    target = tmp_path / 'original'
    target.write_text('weights')
    folder = tmp_path / 'artifact'
    folder.mkdir()
    (folder / 'weights').symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        api['artifact_hashes'](folder)
