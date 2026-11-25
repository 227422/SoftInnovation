"""Layout changes must not alter the meaning of a public time window."""
import pytest
from campus_backend.classification.rule_labels import RuleEvidence
from campus_backend.classification.rule_windows import prose_windows, table_slot


@pytest.mark.parametrize('text',[
    '报名截止时间为2026 年 12 月 15 日 23 点。',
    '报名截止时间为２０２６年１２月１５日２３时。',
    '报名截止时间为2026年12月15日 23 ： 00。',
])
def test_spacing_fullwidth_and_hour_forms_keep_deadline_and_original_evidence(text):
    ref=RuleEvidence(segment_id='body',quote=text)
    window,=prose_windows(text,ref,'本科报名通知')
    assert window.value.end.date=='2026-12-15'
    assert window.value.end.time=='23:00'
    assert window.evidence==(ref,)


def test_single_scene_time_line_establishes_slot_without_inventing_scene_number():
    text='2026年11月8日 9：10 — 10：00'
    slot=table_slot(text,RuleEvidence(segment_id='table:3',quote=text),'本科生在线考试安排表',allow_unheaded=True)
    assert slot is not None
    assert slot.scope.phase is None
    assert slot.value.start.time=='09:10'
    assert slot.value.end.time=='10:00'


def test_same_window_can_share_explicit_month_with_day_only_end():
    text='公示期为2026年10月21日至27日。'
    window,=prose_windows(text,RuleEvidence(segment_id='body',quote=text),'本科公示')
    assert window.value.start.date=='2026-10-21'
    assert window.value.end.date=='2026-10-27'


def test_table_birth_date_and_plain_footer_never_become_exam_slots():
    for text in ('出生日期：2026年11月8日', '2026年11月8日'):
        assert table_slot(text,RuleEvidence(segment_id='table',quote=text),'本科考试安排表',allow_unheaded=True) is None


def test_explicit_horizontal_merge_can_supply_one_time_heading_without_losing_raw_quote():
    text='2027年5月3日（上午9:10—10:00）\t2027年5月3日（上午9:10—10:00）'
    ref=RuleEvidence(segment_id='table:3',quote=text)
    slot=table_slot(text,ref,'本科生考试安排表',allow_unheaded=True,merged_ranges=('A3:B3',))
    assert slot.value.start.time=='09:10'
    assert slot.value.end.time=='10:00'
    assert slot.evidence==(ref,)
    assert table_slot(text,ref,'本科生考试安排表',allow_unheaded=True) is None


@pytest.mark.parametrize('text', [
    '2027年5月3日09:10—10:00\t另一活动',
    '出生日期\t2027年5月3日09:10—10:00',
])
def test_merge_provenance_does_not_make_every_row_a_scene(text):
    assert table_slot(text,RuleEvidence(segment_id='table',quote=text),'本科考试安排表',
                      allow_unheaded=True,merged_ranges=('A3:B3',)) is None


def test_person_roster_header_keeps_its_college_and_class_time_without_personal_labels():
    from test_product_context import document, run
    time='2027年5月3日（上午9:10—10:00）'
    source=document('本科生实验室安全考试通知','具体考试安排详见附件。',
        [('本科生实验室安全考试安排表','\t'.join([time]*5),
          '机房\t学号\t姓名\t上课院系\t班级','401\t001\t合成学生\t文学院\t中文2601')])
    segments=list(source.segments)
    segments[3]=segments[3].model_copy(update={'table_merges':('A2:E2',)})
    result=run(source.model_copy(update={'segments':tuple(segments)}))
    window,=[label for label in result.labels if label.kind=='date']
    assert window.value.start.time=='09:10'
    assert window.value.end.time=='10:00'
    assert window.scope.audience_groups[0].college=='文学院'
    assert window.scope.audience_groups[0].class_name=='中文2601'
    assert all('合成学生' not in (group.audience or '') for group in window.scope.audience_groups)


def test_vertical_merge_empty_separator_is_not_a_new_scene_heading():
    from test_product_context import document,run
    time='2027年5月3日09:10—10:00'
    source=document('本科考试安排','具体考试安排详见附件。',
        [('本科考试安排表','时间\t学院\t班级',f'{time}\t文学院\t中文2601',
          f'{time}\t\t',f'{time}\t数学院\t数学2601')])
    segments=list(source.segments)
    for index in (4,5,6):
        segments[index]=segments[index].model_copy(update={'table_merges':('A3:A5',)})
    result=run(source.model_copy(update={'segments':tuple(segments)}))
    groups=[g.class_name for l in result.labels if l.kind=='date' for g in l.scope.audience_groups]
    assert groups==['中文2601','数学2601']
