"""Main-notice context is explicit and cannot be borrowed from unrelated attachments."""
import pytest
from campus_backend.documents.models import DocumentAsset, DocumentBundle, DocumentSegment


def document(title, body, attachments=()):
    segments = [DocumentSegment(id='title', kind='title', text=title, location='title'),
                DocumentSegment(id='main', kind='body', text=body, location='html:body')]
    assets = []
    for asset_no, lines in enumerate(attachments):
        asset_id = f'a{asset_no}'
        assets.append(DocumentAsset(asset_id=asset_id, asset_hash=str(asset_no + 1) * 64))
        for i, line in enumerate(lines):
            segments.append(DocumentSegment(id=f'{asset_id}-{i}', kind='attachment', text=line,
                asset_id=asset_id, asset_hash=str(asset_no + 1) * 64, location=f'sheet:安排/row:{i + 1}'))
    return DocumentBundle(notice_id='fixture', content_version='1', title=title, body_status='full',
        source_url='https://example.edu/notice', segments=segments, assets=assets, input_fingerprint='a' * 64)


def run(value):
    from campus_backend.classification.product_rules import analyze_product_rules
    result = analyze_product_rules(value)
    for label in result.labels:
        for ref in label.evidence:
            assert ref.quote in next(segment.text for segment in value.segments if segment.id == ref.segment_id)
    return result


@pytest.mark.parametrize('heading',['','一、考试时间\n'])
@pytest.mark.parametrize('attachment',['本科生考试安排表','本科生考试时间'])
def test_attachment_list_and_issue_signature_do_not_create_an_exam_date(heading,attachment):
    result=run(document('本科生考试通知',
        heading+f'考试时间为2027年5月3日。\n附件：{attachment}\n本科生院\n资产与实验室管理处\n2027 年 4 月 20 日'))
    windows=[label for label in result.labels if label.kind=='date']
    assert len(windows)==1
    assert windows[0].value.start.date=='2027-05-03'


def test_issue_signature_removal_keeps_an_actual_action_date_on_the_same_line():
    result=run(document('本科生考试通知',
        '本科生院\n2027年5月3日举行考试。'))
    window,=[label for label in result.labels if label.kind=='date']
    assert window.value.start.date=='2027-05-03'


def test_time_section_after_attachment_heading_still_protects_its_actual_date():
    result=run(document('本科生考试通知','附件：考试安排\n一、考试时间\n文学院\n2027年5月3日'))
    window,=[label for label in result.labels if label.kind=='date']
    assert window.value.start.date=='2027-05-03'


def test_action_instruction_is_not_treated_as_a_department_signature():
    result=run(document('本科生考试通知',
        '一、考试时间\n请前往学院\n2027年5月3日'))
    window,=[label for label in result.labels if label.kind=='date']
    assert window.value.start.date=='2027-05-03'


@pytest.mark.parametrize('venue',['文学院','考试地点为文学院'])
def test_explicit_time_section_protects_its_date_after_a_department_or_venue(venue):
    result=run(document('本科生考试通知',f'一、考试时间\n{venue}\n2027年5月3日'))
    window,=[label for label in result.labels if label.kind=='date']
    assert window.value.start.date=='2027-05-03'


def test_exam_context_links_global_entry_and_pass_conditions_to_related_schedule():
    value = document('本科生实验室安全考试通知',
        '一、考试对象\n2026级全体全日制本科生。未通过的非2026级本科生。\n'
        '所有学生在线学习时间累计达到6小时方可参加考试。考试未通过的学生，不能取得该门课程学分。\n'
        '二、考试安排\n具体考试安排详见附件。\n三、考试规则\n合格分数为90分。',
        [('本科生实验室安全考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30',
          '第二场：2026年11月1日10:00—11:00', '学院\t专业班级\t人数', '数学院\t数学2601\t30')])
    result = run(value)
    windows = [label for label in result.labels if label.kind == 'date' and label.presentation == 'display']
    assert len(windows) == 2
    for window in windows:
        assert '在线学习累计至少6小时方可参加考试' in window.value.requirement.items
        assert '2026级全体全日制本科生' in window.scope.audience_groups[0].audience
        assert {'main'} <= {ref.segment_id for ref in window.evidence}
    benefit, = [label for label in result.labels if label.kind == 'benefit']
    assert benefit.value.claim_relation == 'necessary_condition_not_sufficient_guarantee'
    assert any('90' in condition for condition in benefit.value.requirement.items)
    assert benefit.value.amount is None


def test_attachment_hours_and_teacher_constraints_never_become_notice_context():
    value = document('本科生考试通知', '本科生可以参加本次考试。考试安排详见附件。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30'),
         ('另一活动仅限教师参加。在线学习时间累计达到8小时方可参加考试。',)])
    result = run(value)
    assert result.category == 'daily'
    window, = [label for label in result.labels if label.kind == 'date']
    assert window.value.requirement is None
    assert all('a1-' not in ref.segment_id for ref in window.evidence)


def test_photo_eligibility_applies_to_all_class_slots_but_keeps_each_scope():
    value = document('2028届本科毕业生图像采集通知',
        '采集对象为2028届本科毕业生。已采集过学历电子照片的学生不参加本次采集。图像采集分组安排见附件。',
        [('2028届本科毕业生图像采集时间安排表', '校区\t学院\t班级\t采集时间段',
          '东校区\t文学院\t中文2501\t11月13日09:00—09:30',
          '西校区\t数学院\t数学2501\t11月14日10:00—10:30')])
    result = run(value)
    windows = [label for label in result.labels if label.kind == 'date']
    assert len(windows) == 2
    assert [label.scope.audience_groups[0].class_name for label in windows] == ['中文2501', '数学2501']
    assert all(label.value.requirement.items == ('2028届毕业', '尚未采集学历电子照片') for label in windows)


def test_adjacent_publicity_and_named_objection_period_form_one_window():
    value = document('本科生拟转专业名单公示',
        '现将拟转专业名单予以公示，公示时间为2026年10月21日至10月27日。'
        '公示期间若有异议，请以书面署名形式如实反映。')
    result = run(value)
    window, = [label for label in result.labels if label.kind == 'date']
    assert window.code == 'objection'
    assert window.value.start.date == '2026-10-21'
    assert window.value.end.date == '2026-10-27'
    assert set(window.value.requirement.items) == {'书面署名', '如实反映'}
    assert len(window.evidence) == 2


def test_separately_dated_objection_does_not_inherit_the_publicity_end():
    value = document('评奖名单公示', '公示时间为2026年10月21日至10月27日。'
        '申诉截止2026年10月30日，请书面署名提出异议。')
    result = run(value)
    windows = [label for label in result.labels if label.kind == 'date']
    assert len(windows) == 2
    assert next(label for label in windows if label.code == 'objection').value.end.date == '2026-10-30'


@pytest.mark.parametrize(('title', 'body', 'expected'), [
    ('课程金课评选工作通知', '经协议教师申请、学院推荐、学校评审方式确定课程推荐名单。', 'excluded'),
    ('实验教学项目征集通知', '项目旨在提升学生实践能力。请各单位积极组织申报，提交教学项目申报书。', 'excluded'),
    ('课程金课评选工作通知', '欢迎全体本科生参加金课评选投票。', 'daily'),
    ('实验教学项目征集通知', '本科生可申请参与体验活动，请学生报名。', 'daily'),
    ('大学生创新创业项目申报通知', '教师指导本科生申请创新创业项目，欢迎本科生报名。', 'research_innovation'),
])
def test_teaching_construction_distinguishes_applicant_from_student_beneficiary(title, body, expected):
    assert run(document(title, body)).category == expected


def test_two_distinct_exam_thresholds_are_not_promoted_as_one_global_requirement():
    value = document('本科生考试安排通知',
        'A考试的学生在线学习时间累计达到6小时方可参加考试。'
        'B考试的学生在线学习时间累计达到8小时方可参加考试。考试安排详见附件。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30')])
    result = run(value)
    window, = [label for label in result.labels if label.kind == 'date']
    assert window.value.requirement is None


def test_locally_scoped_learning_condition_is_not_a_global_exam_gate():
    value = document('本科生考试通知',
        '研究生在线学习时间累计达到6小时方可参加考试。本科生没有该学时要求。考试安排详见附件。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30')])
    window, = [label for label in run(value).labels if label.kind == 'date']
    assert window.value.requirement is None


def test_explicitly_waived_written_condition_is_not_reintroduced_by_keyword():
    value = document('拟转专业名单公示', '公示时间为2026年10月21日至10月27日。'
        '公示期间如有异议可以反映，无需书面，不要求署名。')
    window, = [label for label in run(value).labels if label.kind == 'date']
    assert window.code == 'objection'
    assert window.value.requirement is None


def test_certificate_followed_by_award_level_explanation_is_not_lost():
    value = document('大学生软件创新比赛通知',
        '比赛设一等奖、二等奖、三等奖若干，颁发荣誉证书，获奖视为校级学科竞赛获奖。')
    certificate, = [label for label in run(value).labels if label.kind == 'benefit']
    assert certificate.code == 'certificate'
    assert certificate.value.requirement.operator == 'any'
    assert certificate.value.requirement.items == ('一等奖', '二等奖', '三等奖')


def test_exam_entry_hours_are_not_required_to_open_earlier_registration():
    value = document('本科生考试通知', '报名截止2026年10月20日。'
        '所有学生在线学习时间累计达到6小时方可参加考试。考试时间为2026年11月1日09:00—10:00。')
    windows = [label for label in run(value).labels if label.kind == 'date']
    assert next(label for label in windows if label.code == 'registration').value.requirement is None
    assert next(label for label in windows if label.code == 'event').value.requirement.items == ('在线学习累计至少6小时方可参加考试',)


def test_score_for_a_different_population_does_not_define_undergraduate_pass_condition():
    value = document('本科生考试通知', '考试未通过的学生，不能取得该门课程学分。'
        '研究生考试成绩不低于80分。本科生考试合格分数尚未确定。')
    benefit, = [label for label in run(value).labels if label.kind == 'benefit']
    assert not any('80' in item for item in benefit.value.requirement.items)


def test_pdf_wrapped_numbered_sentences_are_not_removed_as_section_headings():
    value = document('本科生考试通知', '一、考试对象\n1.2026级全体全日制本科生。\n'
        '2.未通过的非2026级本科生，考试安排在本次考试的最\n后一场。考试安排详见附件。\n'
        '四、考试方式及操作步骤\n考试时间为50分钟，\n合格分数为90分。'
        '考试未通过的学生，不能取得该门课程学分。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30')])
    result = run(value)
    window, = [label for label in result.labels if label.kind == 'date']
    assert '未通过考试的非2026级本科生' in window.scope.audience_groups[0].audience
    benefit, = [label for label in result.labels if label.kind == 'benefit']
    assert any('90' in condition for condition in benefit.value.requirement.items)


def test_wrapped_application_sentence_retains_qualification_and_deadline():
    value = document('本科学生转专业补充通知',
        '一、符合《管理办法》第三章第\n八条第四项相关规定、申请转专业的本科生，仅限转入以下指定专业。\n'
        '1. 报名时间：符合要求并有相关需求的学生请于10月8日前填\n报申请表报送至相关学院。')
    window, = [label for label in run(value).labels if label.kind == 'date']
    assert window.value.end.month_day == '10-08'
    assert '符合《管理办法》第三章第八条第四项相关规定' in window.value.requirement.items


def test_main_pdf_section_continues_across_pages_but_resets_for_another_asset():
    from campus_backend.classification.product_context import primary_clauses

    value = document('本科生考试通知', '请阅读通知正文。',
        [('一、考试对象', '2028级本科生。'), ('另一份材料独立内容。',)])
    payload = value.model_dump()
    payload['primary_asset_ids'] = ['a0', 'a1']
    for segment in payload['segments'][2:]:
        segment['page'] = int(segment['id'].rsplit('-', 1)[1]) + 1
        segment['location'] = 'page:' + str(segment['page'])
    clauses = primary_clauses(DocumentBundle.model_validate(payload))
    assert next(c for c in clauses if c.text == '2028级本科生').section == '一、考试对象'
    assert next(c for c in clauses if c.text == '另一份材料独立内容').section == ''


def test_publicity_dates_are_not_inherited_by_another_primary_asset():
    from campus_backend.classification.product_context import primary_clauses, window_clauses

    value = document('评奖名单公示', '请阅读正文。',
        [('公示时间为2026年10月21日至10月27日。',), ('公示期间如有异议，请书面反映。',)])
    payload = value.model_dump()
    payload['primary_asset_ids'] = ['a0', 'a1']
    for segment in payload['segments'][2:]:
        segment.update(page=1, location='page:1')
    clauses = window_clauses(primary_clauses(DocumentBundle.model_validate(payload)))
    assert len(clauses) == 3


@pytest.mark.parametrize('condition', ['合格分数为80分。', '学生在线学习累计达到6小时方可参加考试。'])
def test_other_population_section_does_not_supply_undergraduate_credit_conditions(condition):
    value = document('本科生考试通知', '一、本科生考试\n考试未通过的学生，不能取得该门课程学分。\n'
        '二、研究生考试\n' + condition)
    result = run(value)
    benefit, = [label for label in result.labels if label.kind == 'benefit']
    assert benefit.value.requirement.items == ('考试合格',)
    assert any(gap.code == 'coverage_unconfirmed' and '章节' in gap.detail for gap in result.gaps)


def test_nested_population_sections_keep_each_exam_threshold_local():
    value = document('本科生考试通知', '一、本科生考试\n1.考试规则\n合格分数为90分。'
        '考试未通过的学生，不能取得该门课程学分。\n'
        '二、研究生考试\n1.考试规则\n合格分数为80分。')
    result = run(value)
    benefit, = [label for label in result.labels if label.kind == 'benefit']
    assert any('90分' in item for item in benefit.value.requirement.items)
    assert all('80分' not in item for item in benefit.value.requirement.items)
    assert '一、本科生考试' in {ref.quote for ref in benefit.evidence}
    assert any('二、研究生考试' in {ref.quote for ref in gap.evidence} for gap in result.gaps)


def test_graduate_section_hours_never_flow_into_undergraduate_schedule():
    value = document('本科生考试通知', '一、本科生考试\n考试安排详见附件。\n'
        '二、研究生考试\n1.考试规则\n学生在线学习累计达到8小时方可参加考试。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30')])
    window, = [label for label in run(value).labels if label.kind == 'date']
    assert window.value.requirement is None


def phase_limited_exam(second_slot='第二场：2026年11月1日10:00—11:00', extra_tables=()):
    return document('本科生考试通知', '一、考试对象\n2026级全体全日制本科生。'
        '未通过的非2026级本科生，考试安排在本次考试的最后一场。\n二、考试安排\n考试安排详见附件。',
        [('本科生考试考场安排表', '第一场：2026年11月1日09:00—10:00',
          '学院\t专业班级\t人数', '文学院\t中文2601\t30', second_slot,
          '学院\t专业班级\t人数', '数学院\t数学2601\t30'), *extra_tables])


def test_last_session_population_is_added_only_to_its_confirmed_time_window():
    result = run(phase_limited_exam())
    windows = [label for label in result.labels if label.kind == 'date']
    first, second = windows
    assert '未通过考试的非2026级本科生' not in first.scope.audience_groups[0].audience
    assert '未通过考试的非2026级本科生' in second.scope.audience_groups[0].audience
    assert first.scope.audience_groups[0].class_name == '中文2601'
    assert second.scope.audience_groups[0].class_name == '数学2601'
    assert len(first.scope.audience_groups) == len(second.scope.audience_groups) == 1
    assert all('2026级全体全日制本科生' in label.scope.audience_groups[0].audience for label in windows)


def test_pending_last_session_keeps_population_scope_unresolved_instead_of_broadening():
    result = run(phase_limited_exam('第二场：时间另行通知'))
    windows = [label for label in result.labels if label.kind == 'date']
    assert all('未通过考试的非2026级本科生' not in label.scope.audience_groups[0].audience for label in windows)
    assert any(gap.code == 'coverage_unconfirmed' and '最后一场' in gap.detail for gap in result.gaps)


def test_last_session_cannot_be_guessed_across_separate_schedule_assets():
    value = phase_limited_exam(extra_tables=[('本科生考试考场安排表',
        '第一场：2026年11月2日09:00—10:00', '学院\t专业班级\t人数', '法学院\t法学2601\t30')])
    result = run(value)
    windows = [label for label in result.labels if label.kind == 'date']
    assert all('未通过考试的非2026级本科生' not in label.scope.audience_groups[0].audience for label in windows)
    assert any('最后一场' in gap.detail for gap in result.gaps)


def test_last_session_uses_explicit_chronology_not_phase_name_or_list_position():
    value = document('本科生考试通知', '一、考试对象\n2026级全体全日制本科生。'
        '未通过的非2026级本科生，考试安排在本次考试的最后一场。考试安排详见附件。',
        [('本科生考试考场安排表', '第一场：2026年11月2日09:00—10:00',
          '学院\t专业班级\t人数', '法学院\t法学2601\t30',
          '第二场：2026年11月1日10:00—11:00', '学院\t专业班级\t人数', '数学院\t数学2601\t30')])
    result = run(value)
    windows = [label for label in result.labels if label.kind == 'date']
    final, earlier = windows
    assert '未通过考试的非2026级本科生' in final.scope.audience_groups[0].audience
    assert '未通过考试的非2026级本科生' not in earlier.scope.audience_groups[0].audience


def test_unknown_exam_subtopic_does_not_become_the_general_exam_pass_score():
    value = document('本科生考试通知', '一、本科生考试\n考试未通过的学生，不能取得该门课程学分。\n'
        '二、培训考核\n1.考试规则\n合格分数为80分。')
    result = run(value)
    benefit, = [label for label in result.labels if label.kind == 'benefit']
    assert benefit.value.requirement.items == ('考试合格',)
    assert any(gap.code == 'coverage_unconfirmed' and '章节' in gap.detail for gap in result.gaps)


@pytest.mark.parametrize('special_group', ['未通过考试的非2026级本科生', '历届补考人员'])
def test_unresolved_special_table_group_is_not_restricted_to_the_general_grade(special_group):
    value = phase_limited_exam()
    segments = list(value.segments)
    segments[-1] = segments[-1].model_copy(update={'text': '全校\t' + special_group + '\t30'})
    value = value.model_copy(update={'segments': tuple(segments), 'gaps': ('unread_attachment',), 'body_status': 'partial'})
    result = run(value)
    first, final = [label for label in result.labels if label.kind == 'date']
    assert first.scope.audience_groups[0].audience == '2026级全体全日制本科生'
    group, = final.scope.audience_groups
    assert group.class_name == special_group
    assert group.audience is None
    assert any(gap.code == 'coverage_unconfirmed' and '交集' in gap.detail for gap in result.gaps)
