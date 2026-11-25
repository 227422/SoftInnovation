from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'quality'))


@pytest.fixture
def model():
    assert (ROOT / 'scripts/quality/v3_classifier.py').is_file(), 'offline v3 predictor is required'
    import v3_classifier
    return v3_classifier


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('下学期研究生选课通知', '全日制硕士研究生请登录系统选课。', 'excluded'),
    ('期中考试安排', '请选课研究生持研究生证参加考试。', 'excluded'),
    ('学生专项助学金评选', '本科生、研究生均可向学院申请。', 'financial_aid'),
    ('开展职业规划大赛的通知', '本校学生报名参赛，通过初赛进入决赛。', 'research_innovation'),
    ('学生就业技能培训报名', '欢迎应届毕业生报名参加培训。', 'daily'),
    ('城乡居民医疗保险参保通知', '请在校学生按期参保缴费。', 'daily'),
    ('考研学生缓考安排', '请报名硕士研究生入学考试的同学申请缓考。', 'daily'),
    ('研究生论坛回顾', '活动圆满结束，本科学生志愿者提供了服务。', 'excluded'),
    ('奖学金评定实施办法', '申报本科生奖学金的同学须提交材料，相关事项请咨询研究生院。', 'financial_aid'),
    ('导师评审通知', '申报对象仅限硕士研究生导师，受表彰的导师曾指导本科生。', 'excluded'),
    ('推免报名工作通知', '有意攻读硕士研究生的本科生请在系统报名。', 'daily'),
    ('职业规划大赛报名通知', '参赛对象仅限在籍研究生。', 'excluded'),
])
def test_audience_and_primary_action(model, title, body, expected):
    assert model.policy_decision(title, body)[0] == expected


def test_evidence_view_reads_interior_and_preserves_original_text(model):
    important = '对象为在校本科生，参加者须提前报名。'
    body = '工作简介。' * 130 + important + '附件材料。' * 150
    view = model.evidence_view(body)
    assert important in view and len(view) <= 1200
    assert all(piece in body for piece in view.split('\n'))


def test_input_rejects_labels_metadata_empty_and_duplicates(model):
    sample = dict(case_id='id', title='例子', body='正文')
    assert model.validate_inputs([sample]) is None
    for data in ([sample | {'label': 'daily'}], [sample | {'university': '校'}],
                 [sample, sample], [sample | {'body': ''}]):
        with pytest.raises(ValueError):
            model.validate_inputs(data)


def test_history_folds_remove_whole_schools_from_new_fitting(model):
    from v3_model_development import school_folds
    rows = [dict(case_id=str(i), university=s) for i, s in enumerate(['甲', '乙', '甲', '丙'])]
    folds = list(school_folds(rows, ['甲', '丙']))
    assert folds == [('甲', [1, 3], [0, 2]), ('丙', [0, 1, 2], [3])]


def test_rejects_tampered_dependency(model, tmp_path):
    (tmp_path / 'weights').write_bytes(b'wrong')
    with pytest.raises(ValueError, match='sha256'):
        model.verify_files(tmp_path, {'weights': '0' * 64})
    with pytest.raises(ValueError, match='path'):
        model.verify_files(tmp_path, {'../external': '0' * 64})


@pytest.mark.parametrize(('title', 'body', 'must_not_force'), [
    ('关于开展竞赛的通知', '本届竞赛向本科生和研究生同时开放。', 'excluded'),
    ('考研就业服务说明会', '曾邀请博士研究生做经验分享，本次向本科生开放。', 'excluded'),
    ('研究生网上选课通知', '本次允许所有本科生申请选修，请按时提交申请。', 'excluded'),
    ('举办校运会田径比赛的通知', '师生均可报名。', 'research_innovation'),
    ('本科生暑期科研奖学金项目指南', '获资助者在实验室参与科研训练。', 'financial_aid'),
    ('毕业生信息填报通知', '全体毕业生须参加，非全日制研究生也在范围内。', 'excluded'),
    ('创新创业训练选修课选课通知', '全体同学可以申请课程。', 'research_innovation'),
    ('某学院举办交流项目说明会的通知', '欢迎同学报名参加。', 'excluded'),
])
def test_evidence_exceptions(model, title, body, must_not_force):
    assert model.policy_decision(title, body)[0] != must_not_force


def test_manifest_requires_pinned_sha_before_parsing(model, tmp_path):
    p = tmp_path / 'candidate.json'
    p.write_text('malformed')
    with pytest.raises(ValueError, match='manifest sha256'):
        model.load_manifest(p, '0' * 64)


def test_allowed_mixed_scope_and_separate_teacher_call(model):
    title = '关于征集大学生创新项目导师申报课题的通知'
    body = '此项征集面向全校教师。课题旨在训练本科生科研能力，教师均可申报。'
    assert model.policy_decision(title, body) == ('excluded', 'staff_task')


def test_classifier_keeps_ids_and_only_scores_observable_inputs(model):
    rows = [{'case_id': k, 'title': '未知事项', 'body': '请阅读材料。'} for k in ('A', 'opaque-98')]
    components = {'learned': [[0.0, 1, 3, 2], [0, 1, 3, 2]]}
    results = model.mix(rows, components, {'learned': 1.0})
    assert [r['case_id'] for r in results] == ['A', 'opaque-98']
    assert [r['prediction'] for r in results] == ['daily', 'daily']
    with pytest.raises(ValueError, match='component'):
        model.mix(rows, components, {'unknown': 1.0})


def test_publisher_suffix_cannot_cut_a_hyphenated_award_name(model):
    title = '关于企业-联合助学金补充评选的通知-外语学院'
    assert model.primary_title(title) == '关于企业-联合助学金补充评选的通知'
    assert model.policy_decision(title, '现面向全校学生接受申请。')[0] == 'financial_aid'


@pytest.mark.parametrize(('title', 'body', 'label'), [
    ('本学期研究生选课通知', '各位研究生请按期选课。请同时承担本科和研究生课程教学工作的教师核对。', 'excluded'),
    ('科研实践项目学生报名', '本项目为本科生提供早期科研实践，欢迎报名参加。', 'research_innovation'),
    ('学生发展基金申请通知', '申请对象为家庭经济困难本科生。', 'financial_aid'),
    ('大学生社会实践团队招募', '请同学报名，参加团队并提交项目计划。', 'daily'),
    ('学院运动会竞赛规程', '运动会设本科生组和教工组，可组队报名。', 'daily'),
    ('下学期本科生教学任务申报', '各位老师好，请愿意承担教学任务的老师提交材料。', 'excluded'),
])
def test_action_and_recipient_relations(model, title, body, label):
    assert model.policy_decision(title, body)[0] == label


def test_frozen_outputs_cannot_be_replaced(model, tmp_path):
    from v3_model_development import write
    dest = tmp_path / 'sealed.json'
    write(dest, {'revision': 1}, exclusive=True)
    with pytest.raises(FileExistsError):
        write(dest, {'revision': 2}, exclusive=True)
    import json
    assert json.loads(dest.read_bytes()) == {'revision': 1}
