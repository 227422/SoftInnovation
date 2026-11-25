from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_evidence_sampler_finds_late_recipient_and_keeps_submission_date():
    assert (ROOT/'scripts/quality/v6_role.py').exists()
    from v6_role import role_view
    body='会议概况。'*110+'一、参赛对象\n全体在籍硕士研究生。\n报名截止后不可补交。'
    view=role_view(body)
    assert '在籍硕士研究生' in view and '报名截止' in view


@pytest.mark.parametrize(('title','body','expected'),[
 ('高校心理委员培训通知','参训对象：各班本科生心理委员与研究生心理骨干。请学生报名。','daily'),
 ('研究生设计竞赛通知','参赛对象为全日制在读硕士及博士研究生，本科期间获奖可作为申报材料。','excluded'),
 ('研究生创新论坛征稿','允许在校本科生与研究生共同投稿参加评审。','research_innovation'),
 ('博士后创新竞赛报名通知','参赛对象为在站博士后，申报参赛作品。','excluded'),
 ('辅导员能力大赛初赛安排','各学院在岗辅导员参加职业技能测试。','excluded'),
 ('教师教学创新赛选拔通知','教师须提交教学设计与课程报告，本科生参与课堂演示。','excluded'),
 ('选调优秀毕业生工作的通知','应届毕业生可报考，通过公务员录用考察。','daily'),
 ('优秀本科毕业生荣誉评选公示','拟推荐名单公示，学生可按时提出异议。','financial_aid'),
 ('全国创新赛在本校举办','决赛现场来自各校的选手比拼，评审专家完成了现场打分。','excluded'),
 ('即将举办设计大赛的通知','现面向学生征集作品，请于本周报名参加。','research_innovation'),
])
def test_applicant_roles_primary_action_and_tense(title,body,expected):
    assert (ROOT/'scripts/quality/v6_classifier.py').exists()
    from v6_classifier import scope_decision
    assert scope_decision(title,body)[0]==expected


def test_recipient_model_can_learn_and_does_not_relabel_by_id():
    import os
    import subprocess
    executable=os.getenv('ML_PYTHON')
    if not executable:
        pytest.skip('use isolated numerical runtime for the learned recipient head')
    code="""
import numpy as np
from v6_classifier import apply_decisions,recipient_scores
from v6_model_development import train_recipient
roles=np.repeat(np.arange(5),7)
z=np.eye(5)[roles]
p=train_recipient(z,roles)
base=np.repeat([[-.5,-.7,-.8,-2.5]],len(z),axis=0)
out,gate,kind=recipient_scores(z,base,p)
assert (kind.argmax(axis=1)==roles).all() and ((gate>0)==(roles!=0)).all()
assert np.allclose(np.exp(out).sum(axis=1),1)
rows=[dict(case_id='opaque-a',title='事项',body='原件'),dict(case_id='opaque-b',title='事项',body='原件')]
components={'hierarchical':np.array([[-2,-1,0,3],[-2,-1,0,3]])}
sub=np.array([[0,2,-1,-1,-1],[0,2,-1,-1,-1]])
result=apply_decisions(rows,components,{'hierarchical':1},0.6,[0.5,0.8],sub,prior=[('daily','public_session_registration')]*2)
assert [r['prediction'] for r in result]==['daily','excluded']
assert result[1]['reason']=='trained_recipient_and_scope_agree'
"""
    proc=subprocess.run([str(Path(executable).absolute()),'-c',code],cwd=ROOT/'scripts/quality',
                        capture_output=True,text=True,timeout=120)
    assert proc.returncode==0,proc.stderr
