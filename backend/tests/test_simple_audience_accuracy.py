"""User-visible audience regressions, using anonymized development patterns."""

import pytest

from campus_backend.documents.models import DocumentBundle, DocumentSegment
from campus_backend.classification.simple_rules import analyze_simple_rules


def audience_result(title, *paragraphs):
    return analyze_simple_rules(DocumentBundle(
        notice_id='audience-example', content_version='1', title=title, body_status='full',
        source_url='https://example.edu/notice', input_fingerprint='a' * 64,
        segments=(DocumentSegment(id='title', kind='title', text=title, location='title'),)
        + tuple(DocumentSegment(id=f'p{i}', kind='body', text=text, location='html:body')
                for i, text in enumerate(paragraphs)),
    ))


def targets(result):
    return {(item.value.audience, item.value.college, item.value.class_name)
            for item in result.labels if item.kind == 'audience'}


def test_team_members_are_targets_but_cross_discipline_encouragement_is_not_a_major():
    result = audience_result(
        '大学生设计竞赛通知',
        '参赛队队员为全校本科生和研究生。鼓励跨学科专业组队参赛。',
    )
    assert targets(result) == {('全校本科生', None, None), ('研究生', None, None)}


@pytest.mark.parametrize('publication', [
    '拟录取结果在学院网站公示。',
    '入围面试名单及面试具体安排于4月14日在机电学院网站公示。',
    '录取结果将在材料学院的官方网站公布。',
])
def test_result_publication_location_does_not_become_an_audience(publication):
    result = audience_result('本科生选拔通知', publication)
    assert targets(result) == {('本科生', None, None)}
    assert all(group.college is None for label in result.labels
               for group in label.scope.audience_groups)


def test_shared_grade_list_preserves_school_wide_population_and_overrides_publisher():
    result = audience_result(
        '机电学院微专业招生通知',
        '三、招生名额及报名条件\n1.本次招生30人。面向全校大二、大三本科生进行。',
        '要求成绩专业排名前30%。报名截止2026年4月13日。',
    )
    assert targets(result) == {('全校大二、大三本科生', None, None)}
    date = next(label for label in result.labels if label.kind == 'date')
    assert [(g.audience, g.college) for g in date.scope.audience_groups] == [
        ('全校大二、大三本科生', None),
    ]


def test_population_under_application_conditions_overrides_title_department():
    result = audience_result(
        '机电学院2025级本科生转专业考核实施细则',
        '二、申请类别及条件\n2025级全日制普通在籍在校本科生（招生简章明确不可转专业学生除外），每位学生限申报一个志愿。',
        '三、工作流程\n报名截止2026年9月4日。',
    )
    assert targets(result) == {('2025级全日制普通在籍在校本科生', None, None)}
    date = next(label for label in result.labels if label.kind == 'date')
    assert date.scope.audience_groups[0].audience == '2025级全日制普通在籍在校本科生'
    assert date.scope.audience_groups[0].college is None


def test_official_policy_citation_identifies_degree_without_imputing_issuing_department():
    result = audience_result(
        '机电学院辅修专业遴选结果公示',
        '根据《2026年机电学院本科生辅修专业与辅修专业学士学位遴选办法》，学院对所有申报学生进行了综合选拔。',
    )
    assert targets(result) == {('本科生', None, None)}


def test_recommendation_destination_and_qualification_clauses_do_not_add_graduates():
    result = audience_result(
        '工学院推荐2027届免试攻读硕士研究生实施细则',
        '为做好2027届优秀应届本科毕业生免试攻读硕士学位研究生的推荐工作，制定工学院推荐实施细则。',
        '学生须完成培养方案全部教学环节。研究生入学前未取得本科毕业证者取消推免资格。',
        '各学院负责审核申请材料，研究生招生单位负责接收申请。',
    )
    assert targets(result) == {('2027届本科毕业生', '工学院', None)}


def test_entry_and_graduation_year_describe_one_recommendation_cohort():
    result = audience_result(
        '工学院2028届免试攻读硕士学位研究生推荐工作实施细则（2024级）',
        '为做好2028届优秀应届本科毕业生免试攻读硕士学位研究生的推荐工作，现制定本细则。',
    )
    assert targets(result) == {('2028届（2024级）本科生', '工学院', None)}


def test_admitted_named_class_is_not_lost_when_class_has_no_numeric_suffix():
    result = audience_result(
        '2026年卓越创新班录取名单公示',
        '经学生申报和面试，拟录取张某等60名同学进入2026级卓越创新班学习。',
    )
    assert targets(result) == {(None, None, '2026级卓越创新班')}


def test_class_interview_notice_preserves_named_students_and_avoids_venue_department():
    result = audience_result(
        '2026年卓越创新班面试考核通知',
        '经资格审查，学校确定了2026年卓越创新班具有面试考核资格的学生名单。',
        '面试时间为2026年10月10日，地点为工学院。',
    )
    assert targets(result) == {(None, None, '2026年卓越创新班')}
    assert all(g.college is None for label in result.labels for g in label.scope.audience_groups)


def test_generic_selection_condition_does_not_create_a_new_cohort():
    result = audience_result(
        '本科生竞赛通知',
        '面向工学院本科生。',
        '要求具有专业基础，鼓励跨学科专业组队。相关学院负责报名组织。',
        '学生不得以研究生身份重复报名。',
    )
    assert targets(result) == {('本科生', '工学院', None)}


def test_committee_members_and_cited_application_forms_do_not_override_main_cohort():
    result = audience_result(
        '机电学院2025级本科生转专业通知',
        '一、工作机构\n成员如下：成员：各系主任2.成立机电学院本科生转专业考核工作小组。',
        '二、申请类别及条件\n2025级全日制普通在籍在校本科生，每位学生限申报一个志愿。',
        '三、材料提交\n请提交《本科生转专业申请表》，并经主修学院签署意见。',
    )
    assert targets(result) == {('2025级全日制普通在籍在校本科生', None, None)}


def test_a_transfer_program_is_not_a_named_major_in_the_title():
    result = audience_result('关于2025级本科生拟转换专业学生名单公示')
    assert targets(result) == {('2025级本科生', None, None)}


def test_generic_institution_type_does_not_become_a_named_college():
    result = audience_result(
        '大学生创业大赛通知',
        '参赛对象：全日制普通高等学校、技师学院的专科生、本科生、硕士研究生和博士研究生。',
    )
    assert {x[0] for x in targets(result)} == {'专科生', '本科生', '硕士研究生', '博士研究生'}
    assert all(x[1] is None for x in targets(result))


def test_submission_recipient_is_not_a_named_college():
    result = audience_result('2027届本科毕业生推免申请通知', '学生自愿向学院提交推免申请及全部材料。')
    assert targets(result) == {('2027届本科毕业生', None, None)}


def test_background_professional_training_is_not_a_target_major():
    result = audience_result(
        '学生软件竞赛通知',
        '为了促进软件专业技术人才培养，并为参加全国竞赛选拔人才。',
        '参赛对象为全校学生。',
    )
    assert targets(result) == {('全校学生', None, None)}


def test_transfer_destination_table_is_not_an_applicant_restriction():
    result = audience_result(
        '2026年本科学生转专业通知',
        '符合相关规定、申请转专业的本科生，仅限转入以下指定专业：学院专业公共管理学院行政管理社会学建筑与艺术学院建筑学城乡规划。',
    )
    assert targets(result) == {('本科生', None, None)}


def test_explicit_opportunity_for_students_is_a_main_target_declaration():
    result = audience_result(
        '学生创新竞赛通知',
        '本次竞赛为全校学生提供创新创业实践与交流平台。',
        '报名截止2026年11月20日。',
    )
    assert targets(result) == {('全校学生', None, None)}
    date = next(label for label in result.labels if label.kind == 'date')
    assert [g.audience for g in date.scope.audience_groups] == ['全校学生']


@pytest.mark.parametrize('contact', [
    '请于2026年10月13日17:00前加入QQ群1129874625，并完成抽签分组。',
    '请于2026年10月13日前将材料发送到3633592955@qq.com。',
    '请于2026年10月13日前将材料发送到software2401@example.edu。',
    '请于2026年10月13日前访问https://example.edu/软件2401班报名。',
    '报名截止2026年10月13日，联系电话13812345678。',
    '公示时间为2026年10月13日至10月16日，名单：张某7801250210，李某L207241731。',
])
def test_contact_identifiers_and_student_numbers_never_become_classes(contact):
    result = audience_result('本科生竞赛通知', '参赛对象为全校本科生。', contact)
    assert targets(result) == {('全校本科生', None, None)}
    assert all(g.class_name is None for label in result.labels for g in label.scope.audience_groups)


@pytest.mark.parametrize('text, expected', [
    ('面向软件2401班学生。', '软件2401班'),
    ('面向软件2401学生。', '软件2401'),
    ('面向以下班级：软件2401。', '软件2401'),
    ('面向工学院2401班学生。', '2401班'),
])
def test_explicit_class_names_and_contextual_codes_survive(text, expected):
    result = audience_result('校园讲座通知', text)
    assert {label.value.class_name for label in result.labels if label.kind == 'audience'} == {expected}


@pytest.mark.parametrize('text', ['使用设备ABC2401。', '联系助教xiaoming2401。', '名单：张某82102421。'])
def test_untyped_letter_or_name_number_tokens_are_not_class_names(text):
    from campus_backend.classification.simple_audiences import groups

    assert not any(g.class_name for g in groups(text))


def test_admission_publicity_audience_does_not_inherit_historical_interview_or_cited_signup():
    result = audience_result(
        '2026年卓越创新班录取名单公示',
        '根据《2026年卓越创新班报名选拔通知》，经学生本人申报，学校组织简历筛查、面试、项目测试，拟录取张某等60名同学进入2026级卓越创新班学习。',
        '公示时间为2026年10月20日至10月23日。',
    )
    audience, = [label for label in result.labels if label.kind == 'audience']
    assert audience.value.class_name == '2026级卓越创新班'
    assert audience.scope.phase is None
    assert audience.scope.action is None
    date, = [label for label in result.labels if label.kind == 'date']
    assert [g.class_name for g in date.scope.audience_groups] == ['2026级卓越创新班']


def test_audience_phase_only_distinguishes_different_current_stage_populations():
    result = audience_result('学生选拔通知', '初赛：面向工学院本科生。', '复赛：面向商学院研究生。')
    assert {(label.value.college, label.scope.phase) for label in result.labels if label.kind == 'audience'} == {
        ('工学院', '初赛'), ('商学院', '复赛'),
    }
    same = audience_result('学生选拔通知', '初赛：面向工学院本科生。', '复赛：面向工学院本科生。')
    assert all(label.scope.phase is None for label in same.labels if label.kind == 'audience')


def test_current_stage_headings_keep_distinct_audiences():
    result = audience_result('学生选拔通知', '一、初赛\n面向工学院本科生。', '二、复赛\n面向商学院研究生。')
    assert {(label.value.college, label.scope.phase) for label in result.labels if label.kind == 'audience'} == {
        ('工学院', '初赛'), ('商学院', '复赛'),
    }


def test_contact_in_same_sentence_does_not_consume_real_audience():
    result = audience_result('竞赛通知', '面向工学院本科生请发送邮件software2401@example.edu报名。')
    assert targets(result) == {('本科生', '工学院', None)}


def test_title_cohort_refines_compatible_body_degree_without_adding_publisher_college():
    result = audience_result(
        '工学院关于2025级本科生第二批拟转专业学生名单公示',
        '经学生本人申请、所在学院同意，拟同意张某等6名本科生转专业申请。',
        '公示时间为2026年10月21日至10月27日。',
    )
    assert targets(result) == {('2025级本科生', None, None)}
    audience, = [label for label in result.labels if label.kind == 'audience']
    assert {e.segment_id for e in audience.evidence} == {'title', 'p0'}


def test_title_cohort_does_not_override_more_precise_body_audience():
    result = audience_result('工学院2025级本科生招生通知', '招生对象为全校2024级本科生。')
    assert targets(result) == {('全校2024级本科生', None, None)}


def test_learning_qualification_does_not_broaden_explicit_exam_populations():
    result = audience_result(
        '2026年本科生安全教育考试通知',
        '所有本科生必须参加并通过学校统一组织的考试。',
        '一、考试对象\n1.2026级全体全日制本科生。\n2.未通过的非2026级本科生，安排在本次考试的最后一场。',
        '所有学生在线学习时间累计达到6小时方可参加考试。',
        '二、考试时间\n2026年10月31日。',
    )
    expected = {'2026级全体全日制本科生', '非2026级本科生'}
    assert {x[0] for x in targets(result)} == expected
    date, = [label for label in result.labels if label.kind == 'date']
    assert {g.audience for g in date.scope.audience_groups} == expected


@pytest.mark.parametrize('instruction', [
    '杏林校区毕业生拍摄安排和信息核对以医学院通知安排为准。',
    '杏林校区毕业生信息核对按照医学院发布的通知执行。',
    '杏林校区毕业生具体时间以医学院另行通知为准。',
])
def test_arrangement_source_is_not_a_target_college(instruction):
    from campus_backend.classification.simple_audiences import groups

    assert {(group.audience, group.campus, group.college) for group in groups(instruction)} == {
        ('毕业生', '杏林校区', None),
    }


def test_arrangement_source_does_not_restrict_date_audience():
    result = audience_result(
        '2027届本科毕业生图像采集通知',
        '采集对象为2027届本科毕业生。',
        '拍摄时间为2027年4月12日，信息核对以医学院通知安排为准。',
    )
    dates = [label for label in result.labels if label.kind == 'date']
    assert dates
    assert all(group.college is None for label in dates for group in label.scope.audience_groups)


def test_university_students_named_in_competition_title_are_not_missing_or_recast_as_degrees():
    result = audience_result(
        '第七届大学生飞行器虚拟仿真大赛获奖公示通知',
        '该赛事全校共有139人报名参赛。获奖公示名单详见附件。',
    )
    assert targets(result) == {('大学生', None, None)}


def test_explicit_university_student_population_preserves_its_own_name():
    result = audience_result('校园设计竞赛通知', '参赛对象为全校在校大学生。')
    assert targets(result) == {('全校在校大学生', None, None)}


def test_explicit_degree_populations_override_generic_university_student_title():
    result = audience_result('大学生设计竞赛通知', '参赛对象为本科生和研究生。')
    assert targets(result) == {('本科生', None, None), ('研究生', None, None)}


def test_a_university_student_title_does_not_expand_an_undergraduate_only_notice():
    result = audience_result('大学生设计竞赛通知', '本项目仅限本科生参加。')
    assert targets(result) == {('本科生', None, None)}
