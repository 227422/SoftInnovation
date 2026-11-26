"""New-school tests must be independent of development and keep a fixed denominator."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/quality'))
import fresh_school_benchmark as bench


def row(case, school, root, body=None, label='daily'):
    raw=root/(case+'.html')
    raw.write_text(body or f'通知正文{case}')
    source=raw.read_bytes()
    return dict(case_id=case, title='通知', university=school, school_domain=school+'.edu.cn',
                url=f'https://jwc.{school}.edu.cn/info/{case}.htm', family_key='事项'+case,
                raw_path=str(raw), raw_sha256=hashlib.sha256(source).hexdigest(), body_path=str(raw),
                body_sha256=hashlib.sha256(source).hexdigest(), stage='stage1', reference_category=label,
                reference_status='complete', reference_reason='面向学生', reference_evidence=raw.read_text()[:4])


def test_school_holdout_rejects_old_schools_domains_families_and_normalized_urls(tmp_path):
    old=row('x','old',tmp_path)
    for field in ['university','family_key']:
        new=row('y','new',tmp_path)
        new[field]=old[field]
        with pytest.raises(ValueError, match='overlap|duplicate'):bench.check_identities([new],[old],[])
    new=row('z','new',tmp_path)
    new['url']='http://JWC.OLD.EDU.CN/info/x.htm#section'
    with pytest.raises(ValueError, match='overlap|duplicate|domain'):bench.check_identities([new],[old],[])


def test_near_duplicate_is_flagged_even_across_names_and_without_matching_url(tmp_path):
    words=''.join(chr(i) for i in range(0x4e00,0x4f00))
    old=row('a','old',tmp_path,words);new=row('b','fresh',tmp_path,'新的开头'+words+'补充文字')
    pairs=bench.similar_pairs([new],[old],tmp_path)
    assert [(p['left'],p['right']) for p in pairs]==[('b','a')]
    assert pairs[0]['containment']>=.7


def test_stage_requires_independent_reference_review_and_short_evidence(tmp_path):
    new=row('n','u',tmp_path);review=dict(case_id='n',category='daily',read_complete=True,evidence='通知正文',reviewer='other')
    bench.check_review([new],[review],{'n'},tmp_path)
    for change in [{'category':'excluded'},{'read_complete':False},{'evidence':'missing literal'}]:
        with pytest.raises(ValueError):bench.check_review([new],[review|change],{'n'},tmp_path)
    with pytest.raises(ValueError):bench.check_review([new],[],{'n'},tmp_path)


def test_strict_first_and_second_stage_cutoffs_and_unknown_denominator():
    labels=['daily']*96+['financial_aid']*48+['research_innovation']*48+['excluded']*48
    rows=[dict(case_id=str(i),university='学校'+str(i%12),label=l) for i,l in enumerate(labels)]
    predictions=[dict(case_id=r['case_id'],prediction=r['label']) for r in rows]
    for n,pass1,pass2 in [(228,False,False),(229,True,False),(235,True,False),(236,True,True)]:
        report=bench.stage_score(rows,predictions[:n])
        assert report['stage1_passed']==pass1 and report['stage2_passed']==pass2
        assert report['overall']['total']==240 and report['overall']['correct']==n
    assert 'daily_precision' in report and report['daily_recall']==1


def test_prediction_input_strips_school_and_reference_and_obscures_ids():
    r=dict(case_id='school-daily-001',title='题',body='原文',label='daily',university='学校')
    inputs,mapping=bench.blind_inputs([r], 'locked')
    assert set(inputs[0])=={'case_id','title','body'}
    assert inputs[0]['case_id']!='school-daily-001'
    assert mapping=={inputs[0]['case_id']:'school-daily-001'}


def test_failed_inference_is_counted_and_same_folder_cannot_be_reopened(tmp_path,monkeypatch):
    folder=tmp_path/'locked';folder.mkdir()
    example=row('a','new',tmp_path)
    inputs,mapping=bench.blind_inputs([example | {'body':'原文'}],'x')
    for name,data in [('inputs',inputs),('reference',[example]),('mapping',mapping)]:
        bench.write_json(folder/(name+'.json'),data)
    freeze={'stage':'stage1','files_sha256':{p.name:bench.checksum(p) for p in folder.iterdir()},
            'scorer_sha256':bench.checksum(Path(bench.__file__)),
            'shared_scorer_sha256':bench.checksum(Path(bench.__file__).with_name('small_classifier_experiment.py'))}
    bench.write_json(folder/'freeze.json',freeze)
    model=tmp_path/'model.json';model.write_text('{}')
    attempts=[]
    def fail(*args,**kwargs):
        attempts.append(1)
        return type('Status',(),{'returncode':1})()
    monkeypatch.setattr(bench.subprocess,'run',fail)
    args=(folder,model,bench.checksum(model),bench.checksum(folder/'freeze.json'),Path('localpython'),tmp_path/'run')
    result=bench.evaluate_once(*args)
    assert result['overall']['total']==1 and result['overall']['correct']==0
    assert result['prediction_failure']
    with pytest.raises(FileExistsError):bench.evaluate_once(*args)
    with pytest.raises(FileExistsError):bench.evaluate_once(*args[:-1],tmp_path/'another-run')
    assert attempts==[1]


def test_versioned_predictor_entrypoint_is_repo_local_and_digest_bound(tmp_path):
    manifest = tmp_path / 'candidate.json'
    manifest.write_text('{}')
    assert bench.predictor_entrypoint(manifest) == bench.ROOT/'scripts/quality/v3_classifier.py'
    version = 'scripts/quality/v4_classifier.py'
    entry = tmp_path/version
    entry.parent.mkdir(parents=True)
    entry.write_text('# candidate')
    bench.write_json(manifest, {'predictor_entrypoint':version, 'source_sha256':{version:bench.checksum(entry)}})
    assert bench.predictor_entrypoint(manifest,tmp_path) == entry
    entry.write_text('# changed')
    with pytest.raises(ValueError,match='entrypoint'):bench.predictor_entrypoint(manifest,tmp_path)
    bench.write_json(manifest,{'predictor_entrypoint':'../other.py','source_sha256':{}})
    with pytest.raises(ValueError,match='entrypoint'):bench.predictor_entrypoint(manifest,tmp_path)


def test_identifier_only_official_query_strings_distinguish_pages():
    notice = "https://unit.example.edu.cn/Website/Home/Detail?"
    assert bench.url_key(notice + "CAMPUS01") != bench.url_key(notice + "CAMPUS02")
    assert bench.url_key(notice + "CAMPUS01&utm_source=portal") == bench.url_key(notice + "CAMPUS01")
    assert bench.url_key(notice + "q=2&page=1") == bench.url_key(notice + "page=1&q=2#main")
