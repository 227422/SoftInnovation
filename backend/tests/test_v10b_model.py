from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_human_labels_take_precedence_over_weak_reviewer_words():
    from v10b_supervision import labels
    from v10b_data import AUDIENCE,ACTIONS
    r={'title':'通知','label':'daily'};ref={'audience_role':'mixed_including_undergraduate','action_type':'open_activity',
                                          'reference_reason':'教师准备开幕式。','reference_evidence':'师生均可报名。'}
    a,b,wa,wb=labels(r,ref)
    assert AUDIENCE[a]=='mixed_including_undergraduate' and ACTIONS[b]=='open_activity' and wa>1 and wb>1


def test_sports_participation_and_design_remain_separate():
    from v10b_views import athletic_signal
    assert athletic_signal('校园迷你马拉松报名通知','参赛运动员请报名。')
    assert not athletic_signal('智能马拉松运动设备创新设计大赛','学生提交设计作品。')


def test_promotion_cannot_use_the_new_diagnostic_instead_of_hard77():
    from v10b_development import promoted
    def entry(correct,total=336):
        return {'scores':{'chosen':dict(total=total,correct=correct,daily_correct=125,daily_total=132,
                                        false_admissions=5,false_rejections=7)}}
    old={'select':entry(324,331),'guard':entry(318),'hard77':entry(71,77)}
    same={'select':entry(324,331),'guard':entry(325),'hard77':entry(70,77)}
    assert promoted(same,old)
    assert not promoted(same|{'hard77':entry(69,77)},old)
    assert not promoted(same|{'guard':entry(324)},old)


def test_native_three_view_bert_updates_attention_and_returns_all_auxiliary_roles(tmp_path):
    import os
    import subprocess
    import pytest
    runtime=os.environ.get('ML_PYTHON')
    if not runtime:pytest.skip('requires isolated model environment')
    code="""
import sys
import numpy as np
import torch
from transformers import BertConfig,BertForSequenceClassification
from v10b_bert import fit,infer
path=sys.argv[1];torch.manual_seed(14)
BertForSequenceClassification(BertConfig(vocab_size=128,hidden_size=24,intermediate_size=36,
   num_hidden_layers=2,num_attention_heads=4,num_labels=4)).save_pretrained(path,safe_serialization=True)
rng=np.random.default_rng(15);n=12;h=rng.normal(size=(3*n,10,24)).astype(np.float16);lens=np.array([8,9,10]*n)
y=np.arange(n)%4;aux=np.array([[i%6,i%8,1.,1.] for i in range(n)])
m,p=fit(path,h,lens,y,aux,np.ones(n),np.eye(3)[np.arange(n)%3],np.ones(n),range(n),epochs=1)
assert p['steps']==1 and p['attention_before']!=p['attention_after']
s=infer(m,h,lens,list(range(n)),p['device'])
assert [s[k].shape for k in ['joint','doc','audience','action','source']]==[(n,4),(n,4),(n,6),(n,8),(n,3)]
assert all(np.allclose(v.sum(1),1) for v in s.values())
"""
    out=subprocess.run([str(Path(runtime).absolute()),'-c',code,str(tmp_path)],cwd=ROOT/'scripts/quality',
                       capture_output=True,text=True,timeout=120)
    assert out.returncode==0,out.stderr
