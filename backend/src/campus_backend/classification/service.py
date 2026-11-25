"""Adapt the unchanged campus_notice 1.0 rules to versioned collector stages."""
from copy import deepcopy
from datetime import datetime

from campus_notice.engine import analyze_batch
from campus_backend.core.artifacts import make_artifact, validate_artifact
from .lifecycle import BEIJING, as_moment, evaluate_visibility, extract_temporal_facts
from .student_scope import apply_student_scope

PRODUCER = {'name': 'campus-classification', 'version': '1.0'}


def _notice(document):
    document = validate_artifact(document, expected_stage='document')
    payload = deepcopy(document['payload'])
    if not isinstance(payload.get('title'), str) or not payload['title'].strip():
        raise ValueError('document title必须为非空字符串')
    payload['id'] = document['notice_id']
    payload['source'] = payload.get('source_name') or ''
    payload['content'] = payload.get('content') or ''
    payload['body_status'] = {'complete': 'full', 'full': 'full', 'partial': 'partial', 'title_only': 'title_only'}.get(payload.get('body_status'), 'title_only')
    if not payload['content'].strip():
        payload['body_status'] = 'title_only'
    for key in ('source_url', 'school'):
        if payload.get(key) is None:
            payload.pop(key, None)
    # Collector document metadata is not a source of official semantic facts.
    # The legacy standalone API still supports its original structured inputs;
    # this adapter derives dates and audience only from actual public text.
    payload.pop('deadline', None)
    payload.pop('audience', None)
    # title_only is an authority boundary even if an upstream failed parser left
    # text or unverified structured metadata in the payload.
    if payload['body_status'] == 'title_only':
        payload['content'] = ''
        payload.pop('deadline', None)
        payload.pop('audience', None)
    return payload


def _run(notice, profile, now):
    batch = analyze_batch([notice], profile, now=now)
    if batch['errors']:
        raise ValueError(batch['errors'][0]['message'])
    return batch['results'][0], batch['rules_version']


def _reference(document):
    return {'stage': document['stage'], 'notice_id': document['notice_id'],
            'content_version': document['content_version'], 'run_id': document['run_id']}


def analyze_document(document: dict, *, now=None, enhancer=None) -> dict:
    """Public rule analysis; no profile, account or personal routing included."""
    notice = _notice(document)
    moment = as_moment(now) if now is not None else datetime.now(BEIJING)
    result, rules_version = _run(notice, None, moment)
    student_scope = apply_student_scope(notice, result)
    facts = extract_temporal_facts(notice, now=moment)
    common = evaluate_visibility(notice, dict(result, _temporal_facts=facts), now=moment)
    payload = {'classification': deepcopy(result['classification']),
               'student_scope': deepcopy(student_scope),
               'audience': {key: deepcopy(result['relevance'][key]) for key in ('constraints', 'evidence', 'warnings')},
               'deadline': deepcopy(result['deadline']),
               'registration_deadline': facts['registration_deadline'], 'event_end': facts['event_end'],
               'temporal_facts': facts, 'validity': common['lifecycle']['validity'],
               'lifecycle': deepcopy(common['lifecycle']), 'visibility': deepcopy(common['visibility']),
               'body_status': {'full': 'complete'}.get(notice['body_status'], notice['body_status']),
               'rules_version': rules_version,
               'evidence': {'classification': deepcopy(result['classification']['evidence']),
                            'segments': deepcopy(document['payload'].get('segments', [])),
                            'document_ref': _reference(document),
                            'source_url': notice.get('source_url', '')},
               'uncertainties': list(dict.fromkeys(result['deadline'].get('warnings', []) +
                         facts['registration_deadline'].get('warnings', []) +
                         (['正文未完整取得，结论待确认'] if notice['body_status'] != 'full' else [])))}
    if any(key in document['payload'] for key in ('deadline', 'audience')):
        payload['uncertainties'].append('文档中的附加结构化截止或受众字段未作为官方事实，已按原文重新识别')
    payload['audience']['warnings'] = [warning for warning in payload['audience']['warnings'] if '个人资料' not in warning]
    # Optional enhancements only supply separately validated candidates. They
    # never mutate official facts, complete a missing body or control visibility.
    from .enhancement import apply_enhancement
    payload['enhancement'] = apply_enhancement(document, payload, enhancer=enhancer)
    return make_artifact('analysis', document['notice_id'], document['content_version'], payload,
                         status='complete', input_refs=[_reference(document)], producer=PRODUCER, now=moment)


def personalize(document: dict, profile: dict | None, *, now=None, analysis=None) -> dict:
    """Return one unchanged classifier result plus current collector lifecycle."""
    notice = _notice(document)
    moment = as_moment(now) if now is not None else datetime.now(BEIJING)
    if analysis is not None:
        analysis = validate_artifact(analysis, expected_stage='analysis')
        if analysis['notice_id'] != document['notice_id'] or analysis['content_version'] != document['content_version']:
            raise ValueError('analysis通知ID或内容版本不匹配 (content_version)')
    result, _ = _run(notice, profile, moment)
    apply_student_scope(notice, result)
    # Recalculate temporal decisions against current official text/time. Passing
    # a shared analysis is a provenance/version check, not authority to replace
    # current official facts or inject private fields.
    result.update(evaluate_visibility(notice, result, now=moment))
    return result
