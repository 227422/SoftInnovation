import importlib

import pytest

from campus_backend.documents.models import DocumentAsset, DocumentBundle, DocumentSegment


def analyze(title, *paragraphs, status='full', assets=()):
    document = DocumentBundle(
        notice_id='n1', content_version='v1', title=title,
        source_url='https://example.edu/notice', body_status=status, assets=assets,
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),)
        + tuple(DocumentSegment(id=f'p{i}', kind='body', text=text, location=f'p{i}')
                for i, text in enumerate(paragraphs)),
        input_fingerprint='1' * 64,
    )
    before = document.model_dump(mode='json')
    engine = importlib.import_module('campus_backend.classification.rule_baseline')
    result = engine.analyze_rules(document)
    assert result == engine.analyze_rules(document)
    assert document.model_dump(mode='json') == before
    assert result.input_fingerprint == document.input_fingerprint
    for label in result.labels:
        for ref in label.evidence:
            assert ref.quote in next(seg.text for seg in document.segments if seg.id == ref.segment_id)
    return result.model_dump(mode='json')


def test_retains_distinct_tracks_audiences_and_quantities():
    result = analyze(
        '创新大赛报名通知',
        '本科生A赛道报名截止至2026年11月20日17:30；研究生B赛道报名截止至2026年11月21日。',
        '本科生A赛道可获志愿时长2小时；研究生B赛道可获志愿时长三小时。',
    )
    dates = [label for label in result['labels'] if label['kind'] == 'date']
    assert [(label['scope']['track'], label['scope']['audience'], label['value']['date'])
            for label in dates] == [('A赛道', '本科生', '2026-11-20'), ('B赛道', '研究生', '2026-11-21')]
    assert dates[0]['value']['time'] == '17:30'
    benefits = [label for label in result['labels'] if label['kind'] == 'benefit']
    assert [(label['scope']['track'], label['value']['amount']) for label in benefits] == [
        ('A赛道', 2), ('B赛道', 3)]


@pytest.mark.parametrize(('title', 'body', 'category'), [
    ('竞赛获奖经历要求及奖学金申请通知', '本科生可申请。', 'financial_aid'),
    ('2026届毕业生校园招聘会', '欢迎本科毕业生报名。', 'daily'),
    ('大赛报名通知', '本比赛仅面向研究生。', 'excluded'),
    ('大赛报名通知', '本比赛仅面向本科生和研究生。', 'research_innovation'),
    ('我院成功举办创新大赛', '比赛圆满落幕。', 'excluded'),
    ('国家奖学金拟获奖名单公示', '公示期间可提出异议。', 'financial_aid'),
    ('志愿者招募', '志愿者将为研究生新生提供服务。', 'daily'),
])
def test_primary_eligibility_and_notice_category(title, body, category):
    assert analyze(title, body)['category'] == category


def test_conditions_negation_and_internal_reporting():
    result = analyze('大赛报名通知', '本活动不计志愿时长；获奖后方可认定创新学分2分。',
                     '本科生报名截止至11月20日；学院报送截止至2026年11月21日。')
    benefits = [l for l in result['labels'] if l['kind'] == 'benefit']
    assert [(l['code'], l['value']['condition'], l['value']['claim_only']) for l in benefits] == [
        ('innovation_credit', '获奖后', True)]
    dates = [l for l in result['labels'] if l['kind'] == 'date']
    assert [l['code'] for l in dates] == ['internal_reporting_deadline']
    assert any(g['code'] == 'date_unresolved' for g in result['gaps'])
    assert not result['complete']


def test_does_not_bridge_segments_or_read_missing_assets():
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年', '11月20日。',
                     assets=(DocumentAsset(asset_id='a1'),))
    assert not result['complete']
    assert not [l for l in result['labels'] if l['kind'] == 'date']
    assert {g['code'] for g in result['gaps']} >= {'attachment_unread', 'date_unresolved'}


def test_title_only_preserves_gaps():
    result = analyze('普通通知', status='title_only')
    assert result['category'] == 'unknown'
    assert not result['complete']
    assert not result['labels']
    assert any(g['code'] == 'body_incomplete' for g in result['gaps'])


def test_simple_fully_evidenced_notice_is_complete():
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年11月20日。')
    assert result['complete']
    assert result['category'] == 'daily'
    assert not result['gaps']


def test_generic_deadline_text_requires_review():
    assert not analyze('校园讲座报名通知', '有关事项请另行咨询。')['complete']


def test_report_date_keeps_institutional_audience_separate():
    result = analyze('比赛报名通知', '请各学院于2026年11月20日前将参赛名单报送教务处。')
    dates = [l for l in result['labels'] if l['kind'] == 'date']
    assert [(l['code'], l['scope']['audience']) for l in dates] == [
        ('internal_reporting_deadline', '各学院')]


def test_late_benefit_conditions_are_not_silently_dropped():
    result = analyze('创新赛报名通知', '可获创新学分2分（仅限获奖者）。')
    benefits = [l for l in result['labels'] if l['kind'] == 'benefit']
    assert [l['value']['condition'] for l in benefits] == ['仅限获奖者']


def test_time_range_and_nonlocal_grant_remain_unresolved():
    result = analyze('创新赛报名通知', '报名截止至2026年11月21日17:00—19:00；可获创新学分2分或3分。')
    assert not [l for l in result['labels'] if l['kind'] in ('date', 'benefit')]


def test_graduate_only_track_does_not_exclude_whole_notice():
    result = analyze('创新创业大赛报名通知', '创业实践赛道仅限研究生报名。其他赛道向学生开放。')
    assert result['category'] == 'research_innovation'


def test_negated_grant_cannot_be_read_as_promise():
    result = analyze('志愿者招募', '可获得荣誉证书的说法不实。')
    assert not [l for l in result['labels'] if l['kind'] == 'benefit']


def test_complete_requires_title_and_body_to_cover_same_action():
    result = analyze('校园讲座报名及活动安排', '本科生报名截止至2026年11月20日。')
    assert not result['complete']


def test_public_document_adapter_omits_residual_content(monkeypatch):
    import socket

    from campus_backend.classification.rule_baseline import analyze_rules
    from campus_backend.core.artifacts import make_artifact
    from campus_backend.documents.facts_input import build_document_bundle

    def no_socket(*args, **kwargs):
        pytest.fail('rule analysis attempted network access')

    monkeypatch.setattr(socket, 'socket', no_socket)
    payload = {
        'title': '学生通知', 'source_url': 'https://example.edu/notice',
        'body_status': 'title_only', 'published_at': '2026-11-10',
        'content': '残留内容：本科生报名截止至2026年11月20日。',
        'segments': [{'text': '可获奖金100元'}],
        'private_note': '比赛报名',
    }
    original = make_artifact('document', 'n1', 'v1', payload)
    bundle = build_document_bundle(original)
    assert bundle == build_document_bundle(make_artifact(
        'document', 'n1', 'v1', payload | {'private_note': '奖学金', 'content': '不可读取'},
    ))
    result = analyze_rules(bundle)
    assert result.category == 'unknown'
    assert not result.complete
    assert not result.labels
    assert '残留内容' not in result.model_dump_json()


def test_fully_dated_registration_windows_are_scoped():
    result = analyze('创新大赛报名通知',
                     '本科生A赛道报名时间为2026年11月20日09:00至2026年11月21日17:00；'
                     '本科生B赛道报名时间为2026年11月23日至2026年11月24日。')
    dates = [label for label in result['labels'] if label['kind'] == 'date']
    assert [(l['scope']['track'], l['code'], l['value']['date']) for l in dates] == [
        ('A赛道', 'registration_start', '2026-11-20'),
        ('A赛道', 'registration_deadline', '2026-11-21'),
        ('B赛道', 'registration_start', '2026-11-23'),
        ('B赛道', 'registration_deadline', '2026-11-24'),
    ]


def test_policy_benefits_keep_different_eligibility_conditions():
    result = analyze('创新大赛报名通知',
                     '决赛获奖后方可获推免加分2分；参加初赛后可获综测加分1分。')
    assert [(l['code'], l['value']['condition'], l['value']['amount'])
            for l in result['labels'] if l['kind'] == 'benefit'] == [
        ('recommendation_points', '决赛获奖后', 2),
        ('comprehensive_points', '参加初赛后', 1),
    ]


def test_beneficiaries_and_organizers_are_not_eligibility():
    result = analyze('志愿者招募', '研究生院发布本通知。志愿者仅面向研究生新生提供服务。')
    assert result['category'] == 'daily'
    assert not [l for l in result['labels'] if l['code'] == 'eligibility']


def test_specific_stage_condition_does_not_exclude_undergraduate_notice():
    result = analyze('创新大赛报名通知', '本科生和研究生均可参赛。研究生复赛仅限研究生。')
    assert result['category'] == 'research_innovation'


def test_two_same_scope_benefits_keep_distinct_conditions():
    result = analyze('创新大赛报名通知',
                     'A赛道获一等奖后方可获创新学分2分；A赛道获二等奖后方可获创新学分1分。')
    assert [(l['scope']['track'], l['value']['condition'], l['value']['amount'])
            for l in result['labels'] if l['kind'] == 'benefit'] == [
        ('A赛道', '获一等奖后', 2), ('A赛道', '获二等奖后', 1),
    ]


def test_date_from_publisher_metadata_is_never_a_deadline():
    result = analyze('校园讲座报名通知', '发布日期：2026年11月20日。报名时间另行通知。')
    assert not [l for l in result['labels'] if l['kind'] == 'date']
    assert not result['complete']


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('本科毕业生图像采集通知', '请本科毕业生完成图像采集。', 'daily'),
    ('本科生转换专业名单公示', '可申请复核。', 'daily'),
    ('辅修学士学位遴选办法', '面向本科生。', 'daily'),
    ('推荐免试攻读硕士研究生实施细则', '符合资格的本科生可以申请。', 'daily'),
    ('学生专业分流实施细则', '请学生填报志愿。', 'daily'),
    ('临时困难补助申请流程', '全体本科生可以申请。', 'financial_aid'),
    ('学生评优推荐名单公示', '可提出异议。', 'financial_aid'),
    ('优秀毕业生推荐人选公示', '可提出异议。', 'financial_aid'),
    ('非事业编制工作人员招聘公告', '现公开招聘。', 'excluded'),
    ('教职工教学质量优秀奖评选', '现推荐教师参加。', 'excluded'),
    ('学术论坛参会报名通知', '欢迎本科生参加。', 'daily'),
    ('学生科创培养项目报名通知', '本科生可以申请。', 'research_innovation'),
    ('研究生创新人才项目录取名单公示', '名单公示。', 'excluded'),
    ('食堂恢复营业的通知', '请同学们留意开放时间。', 'daily'),
])
def test_general_title_patterns_from_development_input(title, body, expected):
    assert analyze(title, body)['category'] == expected


@pytest.mark.parametrize(('title', 'paragraphs', 'expected'), [
    ('硕士研究生招生考试考场及自带工具公告', ('请考生按要求自备考试用具。',), 'daily'),
    ('MBA新生奖学金方案', ('评选范围：被正式录取并完成报到注册的MBA新生。',), 'excluded'),
    ('职业规划分享讲座圆满结束', ('本次讲座由学生代表主持。',), 'excluded'),
    ('职业规划分享讲座圆满结束', ('第二期报名现已开放，欢迎本科生报名。',), 'daily'),
    ('竞赛圆满结束', ('本科生如有异议可于2026年11月30日前提出申诉。',), 'research_innovation'),
    ('经管学术论坛第45期——管理学院张教授', (), 'unknown'),
    ('关于举办数字经济学术论坛的通知', ('欢迎师生参加。',), 'daily'),
    ('活动场地审批指南', ('请学生组织提交申请表。',), 'daily'),
    ('租赁设备进场审批指南', ('学生活动中心租赁设备进场流程。',), 'daily'),
    ('学生活动中心场地介绍', ('该报告厅可容纳200人。',), 'excluded'),
    ('校团委概况', (), 'excluded'),
    ('学生活动中心场地介绍', ('学生组织可申请使用。',), 'daily'),
    ('开放课题申报指南', ('申请人须具有博士学位或副高级及以上职称。',), 'excluded'),
    ('博士研究生招生报名公告', ('具有硕士学位的毕业生可申请。',), 'daily'),
])
def test_development_review_uses_applicant_and_action_evidence(title, paragraphs, expected):
    assert analyze(title, *paragraphs, status='full' if paragraphs else 'title_only')['category'] == expected


def test_conflicting_same_scope_deadlines_keep_both_evidence_and_gap():
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年11月20日。本科生报名截止至2026年11月21日。')
    assert not result['complete']
    assert [l['value']['date'] for l in result['labels'] if l['kind'] == 'date'] == ['2026-11-20', '2026-11-21']
    gap, = [g for g in result['gaps'] if g['code'] == 'date_conflict']
    assert len(gap['evidence']) == 2


@pytest.mark.parametrize(('text', 'condition', 'status'), [
    ('只有获得一等奖才颁发荣誉证书', '获得一等奖', 'stated'),
    ('通过审核可获得创新学分2分', '通过审核', 'stated'),
    ('仅限获奖者。可获得创新学分2分', None, 'unknown'),
])
def test_benefits_do_not_assert_unconditional_entitlement(text, condition, status):
    result = analyze('大赛报名通知', text)
    label, = [l for l in result['labels'] if l['kind'] == 'benefit']
    assert (label['value']['condition'], label['value']['condition_status']) == (condition, status)


@pytest.mark.parametrize('text', ['本政策不是长期有效', '“长期有效”的说法不实'])
def test_policy_negation_and_dispute_are_not_valid_status(text):
    result = analyze('管理规定', text)
    assert not [l for l in result['labels'] if l['value'] == 'policy_valid']


def test_explicit_extension_replaces_original_and_preserves_both_clauses():
    result = analyze('大赛报名通知', '本科生报名截止原为2026年11月20日，现延长至2026年11月25日。')
    label, = [l for l in result['labels'] if l['kind'] == 'date']
    assert label['value']['date'] == '2026-11-25'
    assert len(label['evidence']) == 2


def test_unscoped_extension_does_not_leave_original_as_definite():
    result = analyze('大赛报名通知', 'A赛道报名截止原为2026年11月20日；B赛道报名截止至2026年11月21日。'
                     'A赛道现延长至另行通知。')
    dates = [l for l in result['labels'] if l['kind'] == 'date']
    assert [(l['scope']['track'], l['value']['date']) for l in dates] == [('B赛道', '2026-11-21')]
    assert any(g['code'] == 'date_unresolved' for g in result['gaps'])


def test_provisional_deadline_remains_unresolved():
    result = analyze('大赛报名通知', '本科生报名截止暂定为2026年11月20日。')
    assert not [l for l in result['labels'] if l['kind'] == 'date']
    assert any(g['code'] == 'date_unresolved' for g in result['gaps'])


def test_eligibility_restriction_for_one_batch_does_not_exclude_another():
    result = analyze('校园招聘会通知', '本次招聘分两个批次。第一批仅限研究生。第二批面向本科生。')
    assert result['category'] == 'daily'


def test_quoted_or_negated_status_is_not_an_affirmative_label():
    result = analyze('管理规定', '本政策并未废止。原文称“长期有效”。本政策仍在现行有效范围内。')
    statuses = [l['value'] for l in result['labels'] if l['kind'] == 'status']
    assert statuses == ['policy_valid']


def test_same_clause_extension_can_resolve_without_assuming_scope():
    result = analyze('大赛报名通知', 'A赛道报名截止原为2026年11月20日现延长至2026年11月25日。')
    label, = [l for l in result['labels'] if l['kind'] == 'date']
    assert label['value']['date'] == '2026-11-25'
    assert label['scope']['track'] == 'A赛道'


@pytest.mark.parametrize('text', [
    '其他学校政策长期有效',
    '本政策过去曾长期有效',
    '如果本政策长期有效则另行通知',
    '其他学校规定已废止',
    '本规定原已废止，现恢复实施',
    '本政策与其他政策不同，后者长期有效',
    '现行有效的文件详见附件',
])
def test_policy_status_requires_current_assertion_about_this_document(text):
    result = analyze('管理规定', text)
    assert not [l for l in result['labels'] if l['value'] in ('policy_valid', 'policy_expired')]


@pytest.mark.parametrize(('text', 'expected'), [
    ('本规定现行有效', 'policy_valid'),
    ('本办法自发布之日起长期有效', 'policy_valid'),
    ('本通知已废止', 'policy_expired'),
])
def test_policy_status_accepts_current_assertion_about_this_document(text, expected):
    result = analyze('管理规定', text)
    assert [l['value'] for l in result['labels'] if l['kind'] == 'status'] == [expected]


@pytest.mark.parametrize(('pdf', 'html', 'category'), [
    ('本科生报名截止至2026年11月20日。', None, 'research_innovation'),
    ('本比赛仅面向研究生。', None, 'excluded'),
    ('本比赛仅面向本科生和研究生。', None, 'research_innovation'),
    ('本比赛仅面向研究生。', '本科生报名截止至2026年11月20日。', 'research_innovation'),
])
def test_verified_pdf_as_primary_text_only_when_html_body_absent(pdf, html, category):
    from campus_backend.classification.rule_baseline import analyze_rules

    title = '校园大赛报名通知'
    attachment = DocumentSegment(
        id='pdf-1', kind='attachment', text=pdf, location='page:1', page=1,
        asset_id='a1', asset_hash='a' * 64,
    )
    document = DocumentBundle(
        notice_id='n1', content_version='v1', title=title, body_status='full',
        source_url='https://example.edu/notice.pdf', input_fingerprint='1' * 64,
        assets=(DocumentAsset(asset_id='a1', asset_hash='a' * 64),),
        primary_asset_ids=('a1',),
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),)
        + ((DocumentSegment(id='p1', kind='body', text=html, location='html:body'),) if html else ())
        + (attachment,),
    )
    result = analyze_rules(document)
    assert result.category == category
    assert not [gap for gap in result.gaps if gap.code == 'body_incomplete']
    refs = [ref for label in result.labels for ref in label.evidence if ref.segment_id == attachment.id]
    assert refs and all(ref.quote in attachment.text for ref in refs)


def test_unverified_pdf_does_not_stand_in_for_public_main_text():
    from campus_backend.classification.rule_baseline import analyze_rules

    title = '校园大赛报名通知'
    document = DocumentBundle(
        notice_id='n1', content_version='v1', title=title, body_status='full',
        source_url='https://example.edu/notice.pdf', input_fingerprint='1' * 64,
        assets=(DocumentAsset(asset_id='a1'),),
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),
                  DocumentSegment(id='pdf', kind='attachment', text='本比赛仅面向研究生。',
                                  location='page:1', page=1, asset_id='a1')),
    )
    result = analyze_rules(document)
    assert result.category != 'excluded'
    assert any(gap.code == 'body_incomplete' for gap in result.gaps)


@pytest.mark.parametrize('closing', ['特此通知。', '如有疑问请咨询主办方。'])
def test_routine_closing_prose_does_not_change_covered_facts(closing):
    title = '校园讲座报名通知'
    deadline = '本科生报名截止至2026年11月20日。'
    baseline = analyze(title, deadline)
    result = analyze(title, deadline, closing)
    assert result['labels'] == baseline['labels']
    assert result['complete'] == baseline['complete'] is True


def test_consultation_with_approval_changes_required_eligibility():
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年11月20日。',
                     '咨询并审核通过后才可参加。')
    assert any(l['code'] == 'eligibility' and '审核通过' in l['value']['text'] for l in result['labels'])
    assert not result['complete']


def test_covered_conditioned_benefit_can_coexist_with_covered_date():
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年11月20日。',
                     '完成签到后可获志愿时长2小时。')
    label, = [l for l in result['labels'] if l['kind'] == 'benefit']
    assert label['value']['condition'] == '完成签到后'
    assert label['value']['amount'] == 2
    assert result['complete']


@pytest.mark.parametrize('extra', [
    '可获志愿时长2小时。',
    '完成签到后可获志愿时长2小时且审核合格。',
    '若有疑问请咨询主办方并取得审批。',
    '报名资格详见附件。',
])
def test_unbound_target_content_still_blocks_product_completion(extra):
    result = analyze('校园讲座报名通知', '本科生报名截止至2026年11月20日。', extra)
    assert not result['complete']
