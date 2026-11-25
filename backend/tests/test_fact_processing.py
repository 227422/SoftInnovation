from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from campus_backend.core.artifacts import make_artifact


TITLE = '奖学金申报通知'
URL = 'https://example.edu.cn/notices/42'
HASH = 'a' * 64
BODY = '全体本科生可以申请奖学金，竞赛获奖证明可作为材料。'
ATTACHMENT = '申报截至2026年11月15日。'
BASIC = dict(title=TITLE, source_url=URL, source_id='catalog', source_name='发布学院', school_id='csu',
             published_at='2026-11-01', body_status='complete', content=BODY + '\n\n' + ATTACHMENT,
             segments=[dict(text=BODY, location='html:body', page=None, asset_id=None, method='html_text'),
                       dict(text=ATTACHMENT, location='page:2', page=2, asset_id='attachment', method='native')],
             assets=[dict(asset_id='attachment', sha256=HASH, filename='申请.pdf',
                          url='https://example.edu.cn/application.pdf', status='complete', path='private/path')])
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def artifact(**changes):
    payload = deepcopy(BASIC)
    payload.update(changes)
    return make_artifact('document', 'notice-42', 'v1', payload, now=NOW)


def bundle(**changes):
    from campus_backend.documents.facts_input import build_document_bundle
    return build_document_bundle(artifact(**changes))


def action(id='a', *, kind='scholarship_application', student_scope='undergraduate', main=True,
           evidence_ids=('main',)):
    return dict(id=id, main=main, kind=kind, student_scope=student_scope, text='本科生行动', evidence_ids=evidence_ids)


def evidence(doc, id='main', *, segment=None, quote=None, **changes):
    segment = segment or doc.segments[min(1, len(doc.segments) - 1)]
    result = dict(evidence_id=id, source_kind='notice', source_id=doc.notice_id, source_url=doc.source_url,
                  source_content_version=doc.content_version, asset_id=segment.asset_id, asset_hash=segment.asset_hash,
                  locator=dict(segment_id=segment.id, page=segment.page), quote=quote or segment.text)
    return result | changes


def candidates(doc, **changes):
    from campus_backend.classification.models import FactCandidates
    values = dict(notice_id=doc.notice_id, content_version=doc.content_version, input_fingerprint=doc.input_fingerprint,
                  actions=[action()], evidence_refs=[evidence(doc)])
    return FactCandidates.model_validate(values | changes)


def field_check(path='actions', id='a', *, refs=('main',), **changes):
    values = dict(field_path=path, candidate_id=id, source_ok=True, semantic_status='supported',
                  relation_complete=True, support_refs=refs, counter_refs=(), unresolved_conflict=False,
                  reason_code='reviewed')
    return values | changes


def report(facts, *fields, **changes):
    from campus_backend.classification.facts import candidate_digest
    from campus_backend.classification.models import VerificationReport
    values = dict(notice_id=facts.notice_id, content_version=facts.content_version,
                  input_fingerprint=facts.input_fingerprint, candidate_digest=candidate_digest(facts), checks=fields,
                  coverage_complete=True, missing_facts=[])
    return VerificationReport.model_validate(values | changes)


def verify(doc, facts, *fields):
    from campus_backend.classification.facts import verify_candidates
    return verify_candidates(doc, facts, report(facts, *fields))


def test_original_adapter_keeps_stable_exact_body_and_attachment_segments():
    document = artifact(cookie='PRIVATE', profile={'email': 'private@example.com'},
                        deadline='false', html='<script>ignored</script>')
    document['payload']['segments'][0]['text'] += '\n\n第二段。'
    document['payload']['content'] = document['payload']['segments'][0]['text'] + '\n\n' + ATTACHMENT
    original = deepcopy(document)
    from campus_backend.documents.facts_input import build_document_bundle
    result = build_document_bundle(document)
    assert document == original
    assert result.body_status == 'full'
    assert [seg.text for seg in result.segments] == [TITLE, BODY, '第二段。', ATTACHMENT]
    assert len({seg.id for seg in result.segments}) == 4
    assert result.segments[0].id == 'title'
    assert (result.segments[-1].page, result.segments[-1].asset_id, result.segments[-1].asset_hash) == (
        2, 'attachment', HASH)
    assert result.assets[0].asset_hash == HASH
    encoded = result.model_dump_json()
    assert not any(secret in encoded for secret in ('PRIVATE', 'private@example.com', 'private/path', 'false', '<script>'))
    repeat = build_document_bundle(document | {'run_id': 'rerun', 'created_at': '2026-11-11T00:00:00+00:00'})
    assert repeat.input_fingerprint == result.input_fingerprint
    assert repeat.segments == result.segments


def test_fingerprint_changes_for_changed_text_and_original_attachment():
    original = bundle()
    text = '正文修订。'
    changed_body = bundle(content=text, segments=[BASIC['segments'][0] | {'text': text}])
    changed_asset = bundle(assets=[BASIC['assets'][0] | {'sha256': 'b' * 64}])
    assert len({original.input_fingerprint, changed_body.input_fingerprint, changed_asset.input_fingerprint}) == 3


def test_title_only_cannot_recover_residual_content_or_segments():
    original = bundle(body_status='title_only')
    stripped = bundle(body_status='title_only', content=None, segments=None)
    assert [seg.text for seg in original.segments] == [TITLE]
    assert original.input_fingerprint == stripped.input_fingerprint
    facts = candidates(original, evidence_refs=[evidence(original, segment=original.segments[0], quote=BODY)])
    assert verify(original, facts, field_check()).category == 'unknown'


@pytest.mark.parametrize('changes', [{'stage': 'raw'}, {'schema_version': '2.0'}, {'payload': {}},
                                     {'content_version': ''}, {'created_at': '2026-11-10'}])
def test_invalid_document_envelope_rejected(changes):
    from campus_backend.documents.facts_input import build_document_bundle
    with pytest.raises(ValueError):
        build_document_bundle(artifact() | changes)


def test_unknown_segment_format_does_not_make_concatenated_body_evidence():
    doc = bundle(segments=[BASIC['segments'][0], {'opaque': ATTACHMENT}])
    assert doc.body_status == 'partial'
    assert doc.gaps
    assert [segment.text for segment in doc.segments] == [TITLE, BODY]


@pytest.mark.parametrize(('kinds', 'expected'), [
    (('scholarship_application',), 'financial_aid'),
    (('competition', 'research'), 'research_innovation'),
    (('competition', 'scholarship_application'), 'unknown'),
    (('activity',), 'daily'),
    ((), 'unknown'),
])
def test_classification_uses_verified_main_actions_not_background_or_publisher(kinds, expected):
    doc = bundle()
    actions = [action(str(i), kind=kind) for i, kind in enumerate(kinds)] + [action('background', kind='competition', main=False)]
    fields = [field_check(id=item['id']) for item in actions]
    result = verify(doc, candidates(doc, actions=actions), *fields)
    assert result.category == expected


def test_competition_award_publication_remains_competition():
    body = '本科生创新大赛获奖名单公示，异议请在公示期内提出。'
    doc = bundle(title='创新大赛获奖公示', content=body, segments=[], assets=[])
    result = verify(doc, candidates(doc, actions=[action(kind='competition')]), field_check())
    assert result.category == 'research_innovation'


def test_confirmed_non_undergraduate_main_action_can_exclude_only_when_body_full():
    facts = dict(actions=[action(student_scope='non_undergraduate')], requirements={'complete': True},
                 benefit_conditions={'complete': True})
    full = bundle()
    partial = bundle(body_status='partial')
    assert verify(full, candidates(full, **facts), field_check()).category == 'excluded'
    result = verify(partial, candidates(partial, **facts), field_check())
    assert result.category == 'unknown'
    assert result.actions
    assert result.complete is False


def test_missing_review_of_another_main_action_blocks_classification():
    doc = bundle()
    facts = candidates(doc, actions=[action(), action('unreviewed', kind='competition')])
    result = verify(doc, facts, field_check())
    assert [item.id for item in result.actions] == ['a']
    assert result.category == 'unknown'
    assert any(gap.candidate_id == 'unreviewed' and gap.reason_code == 'missing_check' for gap in result.gaps)
    assert result.candidates == facts


@pytest.mark.parametrize('changes', [
    {'semantic_status': 'contradicted', 'counter_refs': ['main']}, {'unresolved_conflict': True},
    {'semantic_status': 'insufficient'}, {'source_ok': False}, {'relation_complete': False},
    {'support_refs': []}, {'counter_refs': ['main']},
])
def test_check_must_support_source_semantics_and_relation_without_counter_evidence(changes):
    doc = bundle()
    facts = candidates(doc)
    result = verify(doc, facts, field_check(**changes))
    assert result.actions == ()
    assert result.category == 'unknown'
    assert result.gaps and result.complete is False


@pytest.mark.parametrize('defect', ['quote', 'source', 'version', 'url', 'asset', 'hash', 'page', 'clause', 'no_hash'])
def test_local_attachment_evidence_cannot_be_overridden_by_supported_check(defect):
    doc = bundle(assets=[BASIC['assets'][0] | {'sha256': None}]) if defect == 'no_hash' else bundle()
    segment = doc.segments[-1]
    ref = evidence(doc, segment=segment)
    changes = {'quote': ('quote', BODY), 'source': ('source_id', 'another-notice'),
               'version': ('source_content_version', 'v0'), 'url': ('source_url', 'https://example.edu.cn/other'),
               'asset': ('asset_id', 'another-asset'), 'hash': ('asset_hash', 'b' * 64),
               'page': ('locator', {'segment_id': segment.id, 'page': 1}),
               'clause': ('locator', {'segment_id': segment.id, 'page': 2, 'clause': 'fake-clause'}),
               'no_hash': ('asset_hash', HASH)}
    key, value = changes[defect]
    ref[key] = value
    result = verify(doc, candidates(doc, evidence_refs=[ref]), field_check())
    assert result.actions == () and result.evidence_refs == ()


def test_attachment_page_only_citation_binds_to_actual_page():
    doc = bundle()
    ref = evidence(doc, segment=doc.segments[-1], locator={'page': 2})
    result = verify(doc, candidates(doc, evidence_refs=[ref]), field_check())
    assert result.actions and result.evidence_refs[0].asset_hash == HASH


def test_report_binding_rejects_stale_fingerprint_candidate_or_foreign_checks():
    from campus_backend.classification.facts import verify_candidates
    doc = bundle()
    facts = candidates(doc)
    changed = candidates(doc, actions=[action(kind='competition')])
    with pytest.raises(ValueError):
        verify_candidates(doc, changed, report(facts, field_check()))
    with pytest.raises(ValueError):
        verify_candidates(doc, facts, report(facts, field_check(), input_fingerprint='f' * 64))
    with pytest.raises(ValueError):
        verify(doc, facts, field_check(), field_check())
    with pytest.raises(ValueError):
        verify(doc, facts, field_check(id='unrecognized'))
    with pytest.raises(ValueError):
        verify(doc, facts, field_check(refs=['unknown-evidence']))
    with pytest.raises(ValueError):
        verify(bundle(title='changed'), facts, field_check())


def condition(id='student', **changes):
    return dict(id=id, kind='audience', field='education_stage', operator='eq', value='本科',
                text='全体本科生', evidence_ids=['main']) | changes


def group(id, *members, track_id=None):
    return dict(id=id, operator='all', members=[dict(type=kind, id=member) for kind, member in members],
                label=id, track_id=track_id)


def requirement(*groups, conditions=None, root='g', complete=True):
    return dict(conditions=[condition()] if conditions is None else conditions, groups=groups,
                complete=complete, root_group_id=root)


def time_window(**changes):
    return dict(id='deadline', action_id='a', kind='registration', label='申报截止',
                student_action=True, explicit_long_term=False, audience_complete=True,
                end=dict(precision='date', value='2026-11-15'), raw_text=ATTACHMENT, evidence_ids=['date']) | changes


def window_facts(doc, window, **changes):
    return candidates(doc, evidence_refs=[evidence(doc), evidence(doc, 'date', segment=doc.segments[-1])],
                      time_windows=[window], **changes)


def window_check():
    return field_check('time_windows', 'deadline', refs=['date'])


def test_verified_one_sided_date_window_preserves_precision_and_input():
    doc = bundle()
    facts = window_facts(doc, time_window())
    checked = report(facts, field_check(), window_check())
    original = (doc.model_dump(), facts.model_dump(), checked.model_dump())
    from campus_backend.classification.facts import verify_candidates
    result = verify_candidates(doc, facts, checked)
    assert len(result.time_windows) == 1
    confirmed = result.time_windows[0]
    assert confirmed.verification == 'confirmed'
    assert confirmed.start is None and confirmed.end.value == '2026-11-15' and confirmed.end.precision == 'date'
    assert (doc.model_dump(), facts.model_dump(), checked.model_dump()) == original


@pytest.mark.parametrize('change', [
    {'end': {'value': '2026-02-30', 'precision': 'date'}},
    {'end': {'value': '11-15', 'precision': 'date'}},
    {'end': {'value': '2026-11-15T15:00:00', 'precision': 'datetime'}},
    {'start': {'value': '2026-11-16', 'precision': 'date'}},
    {'start': {'value': '2026-11-15T15:00:00+08:00', 'precision': 'datetime'},
     'end': {'value': '2026-11-15T08:00:00+02:00', 'precision': 'datetime'}},
    {'end': None, 'verification': 'uncertain', 'uncertainty_reason': '原文没有年份'},
    {'audience_complete': False},
    {'action_id': 'another-action'},
])
def test_invalid_or_unlinked_date_cannot_be_confirmed_even_with_semantic_support(change):
    doc = bundle()
    facts = window_facts(doc, time_window(**({'verification': 'confirmed'} | change)))
    result = verify(doc, facts, field_check(), window_check())
    assert result.time_windows == ()
    assert result.candidates.time_windows
    assert any(gap.candidate_id == 'deadline' for gap in result.gaps)


def test_window_requires_year_in_support_or_source_context():
    doc = bundle(segments=[BASIC['segments'][0], BASIC['segments'][1] | {'text': '申报截至11月15日。'}],
                 content=BODY + '\n\n申报截至11月15日。')
    result = verify(doc, window_facts(doc, time_window()), field_check(), window_check())
    assert result.time_windows == ()


def test_window_cannot_borrow_a_different_tracks_confirmed_audience_group():
    doc = bundle()
    req = requirement(group('g', ('condition', 'student'), track_id='track-a'))
    facts = window_facts(doc, time_window(track_id='track-b', audience_group_id='g'), requirements=req)
    result = verify(doc, facts, field_check(), field_check('requirements.conditions', 'student'),
                    field_check('requirements.groups', 'g'), window_check())
    assert [item.id for item in result.requirements.groups] == ['g']
    assert result.time_windows == ()


def test_group_with_unconfirmed_leaf_or_cycle_cannot_support_window():
    doc = bundle()
    cyclic = requirement(group('g', ('group', 'other'), ('condition', 'student')),
                         group('other', ('group', 'g')))
    direct = requirement(group('g', ('condition', 'student')))
    for req in (cyclic, direct):
        facts = window_facts(doc, time_window(audience_group_id='g'), requirements=req)
        condition_checks = [field_check('requirements.conditions', 'student')] if req == cyclic else []
        result = verify(doc, facts, field_check(), window_check(), field_check('requirements.groups', 'g'),
                        *condition_checks)
        assert result.requirements.groups == ()
        assert result.requirements.complete is False
        assert result.time_windows == ()


def test_verified_eligibility_graph_does_not_claim_complete_on_partial_body():
    doc = bundle(body_status='partial')
    req = requirement(group('g', ('condition', 'student')))
    result = verify(doc, candidates(doc, requirements=req), field_check(),
                    field_check('requirements.conditions', 'student'), field_check('requirements.groups', 'g'))
    assert result.requirements.conditions[0].verification == 'confirmed'
    assert result.requirements.root_group_id == 'g'
    assert result.requirements.complete is False and result.complete is False


def benefit_condition(**changes):
    return dict(id='attendance', kind='attendance', target_id='a', target_text='志愿活动',
                operator='eq', value=True, text='参加并签到', evidence_ids=['benefit']) | changes


def benefit_claim(**changes):
    return dict(id='volunteer-hours', type='volunteer', condition_root_id='earn', action_id='a',
                amount=2, unit='小时', text='签到后获得2小时志愿时长', evidence_ids=['benefit']) | changes


def test_volunteer_benefit_conditions_are_separate_from_eligibility_and_link_verified_action():
    body = '本科生可报名志愿活动，参加并签到后获得2小时志愿时长。'
    doc = bundle(content=body, segments=[], assets=[])
    benefit = dict(conditions=[benefit_condition()], groups=[group('earn', ('condition', 'attendance'))],
                   root_group_id='earn', complete=True)
    fields = [field_check(), field_check('benefit_conditions.conditions', 'attendance', refs=['benefit']),
              field_check('benefit_conditions.groups', 'earn', refs=['benefit']),
              field_check('benefit_claims', 'volunteer-hours', refs=['benefit'])]
    facts = candidates(doc, actions=[action(kind='practice')], benefit_claims=[benefit_claim()],
                       benefit_conditions=benefit, evidence_refs=[evidence(doc), evidence(doc, 'benefit')])
    result = verify(doc, facts, *fields)
    assert result.category == 'daily'
    assert result.requirements.conditions == ()
    assert result.benefit_conditions.conditions[0].kind == 'attendance'
    assert result.benefit_claims[0].amount == 2
    assert verify(doc, facts, *fields[1:]).benefit_claims == ()
    contradicted = field_check('benefit_conditions.conditions', 'attendance', refs=['benefit'],
                               semantic_status='contradicted', counter_refs=['benefit'])
    assert verify(doc, facts, fields[0], contradicted, *fields[2:]).benefit_claims == ()
    cyclic = benefit | {'groups': [group('earn', ('group', 'earn'), ('condition', 'attendance'))]}
    changed = candidates(doc, actions=[action(kind='practice')], benefit_claims=[benefit_claim()],
                         benefit_conditions=cyclic, evidence_refs=[evidence(doc), evidence(doc, 'benefit')])
    assert verify(doc, changed, *fields).benefit_claims == ()


def test_benefit_conditions_cannot_supply_a_claim_for_a_different_action():
    doc = bundle()
    benefit = dict(conditions=[benefit_condition(target_id='other')], groups=[group('earn', ('condition', 'attendance'))],
                   root_group_id='earn', complete=True)
    facts = candidates(doc, actions=[action(kind='practice'), action('other', main=False, kind='practice')],
                       benefit_claims=[benefit_claim()], benefit_conditions=benefit,
                       evidence_refs=[evidence(doc), evidence(doc, 'benefit')])
    result = verify(doc, facts, field_check(), field_check(id='other'),
                    field_check('benefit_conditions.conditions', 'attendance', refs=['benefit']),
                    field_check('benefit_conditions.groups', 'earn', refs=['benefit']),
                    field_check('benefit_claims', 'volunteer-hours', refs=['benefit']))
    assert result.benefit_conditions.groups
    assert result.benefit_claims == ()


@pytest.mark.parametrize('changes', [
    {'actions': [action() | {'main': 1}]}, {'actions': [action() | {'text': '  '}]},
    {'actions': [action() | {'audience': 'fake'}]}, {'benefit_claims': [benefit_claim(amount=True)]},
    {'benefit_claims': [benefit_claim(amount=float('inf'))]}, {'evidence_refs': [
        dict(evidence_id='x', source_kind='notice', source_id='n', source_content_version='v', source_url=URL,
             locator=dict(page=True), quote='文')]}
])
def test_candidates_reject_extra_fields_blank_text_and_wrong_scalar_types(changes):
    doc = bundle()
    with pytest.raises(ValidationError):
        candidates(doc, **changes)


def test_grade_boolean_and_string_range_cannot_confirm_as_eligibility():
    doc = bundle()
    for invalid in (condition(field='grade', value=True), condition(field='school_id', operator='gte', value='csu')):
        req = requirement(group('g', ('condition', 'student')), conditions=[invalid])
        try:
            facts = candidates(doc, requirements=req)
        except ValidationError:
            continue
        result = verify(doc, facts, field_check(), field_check('requirements.conditions', 'student'),
                        field_check('requirements.groups', 'g'))
        assert result.requirements.conditions == ()
        assert result.requirements.complete is False


def test_candidate_schema_and_digest_are_stable_for_round_trip_and_ignore_key_order():
    from campus_backend.classification.facts import candidate_digest
    from campus_backend.classification.models import FactCandidates
    doc = bundle()
    facts = candidates(doc)
    ordered = dict(reversed(list(facts.model_dump(mode='json').items())))
    assert candidate_digest(FactCandidates.model_validate(ordered)) == candidate_digest(facts)
    assert candidate_digest(FactCandidates.model_validate_json(facts.model_dump_json())) == candidate_digest(facts)
    assert candidate_digest(candidates(doc, actions=[action(kind='competition')])) != candidate_digest(facts)
    assert 'evidence_refs' in FactCandidates.model_json_schema()['properties']


@pytest.mark.parametrize('missing', ['遗漏附件的报名期限', '遗漏获益须签到的条件'])
def test_independent_coverage_report_keeps_local_facts_but_blocks_completion(missing):
    from campus_backend.classification.facts import verify_candidates
    doc = bundle()
    facts = candidates(doc)
    checked = report(facts, field_check(), coverage_complete=False, missing_facts=[missing])
    result = verify_candidates(doc, facts, checked)
    assert result.category == 'financial_aid' and result.actions
    assert result.complete is False
    assert result.checks.missing_facts == (missing,)
    assert any(gap.reason_code == 'missing_fact' and gap.detail == missing for gap in result.gaps)
    with pytest.raises(ValueError):
        report(facts, field_check(), coverage_complete=True, missing_facts=[missing])


@pytest.mark.parametrize(('condition_fields', 'expected_gaps'), [
    ({}, {'incomplete_requirements', 'incomplete_benefit_conditions'}),
    ({'requirements': {'complete': False}, 'benefit_conditions': {'complete': False}},
     {'incomplete_requirements', 'incomplete_benefit_conditions'}),
    ({'requirements': {'complete': True}}, {'incomplete_benefit_conditions'}),
    ({'benefit_conditions': {'complete': True}}, {'incomplete_requirements'}),
])
def test_unresolved_empty_condition_collections_block_completion(condition_fields, expected_gaps):
    doc = bundle()
    facts = window_facts(doc, time_window(), **condition_fields)
    result = verify(doc, facts, field_check(), window_check())
    assert result.complete is False
    assert result.category == 'financial_aid' and result.actions and result.time_windows
    assert {gap.reason_code for gap in result.gaps} == expected_gaps


@pytest.mark.parametrize(('body_status', 'coverage_complete', 'expected'), [
    ('complete', True, True),
    ('partial', True, False),
    ('complete', False, False),
])
def test_empty_condition_collections_can_confirm_absence_only_with_complete_input_and_review(
    body_status, coverage_complete, expected,
):
    from campus_backend.classification.facts import verify_candidates
    doc = bundle(body_status=body_status)
    facts = window_facts(doc, time_window(), requirements={'complete': True}, benefit_conditions={'complete': True})
    checked = report(facts, field_check(), window_check(), coverage_complete=coverage_complete)
    result = verify_candidates(doc, facts, checked)
    assert result.requirements.complete is expected
    assert result.benefit_conditions.complete is expected
    assert result.complete is expected
    assert result.actions and result.time_windows


def test_body_html_asset_hash_changes_do_not_invalidate_same_extracted_text():
    original_html = {'asset_id': HASH, 'sha256': HASH, 'role': 'original_html', 'status': 'complete'}
    raw_segment = BASIC['segments'][0] | {'asset_id': HASH}
    first = bundle(body_asset_id=HASH, segments=[raw_segment, BASIC['segments'][1]],
                   assets=[original_html, BASIC['assets'][0]])
    changed_hash = 'b' * 64
    second = bundle(body_asset_id=changed_hash, segments=[raw_segment | {'asset_id': changed_hash}, BASIC['segments'][1]],
                    assets=[original_html | {'asset_id': changed_hash, 'sha256': changed_hash}, BASIC['assets'][0]])
    assert first.input_fingerprint == second.input_fingerprint
    assert first.segments[1].asset_id is None and first.segments[1].asset_hash is None
    assert [asset.asset_id for asset in first.assets] == ['attachment']


@pytest.mark.parametrize('status', ['failed', 'title_only', 'skipped'])
def test_unusable_extraction_status_cannot_expose_residual_body(status):
    from campus_backend.documents.facts_input import build_document_bundle
    doc = build_document_bundle(artifact() | {'status': status})
    assert [segment.text for segment in doc.segments] == [TITLE]


def test_manifest_asset_without_text_is_an_input_gap():
    doc = bundle(content=BODY, segments=[BASIC['segments'][0]])
    assert doc.body_status == 'partial'
    assert 'unread_asset' in doc.gaps


def test_complete_window_can_apply_to_a_common_group_across_tracks():
    doc = bundle()
    req = requirement(group('g', ('group', 'track-a'), ('group', 'track-b')),
                      group('track-a', ('condition', 'student'), track_id='a'),
                      group('track-b', ('condition', 'student'), track_id='b'))
    facts = window_facts(doc, time_window(audience_group_id='g'), requirements=req)
    result = verify(doc, facts, field_check(), field_check('requirements.conditions', 'student'), window_check(),
                    *(field_check('requirements.groups', id) for id in ('g', 'track-a', 'track-b')))
    assert result.requirements.complete
    assert len(result.time_windows) == 1


def test_date_and_attachment_match_a_nonempty_checked_action_and_condition():
    doc = bundle()
    facts = window_facts(doc, time_window(), actions=[action(evidence_ids=[])])
    result = verify(doc, facts, field_check(), window_check())
    assert result.actions == () and result.time_windows == ()
    assert result.category == 'unknown'


def test_unsafe_bundle_cannot_claim_title_only_and_include_a_body():
    from campus_backend.documents.models import DocumentBundle
    doc = bundle()
    with pytest.raises(ValidationError):
        DocumentBundle.model_validate(doc.model_dump() | {'body_status': 'title_only'})


def test_invalid_raw_reference_cannot_relabel_another_notices_text():
    from campus_backend.documents.facts_input import build_document_bundle
    original = artifact()
    wrong = {'stage': 'raw', 'notice_id': 'different-notice', 'content_version': 'v1', 'run_id': 'earlier'}
    with pytest.raises(ValueError):
        build_document_bundle(original | {'input_refs': [wrong]})


def test_scholarship_application_is_main_even_when_title_and_evidence_mention_competition():
    doc = bundle(title='奖学金申请及竞赛获奖证明提交')
    facts = candidates(doc, actions=[action(), action('competition-background', kind='competition', main=False)],
                       evidence_refs=[evidence(doc, segment=doc.segments[0])])
    result = verify(doc, facts, field_check(), field_check(id='competition-background'))
    assert result.category == 'financial_aid'


def test_date_only_evidence_does_not_support_a_precise_midnight_deadline():
    doc = bundle()
    proposed = time_window(end={'precision': 'datetime', 'value': '2026-11-15T00:00:00+08:00'})
    result = verify(doc, window_facts(doc, proposed), field_check(), window_check())
    assert result.time_windows == ()
    assert any(gap.reason_code == 'missing_window_clock_evidence' for gap in result.gaps)


def test_explicit_clock_time_keeps_the_reviewed_offset():
    text = '申报截至2026年11月15日18:30（北京时间）。'
    doc = bundle(segments=[BASIC['segments'][0], BASIC['segments'][1] | {'text': text}], content=BODY + '\n\n' + text)
    proposed = time_window(end={'precision': 'datetime', 'value': '2026-11-15T18:30:00+08:00'}, raw_text=text)
    result = verify(doc, window_facts(doc, proposed), field_check(), window_check())
    assert result.time_windows[0].end.value == '2026-11-15T18:30:00+08:00'


def test_benefit_claim_requires_condition_target_link_even_with_a_checked_target_description():
    doc = bundle()
    benefit = dict(conditions=[benefit_condition(target_id=None)], groups=[group('earn', ('condition', 'attendance'))],
                   root_group_id='earn', complete=True)
    facts = candidates(doc, actions=[action(kind='practice')], benefit_claims=[benefit_claim()],
                       benefit_conditions=benefit, evidence_refs=[evidence(doc), evidence(doc, 'benefit')])
    result = verify(doc, facts, field_check(),
                    field_check('benefit_conditions.conditions', 'attendance', refs=['benefit']),
                    field_check('benefit_conditions.groups', 'earn', refs=['benefit']),
                    field_check('benefit_claims', 'volunteer-hours', refs=['benefit']))
    assert result.benefit_conditions.conditions
    assert result.benefit_claims == ()


def test_same_quote_cannot_confirm_opposite_award_and_participation_meanings():
    text = '参与不计学分，获得赛事奖项后方可申请学分认定。'
    doc = bundle(content=text, segments=[], assets=[])
    part = benefit_condition(id='participation', kind='participation', text='参与即可')
    award = benefit_condition(id='award', kind='award', value='competition-award', text='获得赛事奖项')
    benefit = dict(conditions=[part, award], groups=[group('earn', ('condition', 'award'))],
                   root_group_id='earn', complete=False)
    facts = candidates(doc, actions=[action(kind='competition')], benefit_conditions=benefit,
                       evidence_refs=[evidence(doc), evidence(doc, 'benefit')])
    result = verify(doc, facts, field_check(),
                    field_check('benefit_conditions.conditions', 'participation', refs=['benefit'],
                                semantic_status='contradicted', counter_refs=['benefit']),
                    field_check('benefit_conditions.conditions', 'award', refs=['benefit']),
                    field_check('benefit_conditions.groups', 'earn', refs=['benefit']))
    assert [condition.id for condition in result.benefit_conditions.conditions] == ['award']
    assert any(gap.candidate_id == 'participation' and gap.reason_code == 'semantic_contradicted' for gap in result.gaps)


def test_primary_pdf_role_is_bound_to_verified_asset_and_fingerprint():
    from campus_backend.classification.rule_baseline import analyze_rules

    text = '本比赛面向全校学生，欢迎报名。'
    supplemental = '研究生专项附件：仅面向研究生。'
    assets = [
        {'asset_id': 'primary', 'sha256': 'b' * 64, 'status': 'complete', 'role': 'original_pdf'},
        {'asset_id': 'supplement', 'sha256': 'c' * 64, 'status': 'complete', 'role': 'attachment'},
    ]
    segments = [
        {'asset_id': asset_id, 'page': 1, 'location': 'page:1', 'method': 'native', 'text': value}
        for asset_id, value in [('primary', text), ('supplement', supplemental)]
    ]
    opts = dict(title='创新大赛报名通知', content=text + '\n\n' + supplemental, segments=segments)
    primary = bundle(**opts, assets=assets)
    legacy = bundle(**opts, assets=[{k: v for k, v in entry.items() if k != 'role'} for entry in assets])
    assert primary.primary_asset_ids == ('primary',)
    assert not legacy.primary_asset_ids
    assert primary.input_fingerprint != legacy.input_fingerprint
    assert analyze_rules(primary).category == 'research_innovation'
    assert not any(g.code == 'body_incomplete' for g in analyze_rules(primary).gaps)
    assert analyze_rules(legacy).category == 'research_innovation'
    assert any(g.code == 'body_incomplete' for g in analyze_rules(legacy).gaps)
    invalid = bundle(**opts, assets=[assets[0] | {'asset_id': 'wrong'}, assets[1]])
    assert not invalid.primary_asset_ids
    assert 'unverified_primary_pdf' in invalid.gaps
    with pytest.raises(ValidationError):
        type(primary).model_validate(primary.model_dump() | {'primary_asset_ids': ['wrong']})


def test_table_columns_and_explicit_merge_provenance_reach_public_bundle():
    text='\t特殊考生\t4\t405'
    segment=dict(text=text,location='sheet:安排/row:3',page=None,asset_id='attachment',method='text',
                 table_merges=['B2:B3'])
    doc=bundle(content=text,segments=[segment])
    row=doc.segments[1]
    assert row.text==text
    assert row.table_merges==('B2:B3',)
    assert 'table_merges' not in doc.segments[0].model_dump(mode='json')
    changed=dict(segment,table_merges=['B1:B3'])
    assert bundle(content=text,segments=[changed]).input_fingerprint!=doc.input_fingerprint


def test_invalid_merge_metadata_becomes_gap_instead_of_silent_trust():
    text='\t特殊考生\t4\t405'
    segment=dict(text=text,location='sheet:安排/row:3',page=None,asset_id='attachment',method='text',
                 table_merges=['B7:B8'])
    doc=bundle(content=text,segments=[segment])
    assert 'unverified_table_merge' in doc.gaps
    assert doc.segments[1].table_merges==()
