"""Context may resolve dates only when its year, action and audience fit."""

import pytest

from test_simple_tags import labels, run
from test_simple_attachment_binding import document as numbered_document
from test_simple_attachment_binding import unresolved
from campus_backend.classification.product_labels import AudienceGroup, ProductScope
from campus_backend.classification.simple_context import primary_view
from campus_backend.classification.simple_rules import _resolve_schedule_pointers


def test_year_in_quoted_prior_regulation_is_not_the_current_notice_year():
    result = run('关于依据《2025年竞赛办法》开展本科生选拔的通知', '报名截止1月3日。')
    date, = labels(result, 'date')
    assert date.value.end.kind == 'month_day'
    assert date.value.end.month_day == '01-03'
    assert date.value.state == 'unknown'


def test_current_notice_year_outside_a_quoted_prior_rule_still_resolves_date():
    result = run('关于依据《2025年竞赛办法》开展2028年本科生竞赛的通知', '报名截止1月3日。')
    date, = labels(result, 'date')
    assert date.value.end.kind == 'absolute'
    assert date.value.end.date == '2028-01-03'
    assert date.value.state == 'announced'


def test_later_phase_month_day_does_not_inherit_a_reversed_year_from_earlier_phase():
    result = run('本科生竞赛通知', '初赛报名截止2028年12月20日。', '决赛报名截止1月10日。')
    initial, final = labels(result, 'date')
    assert initial.value.end.date == '2028-12-20'
    assert final.value.end.kind == 'month_day'
    assert final.value.end.month_day == '01-10'
    assert final.value.state == 'unknown'


def test_one_college_schedule_does_not_supply_another_colleges_missing_year():
    result = run('本科生考试通知', '工学院考试时间：2028年12月20日。', '文学院考试时间：1月10日。')
    first, second = labels(result, 'date')
    assert first.value.start.date == '2028-12-20'
    assert second.value.start.kind == 'month_day'
    assert second.value.start.month_day == '01-10'
    assert second.value.state == 'unknown'


def test_same_phase_current_schedule_can_supply_a_forward_date_year():
    result = run('本科生竞赛通知', '初赛报名截止2028年5月20日。', '初赛材料提交截止5月25日。')
    registration, submission = labels(result, 'date')
    assert registration.value.end.date == '2028-05-20'
    assert submission.value.end.date == '2028-05-25'
    assert submission.value.state == 'announced'


def test_generic_deadline_reference_does_not_borrow_another_action_deadline():
    result = run('本科生竞赛通知',
                 '一、参赛论文\n参赛论文提交截止2028年6月1日。\n'
                 '二、困难补助\n补助证明请在规定截止时间前提交。')
    dates = labels(result, 'date')
    assert len(dates) == 2
    known, = [date for date in dates if date.value.end and date.value.end.kind == 'absolute']
    pending, = [date for date in dates if any(
        point and point.kind == 'pending' for point in (date.value.start, date.value.end)
    )]
    assert known.value.end.date == '2028-06-01'
    assert pending.value.state == 'unknown'
    assert not any('补助' in ref.quote for ref in known.evidence)


def test_explicit_reference_with_same_submission_object_can_reuse_deadline():
    result = run('本科生竞赛通知', '初审作品提交截止2028年12月15日23点。',
                 '初审作品提交方式：在上述截止时间前以邮件发送初审作品。')
    date, = labels(result, 'date')
    assert date.value.end.date == '2028-12-15'
    assert date.value.end.time == '23:00'
    assert any('上述截止时间' in ref.quote for ref in date.evidence)


def test_numbered_attachment_identity_does_not_override_explicit_population_conflict():
    bundle, dates, _ = numbered_document()
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience='研究生'),)),
    })
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert len(unresolved(resolved)) == 1
    graduate, = [date for date in resolved if date.value.start.kind == 'absolute']
    assert not any('详见附件3' in ref.quote for ref in graduate.evidence)


@pytest.mark.parametrize('audience', [None, '2028级本科生'])
def test_numbered_attachment_can_bind_finer_class_scope_without_an_explicit_conflict(audience):
    bundle, dates, _ = numbered_document()
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(
            audience=audience, college='工学院', class_name='2801班',
        ),)),
    })
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert not unresolved(resolved)
    assert len(resolved) == 1
    assert resolved[0].scope == dates[1].scope
    assert any('详见附件3' in ref.quote for ref in resolved[0].evidence)


@pytest.mark.parametrize('historical', ['往届', '上届', '去年'])
def test_historical_event_year_does_not_resolve_the_current_round_deadline(historical):
    result = run('本科生竞赛通知',
                 f'{historical}比赛于2025年5月1日结束。本届报名截止6月1日。')
    date, = [label for label in labels(result, 'date') if label.code == 'registration']
    assert date.value.end.kind == 'month_day'
    assert date.value.end.month_day == '06-01'
    assert date.value.state == 'unknown'
    assert not any(historical in ref.quote for ref in date.evidence)


@pytest.mark.parametrize('next_year', ['下一年度', '下一年', '次年'])
def test_adjacent_phase_does_not_erase_an_explicit_next_year_relationship(next_year):
    result = run('本科生竞赛通知',
                 f'初赛报名截止2028年4月13日。{next_year}决赛在4月14日举行。')
    date, = [label for label in labels(result, 'date') if label.code == 'event']
    assert date.value.start.kind == 'month_day'
    assert date.value.start.month_day == '04-14'
    assert date.value.state == 'unknown'
    assert any(next_year in ref.quote for ref in date.evidence)


@pytest.mark.parametrize(('first_object', 'second_object'), [('摄影', '作文'), ('绘画', '书法')])
def test_different_competition_work_objects_do_not_share_a_deadline(first_object, second_object):
    result = run('本科生竞赛通知',
                 f'一、{first_object}竞赛\n{first_object}作品提交截止2028年6月1日。\n'
                 f'二、{second_object}比赛\n{second_object}作品请在规定截止时间前提交。')
    dates = labels(result, 'date')
    assert len(dates) == 2
    known, = [date for date in dates if date.value.end and date.value.end.kind == 'absolute']
    pending, = [date for date in dates if any(
        point and point.kind == 'pending' for point in (date.value.start, date.value.end)
    )]
    assert known.value.end.date == '2028-06-01'
    assert pending.value.state == 'unknown'
    assert not any(second_object in ref.quote for ref in known.evidence)


def test_repeated_specific_work_object_can_reuse_its_own_deadline():
    result = run('本科生竞赛通知', '摄影作品提交截止2028年6月1日。',
                 '摄影作品请在上述截止时间前提交。')
    date, = labels(result, 'date')
    assert date.value.end.date == '2028-06-01'
    assert any('上述截止时间' in ref.quote for ref in date.evidence)


@pytest.mark.parametrize(('pointer_audience', 'schedule_audience'), [
    ('硕士研究生', '博士研究生'),
    ('博士研究生', '硕士研究生'),
    ('2028届本科毕业生', '非2028届本科毕业生'),
    ('2028级本科生', '非2028级本科生'),
])
def test_numbered_pointer_rejects_specific_degree_or_negated_cohort_conflict(
    pointer_audience, schedule_audience,
):
    bundle, dates, _ = numbered_document()
    dates[0] = dates[0].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience=pointer_audience),)),
    })
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience=schedule_audience),)),
    })
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert len(unresolved(resolved)) == 1
    scheduled, = [date for date in resolved if date.value.start.kind == 'absolute']
    assert not any('详见附件3' in ref.quote for ref in scheduled.evidence)


@pytest.mark.parametrize('schedule_audience', ['硕士研究生', '博士研究生'])
def test_general_graduate_pointer_allows_a_more_specific_degree_scope(schedule_audience):
    bundle, dates, _ = numbered_document()
    dates[0] = dates[0].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience='研究生'),)),
    })
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience=schedule_audience),)),
    })
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert not unresolved(resolved)
    assert len(resolved) == 1
    assert resolved[0].scope.audience_groups[0].audience == schedule_audience


def test_one_scheduled_population_does_not_resolve_a_two_population_pointer():
    bundle, dates, _ = numbered_document()
    dates[0] = dates[0].model_copy(update={
        'scope': ProductScope(audience_groups=(
            AudienceGroup(audience='本科生'), AudienceGroup(audience='研究生'),
        )),
    })
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience='本科生'),)),
    })
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert len(unresolved(resolved)) == 1


def test_separate_schedule_rows_may_jointly_cover_all_pointer_populations():
    from campus_backend.documents.models import DocumentSegment
    from campus_backend.classification.rule_labels import RuleEvidence
    from campus_backend.classification.product_labels import AbsoluteEndpoint
    from campus_backend.classification.simple_labels import SimpleDateLabel, SimpleDateValue

    bundle, dates, _ = numbered_document()
    first_row = next(segment for segment in bundle.segments
                     if segment.asset_id == 'schedule' and segment.location.endswith('row:2'))
    other_row = DocumentSegment(
        id='graduate-row', kind='attachment', asset_id=first_row.asset_id,
        asset_hash=first_row.asset_hash, location='sheet:日程/row:3',
        text='研究生考试时间：2028年11月8日10:00—11:00',
    )
    bundle = bundle.model_copy(update={'segments': (*bundle.segments, other_row)})
    dates[0] = dates[0].model_copy(update={
        'scope': ProductScope(audience_groups=(
            AudienceGroup(audience='本科生'), AudienceGroup(audience='研究生'),
        )),
    })
    dates[1] = dates[1].model_copy(update={
        'scope': ProductScope(audience_groups=(AudienceGroup(audience='本科生'),)),
    })
    dates.append(SimpleDateLabel(
        code='event', scope=ProductScope(audience_groups=(AudienceGroup(audience='研究生'),)),
        evidence=(RuleEvidence(segment_id=other_row.id, quote=other_row.text),),
        value=SimpleDateValue(
            start=AbsoluteEndpoint(date='2028-11-08', time='10:00'),
            end=AbsoluteEndpoint(date='2028-11-08', time='11:00'),
        ),
    ))
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert not unresolved(resolved)
    assert len(resolved) == 2
    assert {date.scope.audience_groups[0].audience for date in resolved} == {'本科生', '研究生'}
    assert all(any('详见附件3' in ref.quote for ref in date.evidence) for date in resolved)
