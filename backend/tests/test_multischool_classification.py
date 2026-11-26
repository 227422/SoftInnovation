"""The cross-school diagnostic must not hide wrong or unavailable predictions."""
import hashlib
import json
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/quality/multischool_classification.py'


@pytest.fixture
def evaluator():
    assert SCRIPT.is_file(), 'Cross-school frozen evaluation runner must exist'
    return runpy.run_path(str(SCRIPT))


def case(tmp_path, index=0, category='daily', **updates):
    body = tmp_path / f'body-{index}.txt'
    body.write_text('面向全体本科生，选课时间为下周一。')
    row = dict(case_id=f'case-{index}', university=f'学校{index % 2}',
               school_domain='example.edu.cn', url=f'https://example.edu.cn/{index}',
               title='本科生选课通知', body_path=body.name,
               body_sha256=hashlib.sha256(body.read_bytes()).hexdigest(),
               family_key=f'unique-event-{index}', reference_category=category,
               reference_status='complete', reference_reason='学生需办理选课',
               reference_evidence='面向全体本科生')
    return row | updates


def test_strict_threshold_is_not_greater_or_equal(evaluator, tmp_path):
    rows = [case(tmp_path, i) for i in range(20)]
    answers = iter(['daily'] * 19 + ['unknown'])
    report = evaluator['evaluate'](rows, tmp_path, classifier=lambda *_: next(answers))
    assert report['overall'] == dict(total=20, correct=19, incorrect=1,
        unresolved_references=0, accuracy=0.95, confirmed_fraction=0.95, exceeds_95=False)
    assert report['confusion_matrix']['daily']['unknown'] == 1


def test_exceptions_and_missing_input_stay_in_denominator(evaluator, tmp_path):
    rows = [case(tmp_path, 0), case(tmp_path, 1)]
    (tmp_path / rows[1]['body_path']).unlink()
    def broken(*_):
        raise RuntimeError('failure must not be silently skipped')
    report = evaluator['evaluate'](rows, tmp_path, classifier=broken)
    assert report['overall']['total'] == 2
    assert report['overall']['correct'] == 0
    assert report['overall']['accuracy'] == 0
    assert [r['status'] for r in report['cases']] == ['prediction_error', 'input_error']
    assert report['confusion_matrix']['daily']['error'] == 2


def test_incomplete_reference_blocks_main_accuracy(evaluator, tmp_path):
    rows = [case(tmp_path, 0), case(tmp_path, 1, category=None, reference_status='unresolved')]
    report = evaluator['evaluate'](rows, tmp_path, classifier=lambda *_: 'daily')
    assert report['overall']['accuracy'] is None
    assert report['overall']['confirmed_fraction'] == 0.5
    assert report['overall']['exceeds_95'] is False
    assert report['cases'][1]['matches_reference'] is None


def test_school_category_and_included_results_are_separate(evaluator, tmp_path):
    rows = [case(tmp_path, 0), case(tmp_path, 1, category='excluded'),
            case(tmp_path, 2, category='financial_aid')]
    answers = iter(['research_innovation', 'excluded', 'financial_aid'])
    report = evaluator['evaluate'](rows, tmp_path, classifier=lambda *_: next(answers))
    assert report['overall']['accuracy'] == 2 / 3
    assert report['included']['accuracy'] == 0.5
    assert report['by_school']['学校0']['accuracy'] == 0.5
    assert report['by_category']['excluded']['accuracy'] == 1
    assert report['by_category']['daily']['accuracy'] == 0


@pytest.mark.parametrize('field', ['case_id', 'url', 'family_key'])
def test_duplicate_records_cannot_inflate_score(evaluator, tmp_path, field):
    rows = [case(tmp_path, 0), case(tmp_path, 1)]
    rows[1][field] = rows[0][field]
    with pytest.raises(ValueError, match='duplicate'):
        evaluator['evaluate'](rows, tmp_path)


def test_unknown_is_not_an_acceptable_reference_category(evaluator, tmp_path):
    with pytest.raises(ValueError, match='reference'):
        evaluator['evaluate']([case(tmp_path, category='unknown')], tmp_path)


def test_modified_body_is_rejected_before_any_prediction(evaluator, tmp_path):
    row = case(tmp_path)
    (tmp_path / row['body_path']).write_text('改写后的材料')
    called = []
    with pytest.raises(ValueError, match='sha256'):
        evaluator['evaluate']([row], tmp_path, classifier=lambda *a: called.append(a))
    assert called == []


def test_runner_passes_only_title_and_original_paragraphs(evaluator, tmp_path):
    row = case(tmp_path)
    calls = []
    def classify(title, paragraphs):
        calls.append((title, paragraphs))
        return 'daily'
    report = evaluator['evaluate']([row], tmp_path, classifier=classify)
    assert calls == [('本科生选课通知', ('面向全体本科生，选课时间为下周一。',))]
    assert report['overall']['exceeds_95'] is True
    assert report['cross_school_gate_passed'] is False  # one case is not a broad validation


def test_actual_frozen_category_entrypoint_is_used(evaluator, tmp_path):
    report = evaluator['evaluate']([case(tmp_path)], tmp_path)
    assert report['cases'][0]['prediction'] == 'daily'
    assert report['cases'][0]['matches_reference'] is True


def test_freeze_detects_changed_or_added_production_source(evaluator, tmp_path):
    folder = tmp_path / 'backend/src'
    folder.mkdir(parents=True)
    source = folder / 'module.py'
    source.write_text('value = 1\n')
    freeze = {'files': {'backend/src/module.py': hashlib.sha256(source.read_bytes()).hexdigest()}}
    evaluator['verify_algorithm'](freeze, tmp_path)
    source.write_text('value = 2\n')
    with pytest.raises(ValueError, match='algorithm'):
        evaluator['verify_algorithm'](freeze, tmp_path)
    source.write_text('value = 1\n')
    (folder / 'new.py').write_text('other = 3\n')
    with pytest.raises(ValueError, match='algorithm'):
        evaluator['verify_algorithm'](freeze, tmp_path)


def test_reference_file_digest_is_required_and_verified(evaluator, tmp_path):
    path = tmp_path / 'reference.json'
    path.write_text(json.dumps([case(tmp_path)]))
    with pytest.raises(ValueError, match='reference.*sha256'):
        evaluator['load_references'](path, '0' * 64)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert evaluator['load_references'](path, digest)[0]['case_id'] == 'case-0'


def test_raw_text_is_not_exported_in_report(evaluator, tmp_path):
    report = evaluator['evaluate']([case(tmp_path)], tmp_path)
    assert '选课时间为下周一' not in json.dumps(report, ensure_ascii=False)


def test_prediction_uses_the_exact_bytes_checked_before_the_run(evaluator, tmp_path):
    rows = [case(tmp_path, 0), case(tmp_path, 1)]
    observed = []
    def changing_other_file(_title, paragraphs):
        observed.append(paragraphs)
        (tmp_path / rows[1]['body_path']).write_text('替换成另一份内容')
        return 'daily'
    report = evaluator['evaluate'](rows, tmp_path, classifier=changing_other_file)
    assert observed[1] == ('面向全体本科生，选课时间为下周一。',)
    assert report['overall']['correct'] == 2


def test_unreadable_frozen_input_is_counted_without_aborting(evaluator, tmp_path, monkeypatch):
    rows = [case(tmp_path, 0), case(tmp_path, 1)]
    original = Path.read_bytes
    denied = tmp_path / rows[1]['body_path']
    def read(path):
        if path == denied:
            raise PermissionError('cannot read this input')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', read)
    report = evaluator['evaluate'](rows, tmp_path, classifier=lambda *_: 'daily')
    assert report['overall']['total'] == 2
    assert report['overall']['correct'] == 1
    assert report['overall']['accuracy'] == 0.5
    assert report['cases'][1]['status'] == 'input_error'


def test_delivered_corpus_matches_the_pre_prediction_freeze():
    folder = Path(__file__).resolve().parents[2] / 'docs/quality/corpus/multischool-2026-11-17'
    freeze = json.loads((folder / 'freeze.json').read_text())
    for name, key in (('references.json', 'reference_sha256'),
                      ('algorithm-freeze.json', 'algorithm_freeze_sha256'),
                      ('reference-review.json', 'reference_review_sha256')):
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == freeze[key]
    rows = json.loads((folder / 'references.json').read_text())
    assert len(rows) == freeze['case_count'] == 300
    assert len({r['university'] for r in rows}) == freeze['school_count'] == 15
    assert all(r['reference_status'] == 'complete' for r in rows)


def test_delivered_scores_and_error_inventory_are_traceable(evaluator):
    folder = Path(__file__).resolve().parents[2] / 'docs/quality/corpus/multischool-2026-11-17'
    report = json.loads((folder / 'results.json').read_text())
    references = {r['case_id']: r for r in json.loads((folder / 'references.json').read_text())}
    cases = report['cases']
    assert {r['case_id'] for r in cases} == set(references)
    for row in cases:
        reference = references[row['case_id']]
        assert row['reference_category'] == reference['reference_category']
        assert row['body_sha256'] == reference['body_sha256']
        assert row['matches_reference'] == (row['prediction'] == row['reference_category'])
    assert report['overall'] == evaluator['summarize'](cases)
    assert report['included'] == evaluator['summarize']([
        r for r in cases if r['reference_category'] != 'excluded'])
    assert sum(sum(row.values()) for row in report['confusion_matrix'].values()) == len(cases)
    errors = json.loads((folder / 'errors.json').read_text())
    assert {r['case_id'] for r in errors} == {r['case_id'] for r in cases if not r['matches_reference']}
    assert all(r['reference_reason'] == references[r['case_id']]['reference_reason'] for r in errors)


def test_multischool_report_and_protocol_do_not_claim_joint_acceptance():
    root = Path(__file__).resolve().parents[2]
    report = (root / 'docs/verification/s2/multischool-classification-2026-11-17.md').read_text()
    assert '168/300' in report and '56.00%' in report
    assert '161/225' in report and '71.56%' in report
    assert '未超过95%' in report
    assert '标签' in report and '目的性分层' in report
    assert '人工' in report and '独立AI' in report
