"""Admission predicates retain their exceptions and their actual source scope."""
from hashlib import sha256

import pytest

from campus_backend.documents.models import DocumentAsset, DocumentBundle, DocumentSegment
from campus_backend.classification.product_rules import analyze_product_rules


ENTRY = '所有参考学生必须携带本人校园卡（校园卡遗失或头像不清晰的用身份证）入场，否则禁止参考'


def exam_document(pages, *, page_numbers=None, page_assets=None, title='本科生考试通知'):
    page_numbers = page_numbers or list(range(1, len(pages) + 1))
    page_assets = page_assets or ['mainpdf'] * len(pages)
    hashes = {name: sha256(name.encode()).hexdigest() for name in (*page_assets, 'schedule')}
    segments = [DocumentSegment(id='title', kind='title', text=title, location='title')]
    for index, (text, page, asset) in enumerate(zip(pages, page_numbers, page_assets, strict=True)):
        if index == 0:
            text = ('一、考试安排\n考试安排详见附件。考试未通过的学生，不能取得该门课程学分。\n'
                    '二、考试要求\n' + text)
        segments.append(DocumentSegment(id=f'pdf-{index}', kind='attachment', text=text,
            location=f'page:{page}', page=page, asset_id=asset, asset_hash=hashes[asset]))
    for index, text in enumerate(('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
                                  '学院\t专业班级\t人数', '文学院\t中文2601\t30')):
        segments.append(DocumentSegment(id=f'schedule-{index}', kind='attachment', text=text,
            location=f'sheet:安排/row:{index + 1}', asset_id='schedule', asset_hash=hashes['schedule']))
    return DocumentBundle(notice_id='test', content_version='1', title=title,
        source_url='https://example.edu/notice', body_status='full', segments=segments,
        assets=[DocumentAsset(asset_id=name, asset_hash=value) for name, value in hashes.items()],
        primary_asset_ids=tuple(dict.fromkeys(page_assets)), input_fingerprint='a' * 64)


def result(value):
    outcome = analyze_product_rules(value)
    originals = {segment.id: segment.text for segment in value.segments}
    for item in (*outcome.labels, *outcome.gaps):
        for evidence in item.evidence:
            assert evidence.quote in originals[evidence.segment_id]
    return outcome


def exam_windows(outcome):
    return [label for label in outcome.labels if label.kind == 'date' and label.code == 'event']


@pytest.mark.parametrize('pages', [
    [ENTRY + '。'],
    ['所有参考学生必须携带本人校园卡（校园卡遗失或头像', '不清晰的用身份证）入场，否则禁止参考。'],
])
def test_exam_entry_retains_whole_conditional_predicate_in_single_and_split_pdf(pages):
    value = exam_document(pages)
    outcome = result(value)
    window, = exam_windows(outcome)
    assert window.value.requirement is not None
    assert window.value.requirement.operator == 'text'
    assert window.value.requirement.items == (
        '所有参考学生必须携带本人校园卡(校园卡遗失或头像不清晰的用身份证)入场,否则禁止参考',)
    assert {f'pdf-{i}' for i in range(len(pages))} <= {ref.segment_id for ref in window.evidence}
    credit, = [label for label in outcome.labels if label.kind == 'benefit']
    assert credit.value.requirement.items == ('考试合格',)


@pytest.mark.parametrize('pages,page_numbers,page_assets', [
    (['考生必须携带校园卡（遗失时', '可用身份证）入场。'], [1, 2], ['one', 'two']),
    (['考生必须携带校园卡（遗失时', '可用身份证）入场。'], [1, 3], ['one', 'one']),
    (['考生必须携带校园卡（遗失时', '三、其他事项\n可用身份证）入场。'], [1, 2], ['one', 'one']),
    (['考生必须携带校园卡（遗失时', '1.可用身份证）入场。'], [1, 2], ['one', 'one']),
    (['考生必须携带校园卡（遗失时。', '可用身份证）入场。'], [1, 2], ['one', 'one']),
])
def test_unproven_page_continuation_does_not_create_an_admission_rule(pages, page_numbers, page_assets):
    outcome = result(exam_document(pages, page_numbers=page_numbers, page_assets=page_assets))
    window, = exam_windows(outcome)
    assert window.value.requirement is None
    assert any(gap.code == 'coverage_unconfirmed' and '入场' in gap.detail for gap in outcome.gaps)


@pytest.mark.parametrize('heading', ['研究生考试', '教师考试', '培训考核'])
def test_other_subject_section_cannot_supply_undergraduate_entry_rule(heading):
    outcome = result(exam_document(['三、' + heading + '\n' + ENTRY + '。']))
    window, = exam_windows(outcome)
    assert window.value.requirement is None


@pytest.mark.parametrize('text', ['考生无需携带校园卡入场。', '考生无须携带校园卡入场。',
                                 '工作人员必须携带校园卡入场。', '示例：考生必须携带校园卡入场。'])
def test_waiver_staff_or_example_is_not_rewritten_as_student_mandatory_rule(text):
    window, = exam_windows(result(exam_document([text])))
    assert window.value.requirement is None


def test_other_attachment_entry_rule_never_flows_into_main_exam():
    value = exam_document(['请按时参加考试。'])
    asset = DocumentAsset(asset_id='unrelated', asset_hash='b' * 64)
    segment = DocumentSegment(id='other', kind='attachment', text=ENTRY + '。',
        asset_id=asset.asset_id, asset_hash=asset.asset_hash, location='page:1', page=1)
    value = value.model_copy(update={'assets': (*value.assets, asset), 'segments': (*value.segments, segment)})
    window, = exam_windows(result(value))
    assert window.value.requirement is None


def test_page_continuation_is_bounded_and_does_not_swallow_three_pages():
    value = exam_document(['考生必须携带校园卡（遗失时', '应先办理证明并', '用身份证）入场。'])
    window, = exam_windows(result(value))
    assert window.value.requirement is None


@pytest.mark.parametrize('text', ['考生须携带本人准考证或有效身份证进入考场', '须出示本人护照入场'])
def test_credential_rule_is_generic_and_does_not_split_an_explicit_or(text):
    window, = exam_windows(result(exam_document([text + '。'])))
    assert window.value.requirement.operator == 'text'
    assert window.value.requirement.items == (text,)


def test_oversized_continuation_keeps_gap_instead_of_swallowing_the_page():
    value = exam_document(['考生必须携带校园卡（' + '相关说明' * 400, '遗失时可用身份证）入场。'])
    outcome = result(value)
    window, = exam_windows(outcome)
    assert window.value.requirement is None
    assert any('入场' in gap.detail for gap in outcome.gaps)


def test_new_admission_condition_keeps_an_existing_or_as_one_conjunct():
    from campus_backend.classification.product_context import build_context
    from campus_backend.classification.product_labels import Requirement
    from campus_backend.classification.product_requirements import apply_requirements, collect_requirements

    value = exam_document([ENTRY + '。'])
    context = build_context(value)
    window, = exam_windows(result(value))
    window = window.model_copy(update={'value': window.value.model_copy(update={
        'requirement': Requirement(operator='any', items=('完成首次考试', '符合补考条件'))})})
    labels, _ = apply_requirements([window], collect_requirements(context), context)
    assert labels[0].value.requirement.operator == 'all'
    assert labels[0].value.requirement.items[0] == '((完成首次考试)或(符合补考条件))'
    assert len(labels[0].value.requirement.items) == 2


@pytest.mark.parametrize('following', [
    '校园卡遗失或头像不清晰的用身份证入场，否则禁止参考',
    '但本科生无需携带校园卡',
])
def test_separately_stated_exception_does_not_leave_an_unqualified_card_rule(following):
    outcome = result(exam_document(['考生必须携带校园卡入场；' + following + '。']))
    window, = exam_windows(outcome)
    assert window.value.requirement is None
    assert any('入场' in gap.detail for gap in outcome.gaps)


@pytest.mark.parametrize('section', ['1.最后一场', '1.补考要求', '1.初试要求', '1.复试要求', '三、补考要求'])
def test_stage_specific_credentials_are_not_promoted_to_all_exam_sessions(section):
    outcome = result(exam_document([section + '\n考生必须携带准考证入场。']))
    window, = exam_windows(outcome)
    assert window.scope.phase == '第一场'
    assert window.value.requirement is None
    assert any(gap.code == 'coverage_unconfirmed' and '阶段' in gap.detail for gap in outcome.gaps)


def test_conjoining_admission_keeps_each_complex_existing_alternative_atomic():
    from campus_backend.classification.product_context import build_context
    from campus_backend.classification.product_labels import Requirement
    from campus_backend.classification.product_requirements import apply_requirements, collect_requirements

    value = exam_document([ENTRY + '。'])
    context = build_context(value)
    window, = exam_windows(result(value))
    window = window.model_copy(update={'value': window.value.model_copy(update={
        'requirement': Requirement(operator='any', items=(
            '完成培训且本人确认无误', '属于补考或重修人员，否则需先取得批准'))})})
    labels, _ = apply_requirements([window], collect_requirements(context), context)
    assert labels[0].value.requirement.operator == 'all'
    assert labels[0].value.requirement.items[0] == '((完成培训且本人确认无误)或(属于补考或重修人员，否则需先取得批准))'


@pytest.mark.parametrize('text', [
    '考生必须携带准考证在最后一场入场。',
    '考生必须携带准考证入场（仅限补考考生）。',
])
def test_inline_local_population_or_session_never_becomes_common_credential_rule(text):
    outcome = result(exam_document([text]))
    window, = exam_windows(outcome)
    assert window.value.requirement is None
    assert any(gap.code == 'coverage_unconfirmed' and '范围' in gap.detail for gap in outcome.gaps)


@pytest.mark.parametrize('exception', [
    '遗失的可凭临时证明入场', '不清晰的可出示临时证明入场',
])
def test_adjacent_elliptical_replacement_does_not_require_repeated_credential_name(exception):
    outcome = result(exam_document(['考生必须携带校园卡入场；' + exception + '。']))
    window, = exam_windows(outcome)
    assert window.value.requirement is None
    gap, = [gap for gap in outcome.gaps if '后续例外' in gap.detail]
    assert any(exception in ref.quote for ref in gap.evidence)


def test_training_window_in_same_exam_section_does_not_inherit_exam_admission():
    outcome = result(exam_document(['考前培训于2026年11月2日09:00—10:00举行。考生必须携带校园卡进入考场。']))
    training, exam = exam_windows(outcome)
    assert training.value.start.date == '2026-11-02'
    assert training.value.requirement is None
    assert exam.value.requirement.items == ('考生必须携带校园卡进入考场',)
    assert any('考试动作' in gap.detail for gap in outcome.gaps)


def test_explicit_main_exam_window_remains_eligible_for_admission_condition():
    outcome = result(exam_document(['考试于2026年11月2日09:00—10:00举行。考生必须携带校园卡进入考场。']))
    main, schedule = exam_windows(outcome)
    assert main.value.requirement.items == schedule.value.requirement.items == ('考生必须携带校园卡进入考场',)


@pytest.mark.parametrize('heading', ['三、考试时间', '1.考试时间'])
def test_numbered_exam_time_heading_binds_date_only_window_to_admission(heading):
    outcome = result(exam_document([ENTRY + '。\n' + heading + '\n2026年11月2日09:00—10:00。']))
    main, schedule = exam_windows(outcome)
    assert main.value.start.date == '2026-11-02'
    assert main.value.requirement is not None
    assert main.value.requirement.items == schedule.value.requirement.items == (
        '所有参考学生必须携带本人校园卡(校园卡遗失或头像不清晰的用身份证)入场,否则禁止参考',)
    assert not any('考试动作' in gap.detail for gap in outcome.gaps)
