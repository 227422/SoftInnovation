from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_quote_alignment_locates_action_outside_the_heading():
    from v9_evidence import align, spans
    row={'title':'护理专业通知','body':'护理专业通知。召开工作会议讨论相关事项。面向全校本科生征集作品。请将材料提交至邮箱。'}
    chunks=spans(row['title'],row['body'])
    scores=align(chunks,'本科生征集作品')
    assert max(scores)>.5 and '征集作品' in chunks[scores.index(max(scores))]


def test_promotion_needs_higher_accuracy_and_controls_both_scope_errors():
    from v9_development import promoted
    base={'correct':95,'total':100,'daily_correct':38,'false_rejections':4,'false_admissions':2}
    assert promoted(base,base,base,dict(base,correct=96))
    assert not promoted(base,base,base,dict(base,correct=95))
    assert not promoted(base,base,base,dict(base,correct=97,false_rejections=6))


def test_evidence_experts_learn_from_quotes_and_cannot_respond_to_observation_ids():
    import os
    import subprocess
    import pytest
    exe=os.environ.get('ML_PYTHON')
    if not exe:pytest.skip('requires isolated learning environment')
    code="""
import numpy as np
from v9_evidence import align,chosen,fit_ranker,spans,fit_text_experts,text_scores
from v9_classifier import fusion
titles=['科研项目申报','困难学生补助','学生办理选课','在岗教师考核']*4
topic=['参赛学生提交实验方案和科研作品。','学生可以申请困难家庭生活补助。','本科生须于周三前办理课程退选。','仅限在岗专任教师参加年度考核。']*4
rows=[dict(title=t,body='有关部门正在整理会议资料。'+q+'以上信息已由办公室转发。') for t,q in zip(titles,topic)]
chunks=[spans(r['title'],r['body']) for r in rows]
signals=[align(c,q) for c,q in zip(chunks,topic)]
ranker,n=fit_ranker(rows,chunks,signals,range(len(rows)));assert n==16
selected=[chosen(t,c,ranker)[0] for t,c in zip(titles,chunks)]
labels=np.arange(len(rows))%4
model=fit_text_experts(titles,selected,topic,labels)
s=text_scores(titles,selected,model)
assert (s['char'].argmax(1)==labels).all()
s['neural']=s['char'].copy()
d=s['char'].copy()
plain=fusion(d,s,.5,(.6,.3,.1),[None]*len(rows)).argmax(1)
wrong=fusion(d,s,.5,(.6,.3,.1),[(int(y)+1)%4 for y in labels]).argmax(1)
assert (plain==wrong).all()
"""
    p=subprocess.run([str(Path(exe).absolute()),'-c',code],cwd=ROOT/'scripts/quality',
                     capture_output=True,text=True,timeout=120)
    assert p.returncode==0,p.stderr
