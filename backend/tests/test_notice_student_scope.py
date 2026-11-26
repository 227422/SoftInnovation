"""Student feed must not admit clear staff-only workflows as uncertain policies."""
from datetime import datetime

import pytest

from campus_backend.core.artifacts import make_artifact
from campus_backend.classification.service import analyze_document, personalize
from campus_backend.classification.student_scope import assess_student_scope

NOW = datetime.fromisoformat('2026-10-31T12:00:00+08:00')
PROFILE = {'school': '中南大学', 'college': '计算机学院', 'major': '计算机科学与技术', 'grade': 2}


def document(title, content, body='complete'):
    return make_artifact('document', 'scope-notice', 'v1', {
        'title': title, 'content': content, 'body_status': body,
        'school': '中南大学', 'source_name': '学院通知',
        'source_url': 'https://example.csu.edu.cn/info/1.htm',
        'published_at': '2026-10-30', 'segments': [{'text': content, 'location': 'article'}],
    }, now=NOW)


@pytest.mark.parametrize('title,content', [
    ('粉末冶金研究院本科课堂教学准入实施细则',
     '为加强我院教师培养过程管理，进一步提升我院教师的\n教学能力和教学质量，对于目前尚\n未授课的教师申请授课，或在任授课教师申请新上核心课程，\n都必须完成课堂教学准入流程。资格申请条件：已获得国家高等教育教师资格证的教师。'),
    ('中南大学职工出国相关表格', '出国离岗人员工作交接情况表。所在系教学副主任签字。'),
    ('教学大纲格式', '教学大纲模板\n课程在培养方案中的地位、目的和任务\n大纲制订：\n大纲审核：\n大纲批准：'),
    ('教职工出访手续办理通知', '本次办理仅限在职教职工。请提交工作交接表。'),
])
def test_recent_staff_only_documents_are_excluded_from_public_admission_and_personal_feed(title, content):
    doc = document(title, content)
    shared = analyze_document(doc, now=NOW)
    assert shared['payload']['lifecycle']['admitted'] is False
    assert shared['payload']['student_scope']['status'] == 'excluded'
    result = personalize(doc, PROFILE, now=NOW, analysis=shared)
    assert result['visibility']['visible'] is False
    assert result['routing']['notify_eligible'] is False
    assert result['student_scope']['evidence']
    for item in result['student_scope']['evidence']:
        assert item['quote'] in doc['payload'][item['source']]


@pytest.mark.parametrize('title,content', [
    ('师生共同出国交流活动报名通知', '面向全校学生和教师，学生报名截止2026年11月20日。'),
    ('学生出国交流手续办理指南', '学生出国交流可咨询老师，请同学准备申请表。'),
    ('本科实习教学管理办法', '本办法现行有效，规定学生实习纪律与学生实习安全要求，由教师指导实习。'),
    ('国际中文教师奖学金申请办法', '本项目面向优秀学生和在职中文教师。学生申请截止2026年11月20日。'),
    ('教师资格考试报名通知', '面向全校学生。学生报名截止2026年11月20日。'),
    ('本科课堂教学准入细则说明会', '欢迎全校学生和教师参加，学生报名截止2026年11月20日。'),
    ('职工出国与学生交流表格', '学生与教职工均可申请。学生申请截止2026年11月20日。'),
])
def test_student_and_joint_opportunities_are_not_removed_by_staff_filter(title, content):
    result = personalize(document(title, content), PROFILE, now=NOW)
    assert result['visibility']['visible'] is True
    assert result['student_scope']['status'] == 'not_excluded'


def test_title_only_ignores_unread_body_when_checking_staff_scope():
    doc = document('学生交流报名通知', '仅限教师办理出访手续。教师申请授课。', body='title_only')
    result = personalize(doc, PROFILE, now=NOW)
    assert result['visibility']['visible'] is True
    assert result['student_scope']['status'] == 'not_excluded'


def test_recent_staff_form_can_be_excluded_from_public_title_without_body():
    result = personalize(document('中南大学职工出国相关表格', '', body='title_only'), PROFILE, now=NOW)
    assert result['visibility']['visible'] is False
    assert result['student_scope']['evidence'][0]['source'] == 'title'


def test_staff_gate_does_not_treat_student_employment_or_teacher_mentions_as_staff_only():
    # This gate does not broaden the unchanged legacy classifier's recruitment rules.
    for title, content in [
        ('面向应届毕业生的中学教师岗位招聘', '应届毕业生可以申请，提供就业岗位。'),
        ('教师答疑时间安排', '同学可以在每周三前往办公室咨询课程问题。'),
    ]:
        assert assess_student_scope({'title': title, 'content': content, 'body_status': 'full'})['status'] == 'not_excluded'
