"""Second-round data must be genuinely new and keep failed cases in its score."""
import hashlib
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/quality/expanded_classifier_experiment.py'


@pytest.fixture
def api(monkeypatch):
    assert SCRIPT.exists(), 'The expanded experiment runner is required'
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    return runpy.run_path(str(SCRIPT))


def protocol():
    return dict(categories=['research_innovation', 'financial_aid', 'daily', 'excluded'],
                schools={'train': ['旧训练校'], 'validation': ['旧验证校'], 'test': ['新校']},
                new_per_school={'train': {'daily': 1}, 'validation': {'excluded': 1},
                                'test': {'daily': 1, 'excluded': 1}},
                targets={'fresh_test_schools': 1, 'new_train': 1, 'new_validation': 1, 'new_test': 2})


def row(i, school, label='daily', split=None):
    result = dict(case_id=str(i), university=school, reference_category=label,
                  label=label, title='通知', body=f'原文内容{i}', family_key=f'f-{i}',
                  body_sha256=f'h-{i}', url=f'https://example.edu.cn/{i}')
    if split:
        result['assigned_split'] = split
    return result


def samples():
    old = [row(1, '旧训练校'), row(2, '旧验证校')]
    new = [row(3, '旧训练校', split='train'),
           row(4, '旧验证校', 'excluded', 'validation'),
           row(5, '新校', split='test'), row(6, '新校', 'excluded', 'test')]
    return old, new


def test_old_test_may_be_development_but_new_test_schools_are_unseen(api):
    old, new = samples()
    grouped, audit = api['combine_corpus'](old, new, protocol())
    assert [r['case_id'] for r in grouped['test']] == ['5', '6']
    assert audit['old_corpus_is_development'] is True
    assert audit['fresh_test_has_old_school'] is False
    changed = protocol()
    changed['schools']['test'].append('旧训练校')
    with pytest.raises(ValueError, match='school'):
        api['combine_corpus'](old, new, changed)


def test_new_quotas_and_assigned_split_cannot_be_silently_changed(api):
    old, new = samples()
    with pytest.raises(ValueError, match='quota'):
        api['combine_corpus'](old, new[:-1], protocol())
    new[-1]['assigned_split'] = 'train'
    with pytest.raises(ValueError, match='assigned_split'):
        api['combine_corpus'](old, new, protocol())


def test_repeated_old_notice_cannot_count_as_new_sample(api):
    old, new = samples()
    new[0]['url'] = old[0]['url']
    with pytest.raises(ValueError, match='duplicate|overlap'):
        api['combine_corpus'](old, new, protocol())


def test_base_artifact_files_are_checked_before_training(api, tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    (model / 'config.json').write_text('{}')
    expected = {'config.json': hashlib.sha256(b'{}').hexdigest()}
    api['verify_files'](model, expected)
    (model / 'config.json').write_text('changed')
    with pytest.raises(ValueError, match='sha256'):
        api['verify_files'](model, expected)
    with pytest.raises(ValueError, match='outside|relative'):
        api['verify_files'](model, {'../outside': '0' * 64})


def test_strict_gate_keeps_unknown_and_daily_failures_visible(api):
    records = [row(i, '学校' + str(i % 12), 'daily' if i < 96 else 'research_innovation' if i < 144 else 'financial_aid' if i < 192 else 'excluded') for i in range(240)]
    predictions = [{'case_id': str(i), 'prediction': r['label'] if i < 228 else 'unknown'}
                   for i, r in enumerate(records)]
    result = api['fresh_score'](records, predictions, min_schools=12, min_families=200)
    assert result['overall']['accuracy'] == .95
    assert result['classification_target_met'] is False
    assert result['daily']['total'] == 96
    predictions[-1]['prediction'] = 'excluded'
    result = api['fresh_score'](records, predictions, min_schools=12, min_families=200)
    assert result['overall']['correct'] == 229
    assert result['classification_target_met'] is True
    assert result['formal_s2_acceptance'] is False


def test_small_or_repeated_family_test_cannot_pass_gate(api):
    records = [row(i, '新校') for i in range(20)]
    predictions = [{'case_id': r['case_id'], 'prediction': r['label']} for r in records]
    result = api['fresh_score'](records, predictions, min_schools=12, min_families=200)
    assert result['overall']['accuracy'] == 1
    assert result['classification_target_met'] is False
    records[1]['family_key'] = records[0]['family_key']
    with pytest.raises(ValueError, match='family'):
        api['fresh_score'](records, predictions)


def test_verify_frozen_inputs_checks_every_file(api, tmp_path):
    (tmp_path / 'train.json').write_text('[]')
    manifest = {'files_sha256': {'train.json': hashlib.sha256(b'[]').hexdigest()}}
    api['verify_prepared'](tmp_path, manifest, ('train',))
    (tmp_path / 'train.json').write_text('[1]')
    with pytest.raises(ValueError, match='sha256'):
        api['verify_prepared'](tmp_path, manifest, ('train',))


def test_quarantine_keeps_test_and_removes_only_development_copies(api):
    a, b, c = row(1, '训练校'), row(2, '验证校'), row(3, '测试校')
    for r in (a, b, c):
        r['body'] = '这是独立于模型预测的完全相同通知正文。' * 8
    splits, audit = api['quarantine_similarity'](
        {'train': [a, row(4, '训练校')], 'validation': [b, row(5, '验证校')], 'test': [c]},
        {'shingle_size': 5, 'minimum_normalized_chars': 50,
         'jaccard_threshold': .25, 'containment_threshold': .7})
    assert [r['case_id'] for r in splits['test']] == ['3']
    assert audit['quarantined_case_ids'] == ['1', '2']
    assert [r['case_id'] for r in splits['train']] == ['4']


def test_per_school_override_is_explicit_and_cannot_change_total(api):
    old, new = samples()
    config = protocol()
    config['new_school_quotas'] = {'旧训练校': {'daily': 2}}
    with pytest.raises(ValueError, match='quota'):
        api['combine_corpus'](old, new, config)


def test_perfect_results_without_all_four_classes_cannot_pass(api):
    records = [row(i, '学校' + str(i % 12)) for i in range(240)]
    result = api['fresh_score'](records, [{'case_id': r['case_id'], 'prediction': 'daily'} for r in records])
    assert result['overall']['accuracy'] == 1
    assert result['classification_target_met'] is False


def test_prepare_rejects_reference_or_raw_tampering_before_creating_output(api, tmp_path, monkeypatch):
    old, new = samples()
    # Exercise actual on-disk reference/body/raw verification, not a mocked training score.
    for r in old + new:
        body = tmp_path / (r['case_id'] + '.txt')
        body.write_text(r.pop('body'))
        r.update(body_path=str(body), body_sha256=hashlib.sha256(body.read_bytes()).hexdigest(),
                 reference_status='complete')
        raw = tmp_path / (r['case_id'] + '.html')
        raw.write_text('<main>' + r['case_id'] + '</main>')
        r.update(raw_path=str(raw), raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
    old_path, new_path = tmp_path/'old.json', tmp_path/'new.json'
    old_path.write_text(json.dumps(old)); new_path.write_text(json.dumps(new))
    config = protocol() | dict(prior_reference_path=str(old_path),
        prior_reference_sha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
        experiment_id='tiny', similarity=dict(shingle_size=5, minimum_normalized_chars=50,
                                            jaccard_threshold=.25, containment_threshold=.7))
    cp = tmp_path/'config.json'; cp.write_text(json.dumps(config))
    api['prepare'].__globals__['ROOT'] = tmp_path
    Path(new[0]['raw_path']).write_text('changed')
    with pytest.raises(ValueError, match='raw sha256'):
        api['prepare'](cp, new_path, hashlib.sha256(new_path.read_bytes()).hexdigest(), tmp_path/'prepared')
    assert not (tmp_path/'prepared').exists()


def test_evaluation_cannot_be_repeated_and_prediction_failures_remain_errors(api, tmp_path, monkeypatch):
    import sys
    import types
    folder, output = tmp_path/'prepared', tmp_path/'run'
    folder.mkdir(); output.mkdir()
    test = [row(i, '新校'+str(i%2), label) for i,label in enumerate(protocol()['categories'])]
    config = dict(minimum_test_schools=2, minimum_test_families=4, reference_kind='test_fixture')
    cp=tmp_path/'protocol.json'; cp.write_text(json.dumps(config))
    (folder/'test.json').write_text(json.dumps(test))
    manifest = dict(config_sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),
        files_sha256={'test.json':hashlib.sha256((folder/'test.json').read_bytes()).hexdigest()},
        records=[r | {'split':'test'} for r in test])
    (folder/'manifest.json').write_text(json.dumps(manifest))
    model=tmp_path/'model'; model.mkdir(); (model/'model.json').write_text('{}')
    selection=dict(config_sha256=manifest['config_sha256'],
        dataset_manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
        code_sha256=api['source_hashes'](), selected_candidate_id='chosen',
        test_candidates=[dict(candidate_id='chosen', artifact_dir=str(model), artifact_sha256=api['artifact_hashes'](model))])
    (output/'selection.json').write_text(json.dumps(selection))
    calls=[]
    def fail(path, examples):
        assert all(set(e)=={'case_id','title','body'} for e in examples)
        calls.append(examples)
        raise RuntimeError('model failed')
    monkeypatch.setitem(sys.modules, 'small_classifier_models', types.SimpleNamespace(predict_saved=fail))
    result=api['evaluate'](cp,folder,output)
    assert result['models']['chosen']['overall']==dict(total=4,correct=0,accuracy=0,exceeds_95=False)
    assert result['models']['chosen']['prediction_failure']=='RuntimeError'
    with pytest.raises(FileExistsError): api['evaluate'](cp,folder,output)
    assert len(calls)==1


def test_embedded_source_integrity_is_checked_not_only_wrapper_html(api, tmp_path):
    wrapper, attachment = tmp_path/'article.html', tmp_path/'main.pdf'
    wrapper.write_bytes(b'wrapper'); attachment.write_bytes(b'pdf original')
    rows=[dict(case_id='pdf-1', raw_path=str(wrapper), raw_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
               embedded_documents=[dict(raw_path=str(attachment),sha256=hashlib.sha256(attachment.read_bytes()).hexdigest())])]
    api['verify_reference_materials'](rows, tmp_path)
    attachment.write_bytes(b'changed')
    with pytest.raises(ValueError, match='sha256'):
        api['verify_reference_materials'](rows, tmp_path)
    rows[0]['embedded_documents'][0]['raw_path']='/outside.pdf'
    with pytest.raises(ValueError, match='outside'):
        api['verify_reference_materials'](rows, tmp_path)


def test_base_model_rejects_unfrozen_tokenizer_sidecars(api, tmp_path):
    model=tmp_path/'model';model.mkdir();(model/'vocab.txt').write_bytes(b'known')
    expected={'vocab.txt':hashlib.sha256(b'known').hexdigest()}
    (model/'special_tokens_map.json').write_text('{}')
    with pytest.raises(ValueError, match='inventory|unmanifested'):
        api['verify_files'](model, expected, exact=True)


def test_loaded_manifest_cannot_change_during_training(api, tmp_path, monkeypatch):
    import sys
    import types
    folder=tmp_path/'prepared';folder.mkdir()
    config=dict(recipes=[dict(config=dict(linear_c_values=[1]))])
    cp=tmp_path/'protocol.json';cp.write_text(json.dumps(config))
    rows=[row(i,'训练校',label) for i,label in enumerate(protocol()['categories'])]
    for name in ['train','validation']:(folder/(name+'.json')).write_text(json.dumps(rows))
    manifest=dict(config_sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),
        files_sha256={n+'.json':hashlib.sha256((folder/(n+'.json')).read_bytes()).hexdigest() for n in ['train','validation']})
    mp=folder/'manifest.json';mp.write_text(json.dumps(manifest))
    predictions=[dict(case_id=r['case_id'],prediction=r['label']) for r in rows]
    def train(train,validation,out,flat,c):
        out.mkdir();(out/'model.json').write_text('{}')
        changed=json.loads(mp.read_text());changed['records']=[{'wrong':'metadata'}];mp.write_text(json.dumps(changed))
        return dict(candidate_id='tiny',kind='svm',artifact_dir=str(out),validation_predictions=predictions)
    monkeypatch.setitem(sys.modules,'small_classifier_models',types.SimpleNamespace(
        normalized_config=lambda c:c,train_linear=train,train_bert=None,predict_saved=lambda *args:predictions))
    with pytest.raises(ValueError,match='manifest.*sha256|manifest changed'):
        api['train_recipe'](cp,folder,tmp_path/'run','linear')
    assert not (tmp_path/'run/linear/candidates.json').exists()
