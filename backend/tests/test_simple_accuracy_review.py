"""Independent v3 review reproducers. Expected outcomes do not use corpus answers."""

from campus_backend.classification.product_labels import endpoints_reversed
from campus_backend.classification.simple_labels import SimpleRuleResult
from campus_backend.documents.models import DocumentAsset
from test_simple_tags import run, labels


def test_year_resolution_never_emits_an_announced_reversed_cross_year_range():
    result = run('2028年本科生竞赛报名通知', '报名时间：2028年12月28日至1月3日。')
    window, = labels(result, 'date')
    assert not endpoints_reversed(window.value.start, window.value.end) or window.value.state == 'conflicting'
    SimpleRuleResult.model_validate_json(result.model_dump_json())


def test_supplement_year_does_not_become_primary_via_shared_audience_evidence():
    asset = DocumentAsset(asset_id='supplement', asset_hash='b' * 64)
    result = run(
        '本科生竞赛报名通知', '面向全校本科生。', '报名截止11月20日。',
        attachments=((asset, ('实践活动于2025年3月1日举行。',)),),
    )
    window = next(item for item in labels(result, 'date') if item.code == 'registration')
    assert window.value.end.kind == 'month_day'
    assert window.value.end.month_day == '11-20'


def test_another_named_project_cannot_supply_an_unstated_calendar_year():
    result = run(
        '本科生项目报名通知',
        '星光计划报名截止2028年11月20日。飞跃计划报名截止11月25日。',
    )
    second = next(item for item in labels(result, 'date') if item.scope.action == '飞跃计划')
    assert second.value.end.kind == 'month_day'


def test_receipt_relative_objection_does_not_get_reanchored_to_publicity_start():
    result = run('本科生竞赛结果公示', '如有异议，请于收到邮件后三天内反馈。')
    window, = labels(result, 'date')
    assert window.value.end.kind == 'relative'
    assert window.value.end.anchor == '收到邮件'
    assert window.value.end.days == 3


def test_explicit_publicity_duration_carries_to_adjacent_objection_instruction():
    result = run('本科生培养班录取名单公示', '现将拟录取名单公示，公示期3天。如有异议，请实名反馈。')
    objections = [item for item in labels(result, 'date') if item.code == 'objection']
    assert len(objections) == 1
    assert objections[0].value.end.kind == 'relative'
    assert objections[0].value.end.days == 3


def test_unit_reporting_does_not_become_student_reporting_when_material_mentions_students():
    result = run('本科生竞赛通知', '学院请于2028年11月20日前汇总学生材料并报送教务处。')
    assert labels(result, 'date') == []


def test_explicit_student_synonym_reporting_is_kept():
    result = run('本科生竞赛通知', '请同学们于2028年11月20日前报送材料。')
    window, = labels(result, 'date')
    assert window.code == 'submission'
    assert window.value.end.date == '2028-11-20'


def test_enterprise_registration_requirement_is_not_contest_registration_date():
    result = run('本科生创业大赛通知', '参赛企业须于2026年1月1日前完成注册。')
    assert labels(result, 'date') == []
