"""Collector adapter behavior: old routing cannot bypass collection lifecycle."""
from copy import deepcopy
from datetime import datetime
import json
import subprocess
import sys

import pytest

from campus_backend.classification.service import analyze_document, personalize
from campus_backend.classification.lifecycle import evaluate_visibility


def moment(value):
    return datetime.fromisoformat(value)


def document(content='', *, title='大学生数学竞赛报名通知', published='2026-09-01', body='complete', version='v1'):
    return {'schema_version': '1.0', 'stage': 'document', 'notice_id': 'competition-1',
            'content_version': version, 'run_id': 'test-input', 'created_at': '2026-10-01T00:00:00+08:00',
            'producer': {'name': 'fixture', 'version': '1.0'}, 'status': 'complete',
            'errors': [], 'input_refs': [], 'payload': {'title': title, 'content': content,
            'body_status': body, 'source_name': '计算机学院', 'source_url': 'https://example.csu.edu.cn/a',
            'published_at': published, 'school': '中南大学',
            'segments': [{'text': content, 'asset_id': 'body', 'page': 1, 'location': 'article'}]}}


def test_minute_boundary_keeps_expired_registration_visible_despite_archive():
    doc = document('面向全校学生。学生报名截止2026年10月1日10:00。比赛于2026年11月1日结束。')
    result = personalize(doc, {'school': '中南大学'}, now=moment('2026-10-15T10:00:00+08:00'))
    assert result['routing']['status'] == 'archive'
    assert result['urgency']['status'] == 'expired'
    assert result['visibility']['visible'] is True
    assert result['visibility']['hide_at'] == '2026-10-15T10:00:00+08:00'
    result = personalize(doc, None, now=moment('2026-10-15T10:00:00.000001+08:00'))
    assert result['visibility']['visible'] is False


def test_date_only_window_ends_at_beijing_day_end():
    doc = document('学生报名截止2026年10月1日。比赛于2026年11月1日结束。')
    assert personalize(doc, None, now=moment('2026-10-15T15:59:59+00:00'))['visibility']['visible']
    assert not personalize(doc, None, now=moment('2026-10-15T16:00:00+00:00'))['visibility']['visible']


def test_confirmed_extension_recomputes_window_from_new_deadline():
    doc = document('学生报名原截止2026年10月1日，现报名截止延期至2026年10月10日。比赛于2026年11月1日结束。')
    result = personalize(doc, None, now=moment('2026-10-20T12:00:00+08:00'))
    assert result['visibility']['visible']
    assert result['lifecycle']['registration_deadline']['value'] == '2026-10-10'
    assert result['visibility']['hide_at'] == '2026-10-24T23:59:59.999999+08:00'


@pytest.mark.parametrize('text', [
    '各学院报名汇总截止2026年10月1日。',
    '学生缴费截止2026年10月1日。',
    '学生提交作品截止2026年10月1日。',
    '报名通知。各学院于2026年10月1日前报送汇总表。',
    '报名方式见附件。学生申请奖学金截止2026年10月1日。',
])
def test_department_and_other_action_deadlines_do_not_trigger_registration_window(text):
    result = personalize(document(text, published='2026-10-01'), None,
                         now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['status'] == 'unknown'
    assert result['visibility']['hide_at'] is None


def test_non_competition_deadline_does_not_use_fourteen_days():
    result = personalize(document('学生报名截止2026年10月1日。', title='讲座报名通知'), None,
                         now=moment('2026-10-05T12:00:00+08:00'))
    assert not result['visibility']['visible']
    assert result['visibility']['hide_at'] is None


def test_initially_finished_competition_excluded_but_previously_admitted_retained():
    doc = document('学生报名截止2026年10月1日。比赛于2026年10月3日结束。')
    now = moment('2026-10-05T12:00:00+08:00')
    first = personalize(doc, None, now=now)
    assert first['lifecycle']['admitted'] is False
    assert not first['visibility']['visible']
    doc['payload']['first_seen_at'] = '2026-09-30T12:00:00+08:00'
    previous = personalize(doc, None, now=now)
    assert previous['lifecycle']['admitted'] is True
    assert previous['visibility']['visible'] is True
    assert previous['lifecycle']['validity']['status'] == 'expired'


@pytest.mark.parametrize('content,title,want,status', [
    ('本办法现行有效。', '学生奖学金管理办法', True, 'valid'),
    ('本办法已于2026年9月1日废止。', '学生奖学金管理办法', False, 'expired'),
    ('请阅读本办法。', '学生奖学金管理办法', True, 'unknown'),
    ('学生申请截止2026年12月1日。', '奖学金申请通知', True, 'valid'),
    ('请同学阅读。', '学生通知', False, 'unknown'),
])
def test_old_policy_and_active_deadline_are_not_limited_to_thirty_days(content, title, want, status):
    result = personalize(document(content, title=title, published='2020-01-01'), None,
                         now=moment('2026-10-31T12:00:00+08:00'))
    assert result['visibility']['visible'] is want
    assert result['lifecycle']['validity']['status'] == status


def test_generic_thirty_day_boundary_and_unknown_publication():
    for published, visible in [('2026-10-01', True), ('2026-09-30', False), (None, True)]:
        result = personalize(document('请阅读通知。', title='学生通知', published=published), None,
                             now=moment('2026-10-31T12:00:00+08:00'))
        assert result['visibility']['visible'] is visible
    assert result['lifecycle']['admission_status'] == 'pending_confirmation'


def test_title_only_does_not_trust_hidden_body_or_structured_deadline():
    doc = document('仅限计算机学院。学生报名截止2026年10月1日。本办法现行有效。', body='title_only')
    doc['payload']['audience'] = {'colleges': ['计算机学院']}
    result = personalize(doc, {'school': '中南大学', 'college': '外国语学院'},
                         now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['status'] == 'unknown'
    assert result['relevance']['status'] == 'possible'
    assert result['importance']['tentative'] is True


def test_cross_college_and_shared_analysis_do_not_contain_profile_conclusions():
    doc = document('面向全校学生。学生报名截止2026年12月1日。')
    now = moment('2026-10-31T12:00:00+08:00')
    shared = analyze_document(doc, now=now)
    before = deepcopy(shared)
    assert shared['stage'] == 'analysis'
    assert not {'relevance', 'importance', 'routing', 'profile', 'rank'} & shared['payload'].keys()
    assert shared['payload']['evidence']['segments'][0]['asset_id'] == 'body'
    result = personalize(doc, {'school': '中南大学', 'college': '外国语学院'}, now=now, analysis=shared)
    assert result['relevance']['status'] == 'relevant'
    assert result['visibility']['visible']
    assert shared == before
    other = personalize(doc, {'school': '另一大学'}, now=now, analysis=shared)
    assert not other['visibility']['visible']
    assert shared == before


def test_conflicting_registration_dates_remain_unknown_and_do_not_hide_on_invented_date():
    doc = document('学生报名截止2026年10月1日。学生报名截止2026年10月10日。')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['status'] == 'ambiguous'
    assert result['visibility']['hide_at'] is None
    assert result['visibility']['status'] == 'pending_confirmation'


def test_analysis_different_content_version_is_rejected():
    doc = document('学生报名截止2026年12月1日。')
    analysis = analyze_document(doc)
    doc['content_version'] = 'v2'
    with pytest.raises(ValueError, match='version|版本'):
        personalize(doc, None, analysis=analysis)


def test_visibility_accepts_explicit_first_seen():
    doc = document('学生报名截止2026年10月1日。比赛于2026年10月3日结束。')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    lifecycle = evaluate_visibility(doc['payload'], result, now=moment('2026-10-05T12:00:00+08:00'),
                                    first_seen=moment('2026-09-30T00:00:00+08:00'))
    assert lifecycle['visibility']['visible']


def test_independent_cli_outputs_analysis_and_personal_result(tmp_path):
    path = tmp_path / 'document.json'
    path.write_text(json.dumps(document('面向全校学生。学生报名截止2026年12月1日。'), ensure_ascii=False))
    process = subprocess.run([sys.executable, '-m', 'campus_backend.classification.cli', str(path),
                              '--now', '2026-10-31T12:00:00+08:00'], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)['stage'] == 'analysis'
    profile = tmp_path / 'profile.json'
    profile.write_text('{"school":"中南大学"}')
    process = subprocess.run([sys.executable, '-m', 'campus_backend.classification.cli', str(path),
                              '--profile', str(profile), '--now', '2026-10-31T12:00:00+08:00'],
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result['stage'] == 'personal_result'
    assert result['payload']['visibility']['visible']


def test_shared_audience_warnings_do_not_include_missing_personal_profile():
    analysis = analyze_document(document('面向全校学生。'))
    assert all('个人资料' not in item for item in analysis['payload']['audience']['warnings'])


def test_incidental_competition_mention_does_not_extend_other_registration():
    doc = document('面向全校学生。学生报名截止2026年10月1日。报名者曾获竞赛奖项优先。',
                   title='学生社团报名通知', published='2026-10-01')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['visibility']['hide_at'] is None
    assert not result['visibility']['visible']


def test_extension_without_registration_action_cannot_inherit_other_deadline():
    doc = document('学生报名截止2026年10月1日。学生缴费截止2026年10月2日，现延期至2026年10月10日。')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['value'] == '2026-10-01'


def test_missing_year_never_creates_confirmed_fourteen_day_hide_date():
    doc = document('学生报名截止10月1日。比赛于11月1日结束。', published='2026-09-01')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['status'] == 'ambiguous'
    assert result['visibility']['hide_at'] is None


def test_previously_admitted_event_keeps_window_when_end_update_has_no_date():
    doc = document('学生报名截止2026年10月1日。本次比赛已结束。')
    doc['payload']['first_seen_at'] = '2026-09-30T00:00:00+08:00'
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['visibility']['visible']
    assert result['lifecycle']['validity']['status'] == 'expired'


def test_empty_body_cannot_be_marked_complete_by_analysis():
    analysis = analyze_document(document('', body='complete'))
    assert analysis['payload']['body_status'] == 'title_only'


def test_repeal_of_old_policy_does_not_expire_new_policy():
    doc = document('本办法现行有效，自发布之日起施行，原办法同时废止。',
                   title='学生奖学金管理办法', published='2020-01-01')
    result = personalize(doc, None, now=moment('2026-10-31T12:00:00+08:00'))
    assert result['lifecycle']['validity']['status'] == 'valid'
    assert result['visibility']['visible']


def test_extension_can_use_adjacent_explicit_registration_context():
    doc = document('学生报名原截止2026年10月1日，现延期至2026年10月10日。比赛于2026年11月1日结束。')
    result = personalize(doc, None, now=moment('2026-10-20T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['value'] == '2026-10-10'
    assert result['visibility']['hide_at'] == '2026-10-24T23:59:59.999999+08:00'


def test_past_department_deadline_does_not_exclude_student_unknown_action():
    doc = document('各学院报名汇总截止2026年10月1日。', published='2026-10-01')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['visibility']['visible']
    assert result['lifecycle']['validity']['status'] == 'unknown'


@pytest.mark.parametrize('text,want', [
    ('本次比赛报名延期至2026年10月10日。比赛于2026年11月1日结束。', '2026-10-10'),
    ('比赛报名原截止2026年10月1日，现延长至2026年10月10日。比赛于2026年11月1日结束。', '2026-10-10'),
    ('各学院报名延期至2026年10月10日。', None),
    ('学生报名时间截至2026年10月10日。', '2026-10-10'),
])
def test_explicit_registration_extension_without_word_cutoff_is_supported(text, want):
    result = personalize(document(text), None, now=moment('2026-10-20T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['value'] == want


def test_closed_registration_does_not_claim_competition_has_expired_without_end_evidence():
    doc = document('学生报名截止2026年10月1日。')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['urgency']['status'] == 'expired'
    assert result['lifecycle']['registration_status'] == 'closed'
    assert result['lifecycle']['validity']['status'] == 'unknown'
    assert result['visibility']['visible']
    assert result['visibility']['status'] == 'pending_confirmation'


def test_unquoted_structured_date_cannot_make_old_document_active():
    doc = document('具体安排待确认。', title='学生申请通知', published='2020-01-01')
    doc['payload']['deadline'] = {'value': '2026-12-01', 'role': 'student',
                                'evidence': '这句截止依据没有出现在官方原文'}
    result = personalize(doc, None, now=moment('2026-10-31T12:00:00+08:00'))
    assert result['deadline']['status'] == 'unknown'
    assert not result['visibility']['visible']


def test_document_semantic_metadata_cannot_invent_college_restriction():
    doc = document('面向全校学生。学生报名截止2026年12月1日。')
    doc['payload']['audience'] = {'colleges': ['计算机学院']}
    result = personalize(doc, {'school': '中南大学', 'college': '外国语学院'},
                         now=moment('2026-10-31T12:00:00+08:00'))
    assert result['relevance']['status'] == 'relevant'
    assert result['visibility']['visible']


def test_extension_of_unrecognized_other_action_cannot_inherit_earlier_registration():
    doc = document('学生报名截止2026年10月1日。资格审核截止2026年10月3日，现延期至2026年10月10日。')
    result = personalize(doc, None, now=moment('2026-10-05T12:00:00+08:00'))
    assert result['lifecycle']['registration_deadline']['value'] == '2026-10-01'


def test_public_analysis_exposes_admission_without_personal_matching_fields():
    doc = document('面向全校学生。学生报名截止2026年10月1日。比赛于2026年11月1日结束。')
    now = moment('2026-10-05T12:00:00+08:00')
    shared = analyze_document(doc, now=now)
    payload = shared['payload']
    assert payload['lifecycle']['admitted'] is True
    assert payload['lifecycle']['registration_status'] == 'closed'
    assert payload['visibility']['visible'] is True
    assert not {'relevance', 'importance', 'routing', 'profile', 'rank'} & payload.keys()
    saved = deepcopy(shared)
    personal = personalize(doc, {'school': '另一学校'}, now=now, analysis=shared)
    assert personal['visibility']['visible'] is False
    assert payload['visibility']['visible'] is True
    assert payload['lifecycle']['admitted'] is True
    assert shared == saved


def test_public_first_admission_excludes_undated_finished_competition():
    doc = document('本次比赛已结束。', published='2026-10-01')
    now = moment('2026-10-05T12:00:00+08:00')
    shared = analyze_document(doc, now=now)
    assert shared['payload']['event_end']['status'] == 'ended'
    assert shared['payload']['event_end']['value'] is None
    assert shared['payload']['lifecycle']['admitted'] is False
    assert shared['payload']['visibility']['visible'] is False
    personal = personalize(doc, None, now=now)
    direct = evaluate_visibility(doc['payload'], personal, now=now, first_seen=None)
    assert direct['lifecycle']['admitted'] is False
    assert direct['visibility']['visible'] is False
