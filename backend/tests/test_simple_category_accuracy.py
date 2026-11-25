"""Product v3 category boundaries, independent of document IDs or program names."""

import pytest

from campus_backend.classification.simple_categories import classify_simple_notice
from campus_backend.classification.rule_baseline import classify_notice



@pytest.mark.parametrize(('title', 'body'), [
    ('青云科创班录取名单公示', ('经学生申请、面试及项目测试，拟录取60名同学进入科创班学习。',)),
    ('本科生科创班项目测试入围学生名单公示', ('入围学生请按时参加项目测试并完成抽签分组。',)),
    ('知行实验班面试考核通知', ('经资格审查，确定本科生实验班面试名单，请入围学生参加面试。',)),
    ('基础学科拔尖人才培养班选拔通知', ('面向全校本科生报名，考核后编入培养班学习。',)),
    ('本科生拔尖人才培养计划招生面试安排', ('参加本次人才培养计划选拔的学生请按时面试。',)),
])
def test_student_program_admission_is_academic_even_with_innovation_in_name(title, body):
    assert classify_simple_notice(title, body) == 'daily'


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('科创班学生创新设计竞赛报名通知', ('面向本科生，学生可自行报名参赛。',), 'research_innovation'),
    ('研究生拔尖创新创业人才项目录取名单公示', ('仅面向研究生，现将录取结果公示。',), 'excluded'),
    ('实验班教师招聘公告', ('申请人须具有博士学位。',), 'excluded'),
    ('大学生创新训练项目立项名单公示', ('现公示学生创新训练项目立项名单。',), 'research_innovation'),
])
def test_program_override_preserves_competitions_and_nonundergraduate_exclusions(title, body, expected):
    assert classify_simple_notice(title, body) == expected


@pytest.mark.parametrize('body', [
    ('各二级学院：', '各二级学院需确保每学期独立组织开展1场专题讲座。',
     '为学生答疑解惑。各学院建立专项工作台账，做好活动筹备、宣传总结等工作。',
     '每月20日将讲座组织情况汇总表和工作总结统一报送至学院。'),
    ('请各学院制定系列讲座方案并组织开展活动。', '活动结束后，各学院报送工作总结和组织情况汇总表。'),
])
def test_internal_lecture_organization_without_student_entry_is_excluded(body):
    assert classify_simple_notice('关于组织开展就业创业系列讲座的通知', body) == 'excluded'


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('关于组织大学生创新设计竞赛的通知',
     ('各二级学院：请认真组织，统一报送汇总表。', '本科生可在赛事网站自行报名参赛。'),
     'research_innovation'),
    ('关于组织就业系列讲座的通知',
     ('各学院请做好讲座组织和材料报送。', '本场讲座面向全体本科生开放，欢迎同学们扫码报名。'),
     'daily'),
    ('关于组织职业规划讲座的通知',
     ('各学院需组织开展本场讲座，活动后报送总结。', '报名对象：全体本科生。报名方式：扫描二维码。'),
     'daily'),
])
def test_unit_recipients_do_not_hide_direct_student_opportunities(title, body, expected):
    assert classify_simple_notice(title, body) == expected


@pytest.mark.parametrize(('title', 'body'), [
    ('学院创新基地参观活动',
     ('同学们参观了创新创业基地，体验了3D打印。', '本次参观活动圆满结束，记者记录了同学们的收获。')),
    ('职业规划分享讲座',
     ('学院于10月12日举办了职业规划讲座。', '同学们在活动中交流了自己的收获。')),
    ('大学生创新设计竞赛',
     ('本届竞赛已圆满结束，同学们在比赛中展示了创新作品。',)),
])
def test_body_only_recap_without_new_student_action_is_excluded(title, body):
    assert classify_simple_notice(title, body) == 'excluded'


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('职业规划分享讲座报名通知',
     ('上一期讲座已圆满结束，同学们收获满满。', '新一期欢迎本科生报名，报名截止10月20日。'),
     'daily'),
    ('职业规划讲座活动总结及新一期报名通知',
     ('上期讲座圆满结束。', '请同学们扫描二维码报名参加新一期讲座。'),
     'daily'),
    ('大学生创新设计竞赛圆满结束暨获奖名单公示',
     ('本届竞赛已结束，现将获奖结果公示。',), 'research_innovation'),
    ('实验班选拔活动总结暨录取名单公示',
     ('面试已顺利结束，现公示录取学生名单。',), 'daily'),
    ('大学生创新设计竞赛结果公示',
     ('比赛已结束，公示期内可提出异议。',), 'research_innovation'),
])
def test_results_and_new_student_actions_survive_recap_words(title, body, expected):
    assert classify_simple_notice(title, body) == expected


def test_legacy_classifier_keeps_its_historical_behavior():
    assert classify_notice('青云科创班录取名单公示', ('拟录取学生进入科创班学习。',)) == 'research_innovation'
    assert classify_notice('学院创新基地参观活动', ('本次参观活动圆满结束。',)) == 'unknown'


def test_denied_registration_is_not_a_new_opportunity_in_a_recap():
    assert classify_simple_notice(
        '职业规划讲座', ('本次讲座已圆满结束，学生不可报名。',)
    ) == 'excluded'


def test_future_lecture_is_not_mistaken_for_a_report():
    assert classify_simple_notice(
        '职业规划讲座通知', ('讲座将于11月20日下午举行。',)
    ) == 'daily'


def test_audience_description_alone_does_not_reopen_an_ended_activity():
    assert classify_simple_notice(
        '职业规划讲座', ('本次活动面向全体本科生，讲座已圆满结束。',)
    ) == 'excluded'


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('校园体质健康项目挑战赛', ('本科生按学院报名，各参赛运动员参加跑步和立定跳远，按运动成绩排名并发奖牌。',), 'daily'),
    ('全校大学生游泳比赛通知', ('学生可报名比赛，按各组完成比赛的用时录取前八名。',), 'daily'),
    ('大学生体育器材创新设计比赛', ('本科生可报名，提交用于游泳比赛的训练器材设计作品，评委评审技术方案。',), 'research_innovation'),
    ('学生运动会会徽设计竞赛', ('面向全体本科生征集设计作品，获选作品用于明年的田径比赛。',), 'research_innovation'),
    ('大学生田径比赛赛后回顾', ('本场比赛已经圆满结束，运动员按成绩领取奖牌。',), 'excluded'),
    ('校园游泳比赛通知', ('本次比赛仅限在籍研究生，各组按用时排名。',), 'excluded'),
    ('校园游泳比赛通知', ('本次比赛仅限在籍研究生，本科生不能参加。运动员按成绩排名。',), 'excluded'),
    ('校园游泳比赛通知', ('研究生组仅面向研究生，本科生另设甲组，各组选手按用时排名。',), 'daily'),
    ('运动会学生志愿者招募', ('学生可报名志愿服务，负责队伍引导。参赛运动员按成绩排名。',), 'daily'),
    ('游泳比赛奖学金申请通知', ('学生可申请体育奖学金。运动员按成绩排名是其中一项条件。',), 'financial_aid'),
    ('智能体育科技挑战赛', ('参赛者提交跑姿识别算法作品和技术报告，由专家评审。',), 'research_innovation'),
])
def test_sports_category_uses_what_the_student_actually_competes_in(title, body, expected):
    assert classify_simple_notice(title, body) == expected


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('教职工排球比赛报名', ('各工会选派本单位教职工组队，运动员按循环赛积分排名。',), 'excluded'),
    ('师生排球比赛报名通知', ('教师队和本科生队均可报名，各组按积分排名。',), 'daily'),
    ('大学生排球比赛', ('参赛运动员为在校本科生，各队领队仅限教职工。',), 'daily'),
    ('关于为教职工排球比赛招募学生志愿者的通知', ('欢迎本科生报名承担计分和引导服务。',), 'daily'),
])
def test_sports_scope_distinguishes_players_staff_and_student_volunteers(title, body, expected):
    assert classify_simple_notice(title, body) == expected
