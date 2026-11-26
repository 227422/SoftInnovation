import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.facts_input import build_document_bundle


def api():
    return importlib.import_module('campus_backend.evaluation.rule_baseline')


def dataset(tmp_path, count=2):
    cases = []
    for i in range(count):
        doc = make_artifact('document', f'n{i}', 'v1', {
            'title': '校园讲座报名通知', 'content': '本科生报名截止至2026年11月20日。',
            'source_url': 'https://example.edu/notice/' + str(i),
            'body_status': 'full', 'assets': [],
        })
        data = json.dumps(doc, ensure_ascii=False).encode()
        path = tmp_path / f'{i}.json'
        path.write_bytes(data)
        bundle = build_document_bundle(doc)
        cases.append({'case_id': f'c{i}', 'group_id': f'g{i}', 'document_file': path.name,
                      'document_sha256': hashlib.sha256(data).hexdigest(),
                      'notice_id': f'n{i}', 'content_version': 'v1', 'input_fingerprint': bundle.input_fingerprint,
                      'expected': {'category': 'daily', 'labels': None}})
    return {'schema_version': 's2-rule-evaluation/1', 'dataset_id': 'synthetic-test',
            'kind': 'synthetic', 'split': 'development', 'annotation_status': 'draft', 'cases': cases}


def prediction(case, *, complete=False, labels=None):
    return {'case_id': case['case_id'], 'document_sha256': case['document_sha256'],
            'error_code': None, 'result': {
                'schema_version': 's2-rule-baseline/1', 'rules_version': 'test-v1',
                'notice_id': case['notice_id'], 'content_version': case['content_version'],
                'input_fingerprint': case['input_fingerprint'], 'category': 'daily',
                'complete': complete, 'labels': labels or [], 'gaps': [] if complete else [{'code': 'coverage_unconfirmed', 'detail': 'unresolved'}],
            }}


def label(day, audience):
    return {'kind': 'date', 'code': 'registration_deadline',
            'scope': {'action': '报名', 'track': None, 'audience': audience},
            'value': {'date': day, 'time': None},
            'evidence': [{'segment_id': 'p1', 'quote': audience + '报名'}]}


def test_missing_predictions_and_unreviewed_labels_cannot_raise_joint_score(tmp_path):
    gold = dataset(tmp_path)
    report = api().score(gold, [prediction(gold['cases'][0])])
    assert report['category'] == {'count': 1, 'total': 2, 'rate': .5}
    assert report['complete']['count'] == 0
    assert report['joint'] is None
    assert report['unannotated_label_case_ids'] == ['c0', 'c1']
    assert report['missing_prediction_ids'] == ['c1']
    assert report['release_claim'] == 'not_established'
    assert report['numeric_target_met'] is False


def test_same_kind_labels_compare_scopes_and_preserve_all_instances(tmp_path):
    gold = dataset(tmp_path, 1)
    labels = [label('2026-11-20', '本科生'), label('2026-11-21', '研究生')]
    gold['cases'][0]['expected']['labels'] = labels
    correct = prediction(gold['cases'][0], complete=True, labels=list(reversed(labels)))
    assert api().score(gold, [correct])['joint']['rate'] == 1
    correct['result']['labels'] = labels[:1]
    wrong = api().score(gold, [correct])
    assert wrong['joint']['count'] == 0
    assert wrong['failures'][0]['dimensions'] == ['labels']


def test_correct_partial_facts_do_not_count_as_complete(tmp_path):
    gold = dataset(tmp_path, 1)
    gold['cases'][0]['expected']['labels'] = []
    report = api().score(gold, [prediction(gold['cases'][0], complete=False)])
    assert report['joint']['rate'] == 1
    assert report['determinate_correct_over_all']['rate'] == 0
    assert report['numeric_target_met'] is False


@pytest.mark.parametrize('field', ['document_sha256', 'content_version', 'input_fingerprint', 'notice_id'])
def test_wrong_document_identity_cannot_be_scored(tmp_path, field):
    gold = dataset(tmp_path, 1)
    item = prediction(gold['cases'][0])
    if field == 'document_sha256':
        item[field] = '0' * 64
    else:
        item['result'][field] = 'wrong'
    with pytest.raises(ValueError):
        api().score(gold, [item])


def test_all_documents_are_checked_before_analyzer_runs(tmp_path):
    gold = dataset(tmp_path)
    (tmp_path / '1.json').write_text('changed')
    called = []
    with pytest.raises(ValueError):
        api().run_dataset(gold, tmp_path, analyzer=lambda d: called.append(d))
    assert not called


def test_reference_answers_are_not_given_to_analyzer_and_failures_remain(tmp_path):
    gold = dataset(tmp_path)
    seen = []
    def analyzer(document):
        seen.append(document.model_dump(mode='json'))
        raise RuntimeError('private exception must not be printed')
    result = api().run_dataset(gold, tmp_path, analyzer=analyzer)
    assert len(result['items']) == 2
    assert [item['error_code'] for item in result['items']] == ['processing_failed'] * 2
    assert result['report']['category']['total'] == 2
    assert result['report']['category']['count'] == 0
    assert 'private exception' not in json.dumps(result)
    assert all('expected' not in value and 'case_id' not in value for value in seen)


@pytest.mark.parametrize('mutation', ['duplicate', 'traversal', 'symlink'])
def test_invalid_manifest_paths_or_duplicate_cases_rejected(tmp_path, mutation):
    gold = dataset(tmp_path, 1)
    if mutation == 'duplicate':
        gold['cases'].append(deepcopy(gold['cases'][0]))
    elif mutation == 'traversal':
        gold['cases'][0]['document_file'] = '../outside.json'
    else:
        (tmp_path / 'link.json').symlink_to(tmp_path.parent / 'outside.json')
        gold['cases'][0]['document_file'] = 'link.json'
    with pytest.raises(ValueError):
        api().run_dataset(gold, tmp_path)


def test_offline_real_analyzer_and_output_protection(tmp_path, capsys):
    gold = dataset(tmp_path, 1)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(gold))
    output = tmp_path / 'report.json'
    assert api().main([str(manifest), '--documents-dir', str(tmp_path), '--output', str(output)]) == 0
    result = json.loads(output.read_text())
    assert result['items'][0]['result']['category'] == 'daily'
    assert result['items'][0]['result']['rules_version']
    assert result['report']['joint'] is None
    original = manifest.read_bytes()
    assert api().main([str(manifest), '--documents-dir', str(tmp_path), '--output', str(manifest)]) == 2
    assert manifest.read_bytes() == original
    assert api().main([str(manifest), '--documents-dir', str(tmp_path), '--output', str(tmp_path / '0.json')]) == 2


def test_protects_input_even_through_output_symlink(tmp_path):
    gold = dataset(tmp_path, 1)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(gold))
    output = tmp_path / 'alias.json'
    output.symlink_to(tmp_path / '0.json')
    before = (tmp_path / '0.json').read_bytes()
    assert api().main([str(manifest), '--documents-dir', str(tmp_path), '--output', str(output)]) == 2
    assert (tmp_path / '0.json').read_bytes() == before


def test_prepare_keeps_unannotated_samples_and_verifies_snapshot_hashes(tmp_path):
    gold = dataset(tmp_path)
    index = {'items': [{key: value for key, value in case.items()
                        if key not in ('expected', 'notice_id', 'content_version', 'input_fingerprint')}
                       for case in gold['cases']]}
    references = {'schema_version': 's2-category-reference/1', 'annotation_status': 'independent_ai_draft',
                  'cases': [{'case_id': 'c0', 'group_id': 'shared', 'category': 'daily',
                             'reason': 'test reference', 'evidence': [], 'needs_review': True}]}
    prepared = api().prepare_dataset(index, references, tmp_path, dataset_id='dev')
    assert prepared['cases'][0]['group_id'] == 'shared'
    assert prepared['cases'][0]['expected'] == {'category': 'daily', 'labels': None}
    assert prepared['cases'][1]['expected'] is None
    assert prepared['annotation_status'] == 'independent_ai_draft'
    (tmp_path / '1.json').write_text('tampered')
    with pytest.raises(ValueError):
        api().prepare_dataset(index, references, tmp_path, dataset_id='dev')


def test_prepare_rejects_duplicate_or_extra_reference_case(tmp_path):
    gold = dataset(tmp_path, 1)
    index = {'items': gold['cases']}
    ref = {'case_id': 'c0', 'group_id': 'g0', 'category': 'daily'}
    for refs in ([ref, ref], [{**ref, 'case_id': 'extra'}]):
        with pytest.raises(ValueError):
            api().prepare_dataset(index, {'cases': refs}, tmp_path, dataset_id='dev')
