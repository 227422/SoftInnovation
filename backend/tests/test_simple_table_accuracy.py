"""V3 schedule columns distinguish named classes from described people."""

import pytest

from test_simple_tags import labels, run
from campus_backend.documents.models import DocumentAsset


def schedule(*rows):
    asset = DocumentAsset(asset_id='exam-schedule', asset_hash='b' * 64)
    return run('本科生考试通知', attachments=((asset, (
        '第七场：2028年11月5日（下午3:30—4:20）',
        '学院\t专业班级\t人数',
        *rows,
    )),))


@pytest.mark.parametrize('separator', ['；', ';', '\n'])
def test_population_descriptions_in_class_column_keep_separate_negative_cohort_groups(separator):
    text = ('1.需补考的非2028级本科生' + separator
            + '2.不能按正常批次参加考试的2028级学生')
    result = schedule(f'\t{text}\t60')
    date, = labels(result, 'date')
    assert [(g.audience, g.class_name) for g in date.scope.audience_groups] == [
        ('需补考的非2028级本科生', None),
        ('不能按正常批次参加考试的2028级学生', None),
    ]
    assert any(text in ref.quote for ref in date.evidence)


def test_table_audience_description_preserves_its_own_college_and_named_class_pairs():
    result = schedule(
        '工学院\t需补考的非2028级本科生\t20',
        '文学院\t中文2801、中文2802\t60',
        '计算机学院\t软件2801\t30',
    )
    date, = labels(result, 'date')
    assert {(g.college, g.class_name, g.audience) for g in date.scope.audience_groups} >= {
        ('工学院', None, '需补考的非2028级本科生'),
        ('文学院', '中文2801', '本科生'),
        ('文学院', '中文2802', '本科生'),
        ('计算机学院', '软件2801', '本科生'),
    }
    assert len(date.scope.audience_groups) == 4


def test_mixed_named_class_and_population_description_are_not_conflated():
    result = schedule('计算机学院\t软件2801、需补考的非2028级本科生\t50')
    date, = labels(result, 'date')
    assert [(g.college, g.class_name, g.audience) for g in date.scope.audience_groups] == [
        ('计算机学院', '软件2801', '本科生'),
        ('计算机学院', None, '需补考的非2028级本科生'),
    ]


def test_detailed_score_requirement_is_not_copied_into_an_audience_label():
    text = '英语四级成绩达到425分的2028级本科生'
    result = schedule(f'工学院\t{text}\t20')
    date, = labels(result, 'date')
    assert [(g.audience, g.class_name) for g in date.scope.audience_groups] == [('2028级本科生', None)]
    assert any(text in ref.quote for ref in date.evidence)
    assert not any('425' in (g.audience or '') for g in date.scope.audience_groups)
    assert {label.kind for label in result.labels} <= {'date', 'audience'}


def test_real_class_with_parenthetical_student_note_remains_a_named_class():
    result = schedule('计算机学院\t软件2801（需补考的学生）\t20')
    date, = labels(result, 'date')
    assert [(g.college, g.class_name) for g in date.scope.audience_groups] == [
        ('计算机学院', '软件2801（需补考的学生）'),
    ]


def test_legacy_v2_class_column_behavior_is_unchanged():
    from test_product_rules import run as run_v2

    text = '1.需补考的非2028级本科生；2.不能按正常批次参加考试的2028级学生'
    result = run_v2('本科考试通知', '学院\t专业班级\t考试时间',
                    f'工学院\t{text}\t2028年11月5日15:30-16:20')
    date, = [label for label in result.labels if label.kind == 'date']
    assert [(g.audience, g.class_name) for g in date.scope.audience_groups] == [(None, text)]
