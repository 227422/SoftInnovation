import pytest
from pydantic import ValidationError

from campus_backend.documents.models import DocumentAsset, DocumentBundle, DocumentSegment


def run(title, *texts, body_status='full', attachments=()):
    from campus_backend.classification.simple_rules import analyze_simple_rules

    return analyze_simple_rules(DocumentBundle(
        notice_id='demo', content_version='1', title=title, body_status=body_status,
        source_url='https://example.edu/test', input_fingerprint='a' * 64,
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),)
        + tuple(DocumentSegment(id=f'p{i}', kind='body', text=value, location='html:body')
                for i, value in enumerate(texts))
        + tuple(DocumentSegment(id=f'{asset.asset_id}:{i}', kind='attachment', text=value,
                                asset_id=asset.asset_id, asset_hash=asset.asset_hash, location=f'sheet:日程/row:{i}')
                for asset, rows in attachments for i, value in enumerate(rows, 1)),
        assets=tuple(asset for asset, _ in attachments),
    ))


def labels(result, kind):
    return [label for label in result.labels if label.kind == kind]


def test_opportunities_are_boolean_even_when_conditions_or_amounts_are_complex():
    result = run(
        '本科生竞赛通知',
        '符合附件规则并通过复核方可获得志愿服务时长两到三小时、创新学分及课程学分。',
        '体育分按学校规则认定，第二课堂积分以系统结果为准。',
        '可获推免加分、综测加分与补助，具体数额另行公布。',
        '获得一等奖和二等奖或三等奖者颁发荣誉证书，具体条件详见附件。',
    )
    benefit = labels(result, 'benefit')
    assert {label.code for label in benefit} == {
        'volunteer_hours', 'innovation_credit', 'course_credit', 'sports_points',
        'second_classroom_points', 'recommendation_points', 'comprehensive_points',
        'financial_award', 'certificate',
    }
    assert all(label.value is True for label in benefit)
    assert all(set(label.model_dump()) == {'kind', 'code', 'scope', 'evidence', 'value'} for label in benefit)
    assert result.schema_version == 's2-rule-baseline/3'
    assert result.rules_version == '3.1.0'
    assert result.complete


def test_negative_claims_and_existing_certificates_are_not_opportunities():
    result = run(
        '本科生辅修专业报名通知',
        '辅修专业最低要求20学分。微专业开设5门课程，共计13学分。',
        '请提交已取得的获奖证书复印件，证书须与报名表一同提交。',
        '本次不颁发证书、不提供奖金，也不能认定创新学分。没有综测加分。',
        '可获得第二课堂积分但不计入体育分。',
    )
    assert [label.code for label in labels(result, 'benefit')] == ['second_classroom_points']
    assert result.complete


def test_named_scholarship_application_is_a_benefit_but_old_award_evidence_is_not():
    result = run('本科生奖学金申请通知', '申请者必须提交往年获得的奖学金证明。')
    label, = labels(result, 'benefit')
    assert label.code == 'financial_award'
    assert {ref.segment_id for ref in label.evidence} == {'title'}


def test_dates_keep_each_purpose_and_endpoint_and_exclude_unit_reporting():
    result = run(
        '本科生创新竞赛通知',
        '报名时间：11月13日08:30至15日09:00。申请截止至11月17日。',
        '须提交材料，提交截止至11月18日。各学院汇总并于11月19日前报送材料。',
        '初赛于11月20日举行。决赛时间另行通知。',
        '名单公示期：11月21日至11月24日。公示期间如有异议，请书面署名反馈。',
        '本办法自2026年11月1日施行，有效至2027年11月1日。',
    )
    dates = labels(result, 'date')
    assert [label.code for label in dates] == [
        'registration', 'application', 'submission', 'event', 'event', 'event', 'objection', 'policy_validity',
    ]
    registration, application, submission, initial, final, publicity, objection, validity = dates
    assert (registration.value.start.month_day, registration.value.start.time) == ('11-13', '08:30')
    assert (registration.value.end.month_day, registration.value.end.time) == ('11-15', '09:00')
    assert application.value.start is None and application.value.end.month_day == '11-17'
    assert submission.value.start is None and submission.value.end.month_day == '11-18'
    assert initial.scope.phase == '初赛'
    assert registration.value.state == 'unknown'
    assert final.value.state == 'unknown'
    assert final.value.start.reason == 'to_be_announced'
    assert publicity.scope.phase == '公示'
    assert objection.value.end.month_day == '11-24'
    assert (validity.value.start.date, validity.value.end.date) == ('2026-11-01', '2027-11-01')
    assert all(set(label.value.model_dump()) == {'start', 'end', 'state', 'explicit_long_term'} for label in dates)
    assert any(gap.code == 'date_unresolved' for gap in result.gaps)


def test_unstated_validity_and_explicit_long_term_are_distinct():
    missing = run('本科生转专业通知', '本办法目前仍然有效。')
    assert labels(missing, 'date') == []
    assert missing.complete
    assert [label.value for label in labels(missing, 'status')] == ['policy_valid']
    long_term = run('本科生转专业通知', '本办法长期有效。')
    label, = labels(long_term, 'date')
    assert label.code == 'policy_validity'
    assert label.value.explicit_long_term is True
    assert label.value.start is None and label.value.end is None


def test_same_kind_scoped_labels_survive_and_scope_contains_only_audience():
    result = run(
        '竞赛通知',
        '面向文学院2025级本科生中成绩排名前20%的学生，须提交获奖证书。',
        '初赛：文学院2025级本科生报名截止2026年11月22日，数学院2026级本科生报名截止2026年11月23日。',
        '初赛A组可获得证书。复赛B组可获得证书。',
    )
    targets = labels(result, 'audience')
    assert {(label.value.audience, label.value.college) for label in targets} == {
        ('2025级本科生', '文学院'), ('2026级本科生', '数学院'),
    }
    assert {label.scope.track for label in labels(result, 'benefit')} == {'A组', 'B组'}
    dates = labels(result, 'date')
    assert [(label.value.end.date, label.scope.audience_groups[0].college) for label in dates] == [
        ('2026-11-22', '文学院'), ('2026-11-23', '数学院'),
    ]
    assert result.complete


def test_current_window_replaces_historical_deadline_with_evidence():
    result = run('竞赛报名通知', '本科生报名截止原为2026年11月20日，现延长至2026年11月25日。')
    label, = labels(result, 'date')
    assert label.value.end.date == '2026-11-25'
    assert label.value.state == 'rescheduled'
    assert '原为2026年11月20日' in label.evidence[0].quote


def test_two_unreconciled_deadlines_for_the_same_scope_are_conflicting():
    result = run('竞赛报名通知', '本科生报名截止11月20日。', '本科生报名截止11月21日。')
    assert [label.value.state for label in labels(result, 'date')] == ['conflicting', 'conflicting']
    assert {gap.code for gap in result.gaps} == {'date_conflict'}


def test_document_statuses_keep_their_own_product_labels():
    result = run(
        '本科生竞赛结果公示',
        '本次比赛已结束。本通知已废止。',
    )
    assert {label.value for label in labels(result, 'status')} == {
        'result_publicity', 'event_ended', 'policy_expired',
    }


def test_excluded_notice_has_no_product_tags():
    result = run('教师招聘通知', '报名时间：11月13日。录用者将获得奖金。')
    assert result.category == 'excluded'
    assert not result.labels
    assert result.complete


def test_v3_date_rejects_legacy_requirements():
    from campus_backend.classification.simple_labels import SimpleDateValue

    with pytest.raises(ValidationError):
        SimpleDateValue(start={'kind': 'month_day', 'month_day': '11-13'},
                        requirement={'operator': 'text', 'items': ('签到',)})


@pytest.mark.parametrize('amount', [1, 1.0, 'true'])
def test_benefit_protocol_rejects_numeric_and_string_values(amount):
    from campus_backend.classification.simple_labels import SimpleBenefitLabel

    with pytest.raises(ValidationError):
        SimpleBenefitLabel(code='financial_award', value=amount, scope={},
                           evidence=[{'segment_id': 'p0', 'quote': '发放奖学金'}])


def test_audience_keeps_major_and_pairs_colleges_with_their_own_classes():
    result = run(
        '校园竞赛通知',
        '面向计算机学院软件工程专业2024级本科生、文学院中文2401班。',
        '材料提交至法学院办公室，须携带成绩单。',
    )
    assert {(label.value.college, label.value.audience, label.value.class_name)
            for label in labels(result, 'audience')} == {
        ('计算机学院', '软件工程专业2024级本科生', None),
        ('文学院', None, '中文2401班'),
    }


def test_submission_location_does_not_become_audience_scope():
    result = run('本科生竞赛通知', '请于2026年11月20日前将材料提交至法学院办公室。')
    date, = labels(result, 'date')
    assert date.code == 'submission'
    assert tuple(group.college for group in date.scope.audience_groups) == (None,)
    assert [label.value.audience for label in labels(result, 'audience')] == ['本科生']


def test_different_named_items_keep_their_own_benefits_and_dates():
    result = run(
        '本科竞赛通知',
        '创新计划报名截止2026年11月20日。实践计划报名截止2026年11月21日。',
        '创新计划参加者可获得证书。实践计划参加者可获得证书。',
    )
    assert {(label.scope.action, label.value.end.date) for label in labels(result, 'date')} == {
        ('创新计划', '2026-11-20'), ('实践计划', '2026-11-21'),
    }
    assert {label.scope.action for label in labels(result, 'benefit')} == {'创新计划', '实践计划'}
    assert result.complete


def test_audience_keeps_college_class_pairs_and_excludes_organizer():
    result = run(
        '校园讲座通知',
        '面向工学院2401班和商学院2402班学生。',
        '该讲座由计算机学院教师组织，活动时间为2026年11月20日。',
    )
    assert {(label.value.college, label.value.class_name) for label in labels(result, 'audience')} == {
        ('工学院', '2401班'), ('商学院', '2402班'),
    }
    date, = labels(result, 'date')
    assert all(group.college != '计算机学院' for group in date.scope.audience_groups)


def test_explicit_notice_wide_denial_overrides_an_award_title_without_positive_claim():
    result = run('本科生奖学金申请通知', '本次不设奖金或奖学金，参与者不颁发任何证书。')
    assert labels(result, 'benefit') == []


def test_range_with_unresolved_end_keeps_explicit_start_and_pending_end():
    result = run('本科生竞赛通知', '报名时间自2026年11月1日起，截止时间待定。')
    date, = labels(result, 'date')
    assert date.value.start.date == '2026-11-01'
    assert date.value.end.reason == 'to_be_announced'
    assert date.value.state == 'unknown'


def test_policy_validity_pairs_adjacent_endpoints_and_applies_single_policy():
    result = run('本科生转专业通知', '本办法自2026年11月1日起施行。有效期至2027年11月1日。')
    date, = labels(result, 'date')
    assert date.code == 'policy_validity'
    assert (date.value.start.date, date.value.end.date) == ('2026-11-01', '2027-11-01')


def test_providing_money_is_an_award_and_submitting_award_records_is_material():
    result = run(
        '本科生创新竞赛通知',
        '竞赛组委会向获奖者提供奖金。学生须提交以往获得的荣誉证书。',
    )
    assert [label.code for label in labels(result, 'benefit')] == ['financial_award']


def test_multiple_delimited_audiences_keep_college_population_association():
    result = run('创新竞赛通知', '报名对象：工学院本科生、商学院研究生。')
    assert {(label.value.college, label.value.audience) for label in labels(result, 'audience')} == {
        ('工学院', '本科生'), ('商学院', '研究生'),
    }


def test_phase_prefix_applies_to_each_scoped_window_in_the_clause():
    result = run(
        '本科生竞赛通知',
        '初赛：文学院报名截止2026年11月22日，数学院报名截止2026年11月23日。',
    )
    assert [label.scope.phase for label in labels(result, 'date')] == ['初赛', '初赛']


def test_qualifier_free_following_end_marker_retains_both_dates():
    result = run('本科生竞赛通知', '2026年11月20日开始报名，2026年11月21日截止。')
    date, = labels(result, 'date')
    assert (date.value.start.date, date.value.end.date) == ('2026-11-20', '2026-11-21')


def test_reference_to_post_award_certificate_number_is_not_an_award_offer():
    result = run('本科生竞赛通知', '往届获奖者证书编号已登记。')
    assert labels(result, 'benefit') == []


@pytest.mark.parametrize('location', ['在商学院举行', '于商学院报告厅举行'])
def test_event_venue_does_not_override_declared_audience(location):
    result = run('本科生竞赛通知', '面向工学院本科生。', f'比赛于2026年11月20日{location}。')
    audience, = labels(result, 'audience')
    assert audience.value.college == '工学院'
    date, = labels(result, 'date')
    assert date.scope.audience_groups == (audience.value,)


def test_shared_declared_audience_applies_to_unqualified_labels():
    result = run(
        '竞赛通知', '面向工学院本科生、商学院研究生。',
        '报名截止2026年11月20日。完成活动可获得证书。',
    )
    expected = {label.value for label in labels(result, 'audience')}
    assert len(expected) == 2
    relevant = (*labels(result, 'date'), *labels(result, 'benefit'))
    assert len(relevant) == 2
    assert all(set(label.scope.audience_groups) == expected for label in relevant)


def test_audience_from_one_scoped_window_is_not_imputed_to_another():
    result = run(
        '竞赛通知',
        '初赛：工学院本科生报名截止2026年11月20日。复赛报名截止2026年11月21日。',
    )
    initial, final = labels(result, 'date')
    assert initial.scope.audience_groups[0].college == '工学院'
    assert final.scope.audience_groups == ()


def test_schedule_rows_merge_equivalent_slots_without_reassigning_groups():
    result = run(
        '本科生考试通知', '面向全日制本科生。',
        '校区\t学院\t班级\t考试时间',
        '东校区\t工学院\t2401班\t2026年11月13日08:30-09:00',
        '东校区\t商学院\t2402班\t2026年11月13日08:30-09:00',
        '西校区\t工学院\t2403班\t2026年11月13日08:30-09:00',
    )
    first, second = labels(result, 'date')
    assert [(g.college, g.class_name) for g in first.scope.audience_groups] == [
        ('工学院', '2401班'), ('商学院', '2402班'),
    ]
    assert {ref.segment_id for ref in first.evidence} == {'p0', 'p1', 'p2', 'p3'}
    assert {g.audience for g in first.scope.audience_groups} == {'全日制本科生'}
    assert [(label.value.audience, label.value.class_name) for label in labels(result, 'audience')] == [
        ('全日制本科生', None),
    ]
    assert [(g.campus, g.class_name) for g in second.scope.audience_groups] == [('西校区', '2403班')]


def test_exam_duration_and_unrelated_attachment_mention_are_not_pending_dates():
    result = run(
        '本科生考试通知',
        '考试时间为50分钟，合格分数为90分。',
        '参加考试的学习要求详见附件1。',
        '考试日期另行通知。',
    )
    date, = labels(result, 'date')
    assert date.value.start.reason == 'to_be_announced'
    assert [ref.segment_id for ref in date.evidence] == ['p2', 'title']


def test_referential_colleges_do_not_create_named_audience_groups():
    result = run(
        '本科生转专业通知',
        '面向计算机学院2024级本科生。相关学院负责组织报名，所在学院申请审核，转入学院报名协调。',
    )
    assert {label.value.college for label in labels(result, 'audience')} == {'计算机学院'}


@pytest.mark.parametrize('available', [True, False])
def test_attachment_schedule_pointer_only_remains_pending_when_schedule_is_unread(available):
    asset = DocumentAsset(asset_id='schedule', asset_hash='b' * 64)
    schedule = (
        '学院\t班级\t考试时间',
        '工学院\t2401班\t2026年11月13日08:30-09:00',
        '工学院\t2402班\t2026年11月13日09:00-09:30',
    )
    result = run('本科生考试通知', '具体考试安排详见附件。',
                 attachments=((asset, schedule if available else ()),))
    windows = labels(result, 'date')
    if available:
        assert [window.value.state for window in windows] == ['announced', 'announced']
        assert [window.value.start.time for window in windows] == ['08:30', '09:00']
        assert all('p0' in {ref.segment_id for ref in window.evidence} for window in windows)
        assert result.complete
    else:
        window, = windows
        assert window.value.start.reason == 'unresolved'
        assert {gap.code for gap in result.gaps} == {'date_unresolved', 'attachment_unread'}


def test_multiple_schedule_attachments_do_not_resolve_an_ambiguous_reference():
    first = DocumentAsset(asset_id='first', asset_hash='b' * 64)
    second = DocumentAsset(asset_id='second', asset_hash='c' * 64)
    result = run(
        '本科生考试通知', '具体考试安排详见附件。',
        attachments=(
            (first, ('学院\t班级\t考试时间', '工学院\t2401班\t2026年11月13日08:30-09:00')),
            (second, ('学院\t班级\t考试时间', '工学院\t2401班\t2026年11月15日08:30-09:00')),
        ),
    )
    assert [label.value.state for label in labels(result, 'date')] == ['unknown', 'announced', 'announced']
