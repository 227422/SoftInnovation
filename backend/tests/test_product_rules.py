import pytest
from pydantic import ValidationError


def test_v2_date_endpoint_preserves_month_day_and_rejects_invented_year():
    from campus_backend.classification.product_labels import MonthDayEndpoint, WindowValue

    value = WindowValue(start={'kind': 'month_day', 'month_day': '11-13', 'time': '08:30'})
    assert isinstance(value.start, MonthDayEndpoint)
    assert value.model_dump(mode='json')['end'] is None
    with pytest.raises(ValidationError):
        WindowValue(start={'kind': 'month_day', 'month_day': '11-13', 'date': '2026-11-13'})
    with pytest.raises(ValidationError):
        WindowValue(start={'kind': 'month_day', 'month_day': '02-30'})


def test_v2_necessary_benefit_requires_evidenced_condition():
    from campus_backend.classification.product_labels import ProductBenefitValue

    with pytest.raises(ValidationError):
        ProductBenefitValue(claim_relation='necessary_condition_not_sufficient_guarantee')
    consequence = ProductBenefitValue(
        claim_relation='necessary_condition_not_sufficient_guarantee', condition_status='stated',
        requirement={'operator': 'text', 'items': ('考试合格',)},
    )
    assert consequence.amount is None


def run(title, *texts):
    from campus_backend.classification.product_rules import analyze_product_rules
    from campus_backend.documents.models import DocumentBundle, DocumentSegment

    return analyze_product_rules(DocumentBundle(
        notice_id='demo', content_version='1', title=title, body_status='full',
        source_url='https://example.edu/test', input_fingerprint='a' * 64,
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),)
        + tuple(DocumentSegment(id=f'p{i}', kind='body', text=text, location='html:body')
                for i, text in enumerate(texts)),
    ))


def test_v2_parses_month_day_range_pending_and_relative_dates():
    from campus_backend.classification.product_labels import WindowLabel

    result = run('本科毕业生图像采集通知', '拍摄时间：11月13日08:30至09:00。',
                 '东校区拍摄时间另行通知。', '拍摄结束后约30日请核对照片。')
    labels = [l for l in result.labels if isinstance(l, WindowLabel)]
    assert [(l.code, l.value.start.kind if l.value.start else None,
             l.value.end.kind if l.value.end else None) for l in labels] == [
        ('event', 'month_day', 'month_day'), ('event', 'pending', None),
        ('submission', 'relative', None),
    ]
    assert labels[0].value.end.time == '09:00'
    assert labels[1].scope.audience_groups[0].campus == '东校区'
    assert labels[2].value.start.days == 30


def test_v2_scoped_table_windows_are_distinct_and_cite_headers():
    from campus_backend.classification.product_labels import WindowLabel

    result = run('本科考试通知', '考试安排', '校区\t学院\t班级\t考试时间',
                 '北校区\t文学院\t中文2301、中文2302\t11月13日08:30-09:00',
                 '南校区\t数学院\t数学2301\t11月14日09:00-10:00')
    labels = [l for l in result.labels if isinstance(l, WindowLabel)]
    assert len(labels) == 2
    assert [g.class_name for g in labels[0].scope.audience_groups] == ['中文2301', '中文2302']
    assert labels[0].scope.audience_groups[0].college == '文学院'
    assert labels[1].scope.audience_groups[0].campus == '南校区'
    assert {e.segment_id for e in labels[0].evidence} >= {'p1', 'p2'}


def test_empty_table_cells_and_merged_footer_do_not_create_people_or_fail_notice():
    result = run('本科考试通知', '第一场：2026年11月1日09:00—10:00',
                 '学院\t专业班级\t人数', '文学院\t中文2601\t30\n\t',
                 '备注：请提前到场。\t备注：请提前到场。\t备注：请提前到场。')
    windows = [label for label in result.labels if label.kind == 'date']
    assert len(windows) == 1
    assert [group.class_name for group in windows[0].scope.audience_groups] == ['中文2601']


def test_note_like_class_name_is_still_a_class_when_not_a_footer():
    result = run('本科考试通知', '第一场：2026年11月1日09:00—10:00',
                 '学院\t专业班级\t人数', '文学院\t说明文学2601\t30')
    window, = [label for label in result.labels if label.kind == 'date']
    assert window.scope.audience_groups[0].class_name == '说明文学2601'


def test_v2_distinguishes_required_exam_from_conditional_award():
    from campus_backend.classification.product_labels import ProductBenefitLabel

    result = run('校园竞赛通知', '未通过考试不能取得该课程学分。',
                 '获得一、二、三等奖者颁发荣誉证书。', '评分满分100分，报名费15元，照片用于制作毕业证。')
    labels = [l for l in result.labels if isinstance(l, ProductBenefitLabel)]
    assert [(l.code, l.value.claim_relation) for l in labels] == [
        ('course_credit', 'necessary_condition_not_sufficient_guarantee'),
        ('certificate', 'direct_conditional_award'),
    ]
    assert labels[0].value.requirement.items == ('考试合格',)
    assert labels[1].value.requirement.operator == 'any'
    assert labels[1].value.requirement.items == ('一等奖', '二等奖', '三等奖')


def test_v2_windows_keep_provisional_and_internal_details():
    from campus_backend.classification.product_labels import WindowLabel

    result = run('本科报名通知', '本科生报名截止暂定为2026年11月20日。学院报送截止至2026年11月21日。')
    labels = [l for l in result.labels if isinstance(l, WindowLabel)]
    assert [(l.code, l.value.state, l.presentation, l.value.student_action) for l in labels] == [
        ('registration', 'tentative', 'display', True),
        ('internal_reporting', 'announced', 'detail', False),
    ]


def test_v2_curriculum_credit_requirement_and_offering_are_not_awards():
    from campus_backend.classification.product_labels import ProductBenefitLabel

    result = run('本科生辅修专业报名通知', '辅修专业最低要求20学分。辅修学士学位至少须修满50学分。',
                 '微专业开设5门课程，共计13学分。课程考试及格分为60分。')
    labels = [l for l in result.labels if isinstance(l, ProductBenefitLabel)]
    assert [(l.scope.track, l.value.claim_relation, l.value.amount, l.value.quantity_operator) for l in labels] == [
        ('辅修专业', 'curriculum_requirement', 20, 'gte'),
        ('辅修学士学位', 'curriculum_requirement', 50, 'gte'),
        ('微专业', 'curriculum_offering', 13, 'eq'),
    ]


def test_v2_publicity_without_objection_channel_keeps_publicity_phase():
    from campus_backend.classification.product_labels import WindowLabel

    result = run('拟评优名单公示', '公示期：2025年11月20日至2025年11月24日。', '2026年11月20日')
    label, = [l for l in result.labels if isinstance(l, WindowLabel)]
    assert label.code == 'event'
    assert label.scope.phase == '公示'


def test_v2_benefit_relation_validates_condition_and_quantity():
    from campus_backend.classification.product_labels import ProductBenefitValue

    with pytest.raises(ValidationError):
        ProductBenefitValue(claim_relation='direct_award', condition_status='stated',
                            requirement={'operator': 'text', 'items': ['签到']})
    with pytest.raises(ValidationError):
        ProductBenefitValue(claim_relation='curriculum_offering', quantity_operator='eq')


def test_replaced_deadline_keeps_only_current_value_and_two_sources():
    result = run('竞赛报名通知', '本科生报名截止原为2026年11月20日，现延长至2026年11月25日。')
    label, = [l for l in result.labels if l.kind == 'date']
    assert label.value.end.date == '2026-11-25'
    assert label.value.state == 'rescheduled'
    assert len(label.evidence) == 2


def test_same_scope_conflicting_dates_keep_both_windows_unconfirmed():
    result = run('竞赛报名通知', '本科生报名截止至2026年11月20日。', '本科生报名截止至2026年11月21日。')
    labels = [l for l in result.labels if l.kind == 'date']
    assert [l.value.state for l in labels] == ['conflicting', 'conflicting']
    assert not result.complete


def test_table_rows_allow_missing_trailing_counts_and_weekday_tokens():
    result = run('本科毕业生图像采集通知', '校区\t院系\t班级\t人数\t采集时间段\t合计',
                 '北校区\t文学院\t中文2301\t30\t11月13日周五08：30-09：00\t60',
                 '北校区\t文学院\t中文2302\t30\t11月13日周五08：30-09：00')
    label, = [l for l in result.labels if l.kind == 'date']
    assert label.value.end.time == '09:00'
    assert [g.class_name for g in label.scope.audience_groups] == ['中文2301', '中文2302']


def test_excluded_notice_keeps_dated_details_without_display_labels():
    result = run('行政人员招聘公告', '报名截止至2026年11月20日。')
    assert result.category == 'excluded'
    assert any(l.kind == 'date' for l in result.labels)
    assert all(l.presentation == 'detail' for l in result.labels)


def test_separately_headed_table_slots_share_time_but_not_class_scope():
    result = run('本科考试通知', '第一场：2026年11月1日（下午1:30—2:20）',
                 '学院\t专业班级\t人数', '文学院\t中文2301\t30',
                 '第二场：2026年11月1日（下午2:30—3:20）',
                 '学院\t专业班级\t人数', '数学院\t数学2301\t30')
    labels = [l for l in result.labels if l.kind == 'date']
    assert [(l.value.start.time, l.value.end.time, l.scope.audience_groups[0].class_name)
            for l in labels] == [('13:30', '14:20', '中文2301'), ('14:30', '15:20', '数学2301')]


def test_pdf_line_wrap_does_not_hide_required_course_credit_condition():
    result = run('在线考试通知', '考试未通过的学生，不能取得该门课\n程学分。')
    label, = [l for l in result.labels if l.kind == 'benefit']
    assert label.value.claim_relation == 'necessary_condition_not_sufficient_guarantee'
    assert label.evidence[0].quote == '考试未通过的学生，不能取得该门课\n程学分'


def test_structured_exam_heading_covers_following_date_but_not_footer():
    result = run('本科在线考试通知', '1.考试时间\n2026年11月8日(星期日)上午\n2.考试地点\n东校区\n2026年10月20日')
    label, = [l for l in result.labels if l.kind == 'date']
    assert label.value.start.date == '2026-11-08'
    assert len(label.evidence) == 2


def test_statement_of_prizes_and_certificate_has_alternative_award_requirements():
    result = run('校内竞赛通知', '竞赛设一等奖、二等奖、三等奖若干，颁发荣誉证书。')
    label, = [l for l in result.labels if l.kind == 'benefit']
    assert label.value.requirement.items == ('一等奖', '二等奖', '三等奖')


def test_relative_photo_review_and_past_participation_do_not_change_event_purpose():
    result = run('图像采集通知', '拍摄完成约 30 日后，学生本人须登录系统\n在线校对图像。',
                 '比赛已于2026年10月28日落下帷幕，该赛事共有139人报名参赛。')
    labels = [l for l in result.labels if l.kind == 'date']
    assert [(l.code, l.value.state) for l in labels] == [('submission', 'announced'), ('event', 'ended')]


@pytest.mark.parametrize('text', [
    '公示期：2026年11月8日至2025年11月10日。',
    '考试时间：2026年11月8日09:00至08:00。',
])
def test_reversed_absolute_window_retains_endpoints_but_marks_conflict(text):
    result = run('本科考试安排公示', text)
    label, = [l for l in result.labels if l.kind == 'date']
    assert label.value.start is not None and label.value.end is not None
    assert label.value.state == 'conflicting'
    assert 'date_conflict' in {gap.code for gap in result.gaps}


def test_window_schema_cannot_describe_reversed_absolute_endpoints_as_announced():
    from campus_backend.classification.product_labels import WindowValue
    with pytest.raises(ValidationError, match='conflicting'):
        WindowValue(start={'kind':'absolute','date':'2026-11-08'},
                    end={'kind':'absolute','date':'2025-11-10'})


def test_missing_end_year_across_new_year_is_not_guessed_or_reversed():
    result=run('考试通知', '考试时间：2026年12月31日至1月1日。')
    label, = [l for l in result.labels if l.kind == 'date']
    assert label.value.start.date == '2026-12-31'
    assert label.value.end.kind == 'month_day'
    assert label.value.end.month_day == '01-01'
    assert label.value.state != 'conflicting'


def test_separate_actions_in_one_sentence_bind_to_their_own_deadline():
    result = run('比赛报名通知', '报名截止至2026年11月20日，材料提交截止至2026年11月25日。')
    assert [(l.code, l.value.end.date) for l in result.labels if l.kind == 'date'] == [
        ('registration', '2026-11-20'), ('submission', '2026-11-25'),
    ]


def test_pending_second_slot_never_inherits_first_slot_time():
    result = run('本科考试通知', '第一场：2026年11月1日（下午1:30—2:20）',
                 '学院\t专业班级\t人数', '文学院\t中文2301\t30',
                 '第二场：时间另行通知', '学院\t专业班级\t人数', '数学院\t数学2301\t30')
    windows = [l for l in result.labels if l.kind == 'date']
    assert [(l.scope.phase, l.value.start.kind, l.scope.audience_groups[0].class_name)
            for l in windows] == [('第一场', 'absolute', '中文2301'), ('第二场', 'pending', '数学2301')]


@pytest.mark.parametrize(('sentence', 'operator', 'items'), [
    ('并非获得一等奖者颁发荣誉证书。', None, ()),
    ('获得一等奖及二等奖者颁发荣誉证书。', 'all', ('一等奖', '二等奖')),
    ('获得一等奖者颁发荣誉证书，但须审核通过。', 'all', ('一等奖', '审核通过')),
])
def test_certificate_conditions_keep_negation_and_conjunction(sentence, operator, items):
    result = run('竞赛报名通知', sentence)
    labels = [l for l in result.labels if l.kind == 'benefit']
    if operator is None:
        assert not labels
    else:
        label, = labels
        assert (label.value.requirement.operator, label.value.requirement.items) == (operator, items)
