"""Synthetic regressions for the supplemental read-only HTML adapter."""
from pathlib import Path
import runpy

import pytest

from campus_backend.classification.simple_categories import classify_simple_notice
from campus_backend.classification.simple_rules import analyze_simple_rules
from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.facts_input import build_document_bundle


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = runpy.run_path(str(ROOT / 'scripts/quality/multischool_html_production.py'))


@pytest.mark.parametrize(('body', 'core', 'production'), [
    ('本项目仅限研究生。本科生请关注后续开放安排。', 'research_innovation', 'excluded'),
    ('一、仅限研究生\n申请材料提交至科研处。', 'excluded', 'research_innovation'),
    ('资格\t仅限研究生', 'excluded', 'research_innovation'),
])
def test_adapter_matches_production_segments_and_category(body, core, production):
    title = '科研项目申报通知'
    record = dict(case_id='synthetic', body_sha256=ADAPTER['digest'](body.encode()),
                  title=title, url='https://example.edu.cn/synthetic')
    paragraphs = tuple(body.splitlines())
    adapted = ADAPTER['html_bundle'](record, paragraphs)
    artifact = make_artifact('document', record['case_id'], record['body_sha256'], {
        'title': title, 'source_url': record['url'], 'content': body,
        'body_status': 'complete', 'assets': [],
    })
    normal_bundle = build_document_bundle(artifact)
    assert [(item.kind, item.text) for item in adapted.segments] == [
        (item.kind, item.text) for item in normal_bundle.segments
    ]
    assert analyze_simple_rules(adapted).category == analyze_simple_rules(normal_bundle).category == production
    assert classify_simple_notice(title, paragraphs) == core


def test_adapter_preserves_nonblank_lines_and_does_not_pass_reference():
    record = dict(case_id='synthetic', body_sha256='a' * 64, title='本科生选课通知',
                  url='https://example.edu.cn/synthetic', reference_category='excluded',
                  reference_reason='must never be passed to classifier', university='test school')
    bundle = ADAPTER['html_bundle'](record, ('  面向全体本科生。  ', '', '  ', '请按时选课。'))
    assert [segment.text for segment in bundle.segments[1:]] == ['  面向全体本科生。  ', '请按时选课。']
    assert bundle.school_id is None and bundle.source_name is None
    assert analyze_simple_rules(bundle).category == 'daily'
