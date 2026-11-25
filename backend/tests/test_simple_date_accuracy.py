"""Real-error shapes with different names/dates; no corpus answers in the rules."""
from test_simple_tags import run, labels
from campus_backend.documents.models import DocumentAsset, DocumentBundle, DocumentSegment


def test_student_reporting_to_college_is_not_internal_unit_reporting():
    result = run('关于2028年本科生转专业工作的通知',
                 '报名时间：有相关需求的学生请于10月8日前填报申请表报送至相关学院。')
    date, = labels(result, 'date')
    assert date.code == 'registration'
    assert date.value.end.date == '2028-10-08'
    assert date.value.start is None


def test_scheduled_event_under_arrangement_heading_keeps_purpose():
    result = run('2028年创新培养班面试考核通知', '一、面试安排\n时间：10月10日8:00-12:30。')
    date, = labels(result, 'date')
    assert date.code == 'event'
    assert date.value.start.date == '2028-10-10'
    assert (date.value.start.time, date.value.end.time) == ('08:00', '12:30')


def test_explicit_current_notice_year_resolves_month_day_but_cohort_does_not():
    a = run('2028年本科生考试通知', '考试时间：11月3日。')
    assert labels(a, 'date')[0].value.start.date == '2028-11-03'
    b = run('2028级本科生考试通知', '考试时间：11月3日。')
    assert labels(b, 'date')[0].value.start.kind == 'month_day'
    c = run('2027—2028学年本科生考试通知', '考试时间：11月3日。')
    assert labels(c, 'date')[0].value.start.kind == 'month_day'


def test_signing_date_is_not_a_second_event_and_explicit_other_year_is_preserved():
    result = run('2028年本科生竞赛通知',
                 '报名时间：2027年11月3日至11月5日。\n本科生院\n2028年10月1日')
    date, = labels(result, 'date')
    assert date.value.start.date == '2027-11-03'
    assert date.value.end.date == '2027-11-05'


def test_registration_now_is_not_policy_validity():
    result = run('2028年社团成员注册通知', '注册时间：即日起至7月2日中午12点。')
    date, = labels(result, 'date')
    assert date.code == 'registration'
    assert date.value.start.kind == 'relative'
    assert date.value.end.date == '2028-07-02'
    assert date.value.end.time == '12:00'


def test_single_event_does_not_steal_objection_or_prior_registration_date():
    result = run('2028年大学生竞赛获奖公示',
                 '经过报名、初赛，比赛于6月1日结束。现将获奖名单公示，公示时间为6月2日至6月5日。')
    dates = labels(result, 'date')
    assert {d.code for d in dates} == {'event'}
    assert any(d.value.end and d.value.end.date == '2028-06-01' for d in dates)
    assert any(d.value.start and d.value.start.date == '2028-06-02' for d in dates)


def test_pdf_primary_is_only_promoted_when_readable_first_page_matches_notice_title():
    from campus_backend.classification.simple_rules import analyze_simple_rules
    title = '2028年人工智能微专业选拔实施办法'
    asset = DocumentAsset(asset_id='main', asset_hash='b' * 64)
    doc = DocumentBundle(notice_id='x', content_version='1', title=title,
        source_url='https://example.edu/n', body_status='full', input_fingerprint='a' * 64,
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),
            DocumentSegment(id='pdf', kind='attachment', asset_id='main', asset_hash='b' * 64,
                            page=1, location='page:1', text=title+'\n一、报名对象\n面向全校本科生。\n二、报名时间\n2028年4月9日至4月13日。')),
        assets=(asset,))
    result = analyze_simple_rules(doc)
    assert labels(result, 'audience')[0].value.audience == '全校本科生'
    assert labels(result, 'date')[0].value.end.date == '2028-04-13'
    assert not any(g.code == 'body_incomplete' for g in result.gaps)
    assert doc.primary_asset_ids == ()
    assert result.input_fingerprint == doc.input_fingerprint


def test_relative_publicity_objection_window_is_kept_without_inventing_calendar_date():
    result = run('培养班录取名单公示', '如对公示名单有异议，请于公示开始后三天内反馈。')
    date, = labels(result, 'date')
    assert date.code == 'objection'
    assert date.value.start.kind == 'relative'
    assert date.value.end.kind == 'relative'
    assert date.value.end.days == 3


def test_tentative_date_without_year_remains_incomplete():
    result = run('竞赛通知', '决赛暂定11月20日，具体时间另行通知。')
    assert labels(result, 'date')[0].value.state == 'tentative'
    assert not result.complete
    assert any(g.code == 'date_unresolved' for g in result.gaps)


def test_publication_or_signing_year_does_not_fill_an_ambiguous_deadline():
    result = run('本科生竞赛通知', '报名截止1月3日。\n本科生院\n2028年12月1日')
    date, = labels(result, 'date')
    assert date.value.end.kind == 'month_day'
    assert date.value.state == 'unknown'


def test_other_explicit_date_in_same_main_schedule_can_supply_its_year():
    result = run('微专业选拔通知',
                 '报名时间：2028年4月9日至4月13日。4月14日公示面试安排。')
    dates = labels(result, 'date')
    assert dates[1].value.start.date == '2028-04-14'
    assert any('2028年' in ref.quote for ref in dates[1].evidence)


def test_adjacent_time_only_line_in_same_arrangement_keeps_second_session():
    result = run('2028年本科生面试通知',
                 '一、面试安排\n时间：10月10日8:00-12:30', '13:00-21:00。')
    dates = labels(result, 'date')
    assert len(dates) == 2
    assert [(d.value.start.time, d.value.end.time) for d in dates] == [('08:00', '12:30'), ('13:00', '21:00')]
    assert {d.value.start.date for d in dates} == {'2028-10-10'}
    assert {ref.segment_id for ref in dates[1].evidence} >= {'p0', 'p1'}


def test_time_only_line_never_inherits_from_different_section():
    result = run('2028年本科生面试通知',
                 '一、面试安排\n时间：10月10日8:00-12:30。\n二、咨询方式\n13:00-21:00。')
    assert len(labels(result, 'date')) == 1


def test_system_registration_word_does_not_override_the_student_photo_check():
    result = run('本科生图像采集通知', '拍摄完成约30日后，学生须登录学历电子注册图像校对系统，在线校对图像。')
    date, = labels(result, 'date')
    assert date.code == 'submission'
    assert date.value.start.days == 30


def test_past_participant_registration_count_does_not_own_an_event_end_date():
    result = run('大学生竞赛获奖公示', '大赛已于2028年10月28日落下帷幕，该赛事全校共有139人报名参赛。')
    date, = labels(result, 'date')
    assert date.code == 'event'
    assert date.value.end.date == '2028-10-28'
    assert date.value.state == 'ended'


def test_explicit_objection_window_wins_over_duration_in_same_sentence():
    result = run('2028年大学生竞赛获奖公示', '公示期三天（10月30日—11月1日），如有异议，请反馈。')
    date, = labels(result, 'date')
    assert date.code == 'objection'
    assert date.value.start.date == '2028-10-30'
    assert date.value.end.date == '2028-11-01'


def test_publicity_date_does_not_belong_to_historical_applications():
    result = run('2028年本科辅修选拔结果公示',
                 '经自愿申报和综合选拔，现将名单公示如下。公示期：6月8日—6月10日。')
    date, = labels(result, 'date')
    assert date.code == 'event'


def test_following_tentative_qualification_updates_same_event_with_its_evidence():
    result = run('本科生竞赛通知',
                 '一、赛程安排\n2028年12月19日：答辩。时间暂定为2028年12月19日，具体时间以公告为准。')
    date, = labels(result, 'date')
    assert date.value.state == 'tentative'
    assert any('暂定' in ref.quote for ref in date.evidence)


def test_phone_attachment_title_and_signing_month_are_not_application_deadline():
    result = run('本科生转专业通知',
                 '五、咨询联系方式\n联系电话：0731-88876069\n附件1：《本科生转专业申请表》\n本科生院\n2028年9月')
    assert labels(result, 'date') == []


def test_publicity_window_scope_does_not_absorb_a_roster_from_same_pdf_paragraph():
    result = run('本科辅修选拔结果公示',
                 '经学生自愿申报，现将名单公示如下：\n姓名 学号 主修学院\n甲某 7801250210 文学院\n'
                 '公示期：2028年6月8日至6月10日。')
    date, = labels(result, 'date')
    assert date.code == 'event'
    assert not any(g.college == '文学院' or g.class_name for g in date.scope.audience_groups)


def test_reference_to_unique_stated_submission_deadline_is_not_a_new_unknown_date():
    result = run('本科生竞赛通知', '初审作品提交截止2028年12月15日23点。',
                 '提交方式：在提交截止时间之前以邮件附件发送参赛材料。')
    date, = labels(result, 'date')
    assert date.value.end.date == '2028-12-15'
    assert {ref.segment_id for ref in date.evidence} >= {'p0', 'p1'}


def test_submission_reference_with_packaging_words_keeps_same_object():
    result = run('本科生竞赛通知', '初审作品提交至2028年12月15日23点截止。',
                 '提交方式：将所有参赛材料打包为zip格式，在提交截止时间之前以邮件附件发送。')
    date, = labels(result, 'date')
    assert date.value.end.date == '2028-12-15'
    assert any('打包' in ref.quote for ref in date.evidence)


def test_ambiguous_reference_to_multiple_submission_deadlines_stays_unknown():
    result = run('本科生竞赛通知',
                 '初赛作品提交截止2028年12月15日。决赛作品提交截止2028年12月20日。',
                 '提交方式：在提交截止时间之前以邮件附件发送参赛材料。')
    assert any(d.value.end and d.value.end.kind == 'pending' for d in labels(result, 'date'))


def test_later_announcement_of_problem_or_location_does_not_invent_event_date():
    for text in ('竞赛赛题参考组委会的另行通知。', '考试地点另行通知。', '面试名单另行公布。'):
        assert labels(run('大学生竞赛通知', text), 'date') == []
    date, = labels(run('大学生竞赛通知', '比赛时间另行通知。'), 'date')
    assert date.value.start.reason == 'to_be_announced'


def test_publication_of_interview_list_is_not_the_interview_itself():
    date, = labels(run('2028年本科生选拔通知', '4月14日公布面试名单及面试安排。'), 'date')
    assert date.code == 'event'
    assert date.scope.phase == '名单公布'


def test_ended_event_status_is_retained_despite_historical_participant_count():
    result = run('大学生竞赛获奖公示', '竞赛已于2028年10月28日落下帷幕，全校共有139人报名参赛。')
    assert [label.value for label in labels(result, 'status')] == ['event_ended']
    assert labels(run('大学生竞赛通知', '报名已经结束。'), 'status') == []


def test_result_notice_heading_does_not_move_event_end_into_publicity_phase():
    result = run('大学生竞赛获奖公示', '大学生竞赛获奖公示通知\n大赛已于2028年10月28日落下帷幕。')
    assert all(label.scope.phase is None for label in labels(result, 'date') + labels(result, 'status')
               if label.kind == 'date' or label.value == 'event_ended')
    result = run('大学生竞赛获奖公示', '大学生竞赛获奖公示通知\n决赛已于2028年10月28日落下帷幕。')
    assert all(label.scope.phase == '决赛' for label in labels(result, 'date') + labels(result, 'status')
               if label.kind == 'date' or label.value == 'event_ended')


def test_publishing_college_in_title_does_not_restrict_result_publicity():
    result = run('自动化学院本科辅修选拔结果公示', '经申请和选拔，现将录取名单公示如下。')
    assert all(not label.scope.audience_groups for label in labels(result, 'status'))


def test_chinese_multiple_digit_duration_is_not_truncated():
    for word, days in [('十一', 11), ('二十一', 21), ('三十', 30)]:
        date, = labels(run('本科生结果公示', f'收到通知后{word}天内申请复核。'), 'date')
        assert date.value.end.days == days
        date, = labels(run('本科生结果公示', f'公示期{word}天。'), 'date')
        assert date.value.end.days == days


def test_result_publicity_follows_same_event_year_across_a_roster_reference():
    result = run('大学生竞赛获奖公示',
                 '大学生竞赛已于2028年10月28日落下帷幕。经过评审，获奖名单详见附件1。'
                 '公示期三天（10月30日至11月1日），如有异议请反馈。')
    objection, = [date for date in labels(result, 'date') if date.code == 'objection']
    assert objection.value.start.date == '2028-10-30'


def test_publication_object_can_precede_the_calendar_and_verb():
    date, = labels(run('2028年本科生选拔通知', '入围面试名单及面试具体安排于4月14日在学院网站公示。'), 'date')
    assert date.scope.phase == '名单公布'


def test_dated_ended_verb_keeps_real_final_phase_despite_publicity_heading():
    result = run('大学生竞赛获奖公示', '学生竞赛获奖公示通知\n竞赛决赛已于2028年10月18日结束。')
    ended, = [status for status in labels(result, 'status') if status.value == 'event_ended']
    assert ended.scope.phase == '决赛'
    date, = labels(result, 'date')
    assert date.value.end.date == '2028-10-18'
