from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/quality'))


@pytest.fixture
def decision():
    assert (ROOT / 'scripts/quality/v4_classifier.py').is_file(), 'v4 scope predictor required'
    from v4_classifier import resolve_matter
    return lambda title, body: resolve_matter(title, body)[0]


@pytest.mark.parametrize(('title','body','category'), [
    ('企业校园招聘启事', '本次接受应届本科及以上毕业生投递简历。', 'daily'),
    ('招聘专业技术岗位', '本次招聘仅面向已获博士学位人员，在线报名。', 'excluded'),
    ('春季校园双选会举行', '活动现场吸引了上千名毕业生参与，用人单位提供400个岗位。', 'excluded'),
    ('关于组织春季校园双选会的通知', '请应届本科毕业生登录就业平台报名参会。', 'daily'),
    ('学生竞赛学分认定通知', '请本科生在截止前提交申请认定学分，附历年获奖名单。', 'daily'),
    ('关于竞赛期间教室封闭的公告', '下周教室因比赛封闭，课表另行调整。', 'daily'),
    ('关于数学竞赛报名的通知', '选手报名参赛。获奖者可获得学分认定。', 'research_innovation'),
    ('学业奖学金评定细则', '资助对象为全日制硕士研究生。', 'excluded'),
    ('出国交流学习资助管理办法', '本科生可申请经费，按照资助标准给予补贴。', 'financial_aid'),
    ('本科生交换学习报名通知', '报名者可另外申请奖学金，请提交交流申请表。', 'daily'),
    ('本校学子在创业大赛中再获佳绩', '他们获得金奖，校领导出席了本次颁奖活动。', 'excluded'),
    ('大学生创业大赛评奖结果公示', '现将获奖名单公示，参赛学生如有异议请在公示期内反馈。', 'research_innovation'),
    ('关于研究生招生在线宣讲的通知', '欢迎有意报考的同学参加宣讲，直播时间如下。', 'daily'),
    ('本研贯通培养计划选拔', '请符合条件的本科生报名参加遴选。', 'daily'),
    ('研讨会报名 | 数智技术应用', '欢迎在校学生报名参加论坛。', 'daily'),
    ('本科生摄影作品大赛通知', '面向学生征集作品，参赛作品由评委评分并评选一等奖。', 'research_innovation'),
    ('组织创新训练营报名', '报名参加车载软件开发竞赛，每个团队须提交参赛作品，设有决赛。', 'research_innovation'),
])
def test_alternate_actions_with_similar_subjects(decision, title, body, category):
    assert decision(title, body) == category
