from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_long_paragraphs_keep_the_headline_and_distinguish_actor_from_mention():
    from v10_nli import exemplars
    t='实验项目办理通知'
    body='学生来信介绍了实验兴趣。'*12+'办理对象为在岗教师，学院负责人须在本周申报；本科生无须操作。'+'课程按原计划进行。'*10
    pairs=exemplars(t,body)
    assert len(pairs)==13
    assert all(t in premise and hypothesis for premise,hypothesis in pairs)
    assert any('办理对象为在岗教师' in p for p,h in pairs[3:5])


def test_ambiguous_roles_are_masked_in_training():
    from v10_supervision import auxiliary
    row={'title':'赛事报道','label':'excluded'}
    ref={'reference_reason':'学院记录已经结束的比赛，没有新的报名。','boundary_type':'回顾','reference_evidence':'赛事落幕。'}
    y,mask=auxiliary(row,ref)
    assert len(mask)==len(y)==6 and mask[3] and y[3]==1 and not y[0]


def test_promotion_requires_transfer_and_the_independent_hard_set():
    from v10_development import promoted
    base={'correct':193,'total':200,'daily_correct':76,'daily_total':80,'false_admissions':2,'false_rejections':4}
    better=dict(base,correct=195)
    select={'document':base,'chosen':better};guard={'document':base,'chosen':better}
    assert promoted(select,guard,{'document':{'correct':71},'chosen':{'correct':70}})
    assert not promoted(select,guard,{'document':{'correct':72},'chosen':{'correct':70}})
    assert not promoted(select,{'document':base,'chosen':dict(better,false_admissions=4)},
                        {'document':{'correct':70},'chosen':{'correct':70}})


def test_network_and_oof_meta_learn_on_numeric_relations():
    import os
    import subprocess
    import pytest
    runtime=os.environ.get('ML_PYTHON')
    if not runtime:pytest.skip('requires isolated ML runtime')
    code="""
import numpy as np
from v10_classifier import meta_features,meta_score
from v10_development import train_meta
from v10_relation import fit,apply
rng=np.random.default_rng(18);y=np.repeat(np.arange(4),12);n=len(y)
v=rng.normal(size=(n,13,387)).astype(np.float32)
for i,label in enumerate(y):v[i,:,label*8:(label+1)*8]+=4.
a=np.column_stack([y!=3,y==3,y!=3,y==3,y==0,y==1]).astype(float);mask=np.ones_like(a)
span=np.zeros((n,13));span[:,1]=1
model,c,s,h=fit(v,y,a,mask,span,np.ones_like(span),range(n))
joint,roles,p=apply(model,v,c,s)
assert joint.shape==(48,4) and roles.shape==(48,6) and p.shape==(48,13)
assert (joint.argmax(1)==y).sum()>42 and h[-1]<h[0]
features=meta_features(joint,joint,joint,roles,joint,[None]*n)
m=train_meta(features,y);assert (meta_score(features,m).argmax(1)==y).all()
"""
    p=subprocess.run([str(Path(runtime).absolute()),'-c',code],cwd=ROOT/'scripts/quality',
                     capture_output=True,text=True,timeout=120)
    assert p.returncode==0,p.stderr
