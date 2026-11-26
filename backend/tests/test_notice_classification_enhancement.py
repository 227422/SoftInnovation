"""An optional adapter may add cited candidates; official facts remain intact."""
from copy import deepcopy
from datetime import datetime
import time

import pytest

from campus_backend.classification.service import analyze_document, personalize
from test_notice_classification import document

NOW = datetime.fromisoformat('2026-10-31T12:00:00+08:00')


class Stub:
    timeout_seconds = 0.05

    def __init__(self, mode='success'):
        self.mode = mode

    def enhance(self, request):
        if self.mode == 'failure':
            raise RuntimeError('provider secret should not appear in public result')
        if self.mode == 'timeout':
            time.sleep(0.2)
        if self.mode == 'invalid':
            return ['not an envelope']
        value = {'schema_version': '1.0', 'stage': 'enhancement', 'notice_id': request['notice_id'],
                 'content_version': request['content_version'], 'run_id': 'stub-output',
                 'created_at': '2026-10-31T12:00:00+08:00',
                 'producer': {'name': 'local-test-stub', 'version': '1.0'}, 'status': 'complete',
                 'errors': [], 'input_refs': [], 'payload': {'candidates': [
                     {'field': 'category', 'value': 'competition', 'evidence': [
                         {'source': 'content', 'quote': '面向全校学生'}]}]}}
        if self.mode == 'wrong_version':
            value['content_version'] = 'old'
        elif self.mode == 'wrong_schema':
            value['schema_version'] = '2.0'
        elif self.mode == 'invented_evidence':
            value['payload']['candidates'][0]['evidence'][0]['quote'] = '从未出现在原文中的内容'
        elif self.mode == 'change_official_fact':
            value['payload']['candidates'][0]['field'] = 'registration_deadline'
            value['payload']['candidates'][0]['value'] = '2027-01-01'
        elif self.mode == 'empty_evidence':
            value['payload']['candidates'][0]['evidence'] = []
        elif self.mode == 'profile_leak':
            value['payload']['profile'] = {'school': 'secret'}
        elif self.mode == 'mutate':
            request['payload']['document']['payload']['content'] = 'mutated by provider'
            request['payload']['analysis']['classification']['notice_type'] = 'malicious'
        return value


def test_disabled_enhancement_runs_normal_rules():
    result = analyze_document(document('面向全校学生。学生报名截止2026年12月1日。'), now=NOW)
    assert result['payload']['enhancement']['status'] == 'disabled'
    assert result['payload']['registration_deadline']['value'] == '2026-12-01'


def test_success_is_separate_cited_candidate_and_preserves_input_and_rules():
    doc = document('面向全校学生。学生报名截止2026年12月1日。')
    saved = deepcopy(doc)
    plain = analyze_document(doc, now=NOW)
    enhanced = analyze_document(doc, now=NOW, enhancer=Stub())
    assert enhanced['payload']['enhancement']['status'] == 'accepted'
    assert enhanced['payload']['enhancement']['candidates'][0]['value'] == 'competition'
    assert enhanced['payload']['enhancement']['artifact']['producer']['name'] == 'local-test-stub'
    for key in ('classification', 'deadline', 'registration_deadline', 'audience', 'body_status'):
        assert enhanced['payload'][key] == plain['payload'][key]
    assert doc == saved
    assert personalize(doc, None, now=NOW, analysis=enhanced)['visibility'] == personalize(doc, None, now=NOW)['visibility']


@pytest.mark.parametrize('mode,code', [
    ('failure', 'enhancement_failed'), ('timeout', 'enhancement_timeout'),
    ('invalid', 'enhancement_invalid'), ('wrong_version', 'enhancement_version_mismatch'),
    ('wrong_schema', 'enhancement_invalid'), ('invented_evidence', 'enhancement_invalid'),
    ('change_official_fact', 'enhancement_invalid'), ('empty_evidence', 'enhancement_invalid'),
    ('profile_leak', 'enhancement_invalid')])
def test_failure_and_untrusted_candidates_fall_back_without_fact_changes(mode, code):
    doc = document('面向全校学生。学生报名截止2026年12月1日。')
    saved = deepcopy(doc)
    result = analyze_document(doc, now=NOW, enhancer=Stub(mode))
    assert result['payload']['enhancement']['status'] == 'fallback'
    assert result['payload']['enhancement']['candidates'] == []
    assert result['payload']['enhancement']['errors'][0]['code'] == code
    assert result['payload']['registration_deadline']['value'] == '2026-12-01'
    assert 'secret' not in str(result)
    assert doc == saved


def test_enhancer_mutation_cannot_modify_public_analysis_or_document():
    doc = document('面向全校学生。学生报名截止2026年12月1日。')
    result = analyze_document(doc, now=NOW, enhancer=Stub('mutate'))
    assert doc['payload']['content'].startswith('面向全校学生')
    assert result['payload']['classification']['notice_type'] != 'malicious'


def test_title_only_cannot_cite_unavailable_body():
    doc = document('面向全校学生。学生报名截止2026年12月1日。', body='title_only')
    result = analyze_document(doc, now=NOW, enhancer=Stub())
    assert result['payload']['enhancement']['status'] == 'fallback'
    assert result['payload']['registration_deadline']['status'] == 'unknown'
