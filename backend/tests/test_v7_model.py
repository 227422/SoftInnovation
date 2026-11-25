from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_school_folds_never_share_any_school_or_example():
    assert (ROOT/'scripts/quality/v7_model_development.py').is_file()
    from v7_model_development import school_partitions
    rows=[{'university':s,'case_id':str(i)} for i,s in enumerate(['A','C','B','A','F','D','E','F'])]
    folds=list(school_partitions(rows,3))
    assert sorted(i for _,v in folds for i in v)==list(range(len(rows)))
    for tr,va in folds:assert not {rows[i]['university'] for i in tr}&{rows[i]['university'] for i in va}


def test_gate_features_require_only_observations_and_predictions():
    assert (ROOT/'scripts/quality/v7_gate.py').is_file()
    from v7_gate import gate_features
    votes={'one':'daily','two':'excluded','three':'daily'}
    args=('本科生申请通知','请报名参加。','financial_aid','daily','student_award_or_aid',votes)
    a=gate_features(*args)
    assert len(a)>10 and all(isinstance(float(x),float) for x in a)
    assert a==gate_features(*args)


def test_learned_arbitrator_can_choose_either_branch():
    from v7_classifier import arbitrate
    from v7_gate import gate_features
    row={'case_id':'random-7','title':'在校通知','body':'面向毕业生报名。'}
    p={'case_id':'random-7','learned_prediction':'daily','prediction':'daily','component_predictions':{'one':'daily'}}
    policy=[('financial_aid','student_award_or_aid')]
    n=len(gate_features(row['title'],row['body'],*('financial_aid','daily','student_award_or_aid'),p['component_predictions']))
    for intercept,expected in [(-10,'daily'),(10,'financial_aid')]:
        out=arbitrate([row],[p],policy,{'coef':[0]*n,'intercept':intercept},.5)
        assert out[0]['prediction']==expected and out[0]['case_id']=='random-7'


def test_encoder_updates_attention_and_outputs_finite_scores():
    import os
    import subprocess
    executable=os.getenv('ML_PYTHON')
    if not executable:pytest.skip('use isolated machine learning environment')
    code="""
import numpy as np
from v7_encoder import fit,evaluate
rng=np.random.default_rng(33)
x=rng.normal(size=(20,12,768)).astype('float32');y=np.repeat(np.arange(4),5)
model,c,s,proof=fit(x,y,epochs=1)
result=evaluate(model,x,c,s)
assert result.shape==(20,4) and np.isfinite(result).all()
assert proof['first_attention_before']!=proof['first_attention_after']
assert sum(p.numel() for p in model.parameters() if p.requires_grad)==proof['parameters']
"""
    result=subprocess.run([str(Path(executable).absolute()),'-c',code],cwd=ROOT/'scripts/quality',
                          capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr


def test_temporal_partition_requires_both_a_new_school_and_later_publication():
    from v7_schedule import temporal_partition
    rows=[{'university':str(s),'year':year,'historical_split':'consumed_cohort1'}
          for s in range(8) for year in (2024,2025,2026,None)]
    train,test=temporal_partition(rows)
    assert all(rows[i]['year']<=2025 for i in train)
    assert all(rows[i]['year']==2026 for i in test)
    assert not {rows[i]['university'] for i in train}&{rows[i]['university'] for i in test}
