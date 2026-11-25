from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_semantic_view_labels_title_and_body_token_regions():
    assert (ROOT/'scripts/quality/v5_semantic.py').exists(), 'semantic feature training is required'
    from v5_semantic import layout
    ids, title_length = layout([1,2,3],list(range(500,1000)),list(range(900,1300)),101,102)
    assert ids[:5]==[101,1,2,3,102] and title_length==3 and len(ids)<=384
    assert 500 in ids and 900 in ids and ids[-1]==102


@pytest.mark.parametrize(('title','body','expected'),[
    ('关于奖学金生学籍注册的通知','请所有新学年的奖学金生本人办理注册手续。','daily'),
    ('关于制定本科推免工作评审小组的通知','学院成立工作小组和专家组，各组负责资格审核。','excluded'),
    ('关于本科生推免报名的通知','推免工作专家组负责审核，请本科应届生申请。','daily'),
    ('面向研究生的选课通知','面向对象为所有在籍研究生，已在本科阶段修过同等课程的可免修。','excluded'),
    ('研究生社会奖学金评审','参评资格为全日制二年级及以上硕士、博士研究生，优秀本科生事迹用于宣传。','excluded'),
    ('硕士研究生招生简章','国家承认学历的应届本科毕业生可报考。','daily'),
    ('本科生竞赛获奖者减免实习时间的办法','符合条件的学生可提交申请，办理实习减免。','daily'),
    ('学生会执行主席选拔通知','请符合条件的学生骨干参加遴选。','daily'),
    ('本科生志愿者拟入选名单公示','公示期内可以申请复核，志愿者服务西部。','daily'),
    ('本科生创新创业竞赛先进工作者表彰公示','拟表彰先进学生个人和优秀指导教师。','financial_aid'),
    ('关于创业训练营校园选拔赛的通知','参赛学生须在决赛提交创业作品，由评委择优选拔。','research_innovation'),
    ('本科生课程改选表格下载','请下载改选课程申请表。','daily'),
])
def test_recipient_distinct_from_candidate_qualification(title,body,expected):
    assert (ROOT/'scripts/quality/v5_classifier.py').exists(), 'v5 prediction is required'
    from v5_classifier import resolve
    assert resolve(title,body)[0] == expected


def test_short_notices_keep_contiguous_context():
    from v5_semantic import layout
    ids,n=layout([12],[21,22],[99],1,2)
    assert ids==[1,12,2,21,22,2]
    assert n==1


def test_semantic_heads_learn_inclusion_and_three_topics():
    import os
    import subprocess
    executable=os.getenv('ML_PYTHON')
    if not executable:
        pytest.skip('use the separate local numerical environment for semantic-head fitting')
    script="""
import numpy as np
from v5_model_development import fit_context
from v5_classifier import head_scores
labels=np.repeat(np.arange(4),6)
features=np.eye(4)[labels].astype(np.float32)
head=fit_context(features,labels)
direct,hierarchical=head_scores(features,head)
assert np.array_equal(direct.argmax(axis=1),labels)
assert np.array_equal(hierarchical.argmax(axis=1),labels)
assert np.allclose(np.exp(hierarchical).sum(axis=1),1)
assert set(head)=={'mean','direct_coef','direct_intercept','scope_coef','scope_intercept','topic_coef','topic_intercept'}
"""
    result=subprocess.run([str(Path(executable).absolute()),'-c',script],cwd=ROOT/'scripts/quality',
                          capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
