"""Attachment identity resolves pointers without guessing from cohort wording."""
import pytest

from campus_backend.classification.product_labels import AbsoluteEndpoint, AudienceGroup, PendingEndpoint, ProductScope
from campus_backend.classification.rule_labels import RuleEvidence
from campus_backend.classification.simple_context import primary_view
from campus_backend.classification.simple_labels import SimpleDateLabel, SimpleDateValue
from campus_backend.classification.simple_rules import _resolve_schedule_pointers
from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.facts_input import build_document_bundle


TITLE = '2028年学生考试考场安排表'
OTHER_TITLE = '2028年学生培训日程表'


def document(*, listing=None, attachments=None, numbered=True, legacy=False, cohort=True, pointer_text=None):
    listing = listing if listing is not None else '附件：1.学习要求\n3.2028年学生考试\n考场安排表\n教务处\n2028年10月20日'
    attachments = attachments if attachments is not None else [('schedule', TITLE, True)]
    pointer = pointer_text or ('具体考试安排详见附件3。' if numbered else '具体考试安排详见附件。')
    main = '2028年学生考试通知\n' + pointer + '\n' + listing
    assets = [{'asset_id': 'main', 'sha256': 'a' * 64, 'status': 'complete'}]
    if not legacy:
        assets[0]['role'] = 'original_pdf'
    segments = [{'text': main, 'asset_id': 'main', 'page': 1, 'location': 'page:1', 'method': 'text'}]
    for index, (asset_id, title, readable) in enumerate(attachments, 1):
        digest = f'{index:064x}'
        assets.append({'asset_id': asset_id, 'sha256': digest, 'status': 'complete'})
        if readable:
            segments.extend([
                {'text': '\t'.join([title] * 3), 'asset_id': asset_id, 'page': None,
                 'location': 'sheet:日程/row:1', 'method': 'text'},
                {'text': '2028年11月8日09:00—10:00', 'asset_id': asset_id, 'page': None,
                 'location': 'sheet:日程/row:2', 'method': 'text'},
            ])
    artifact = make_artifact('document', 'generic-exam', 'v1', {
        'title': '2028年学生考试通知', 'source_url': 'https://example.edu/exam',
        'body_status': 'complete', 'assets': assets, 'segments': segments,
        'content': '\n\n'.join(s['text'] for s in segments),
    })
    bundle = build_document_bundle(artifact)
    primary = next(s for s in bundle.segments if s.asset_id == 'main')
    scope = ProductScope(audience_groups=(AudienceGroup(audience='2028级全日制本科生'),)) if cohort else ProductScope()
    dates = [SimpleDateLabel(code='event', scope=scope,
                            evidence=(RuleEvidence(segment_id=primary.id, quote=pointer),),
                            value=SimpleDateValue(start=PendingEndpoint(reason='unresolved'), state='unknown'))]
    for asset_id, _, readable in attachments:
        if readable:
            row = next(s for s in bundle.segments if s.asset_id == asset_id and s.location.endswith('row:2'))
            dates.append(SimpleDateLabel(code='event',
                scope=ProductScope(audience_groups=(AudienceGroup(college='工学院', class_name='2801班'),)),
                evidence=(RuleEvidence(segment_id=row.id, quote=row.text),),
                value=SimpleDateValue(start=AbsoluteEndpoint(date='2028-11-08', time='09:00'),
                                      end=AbsoluteEndpoint(date='2028-11-08', time='10:00'))))
    return bundle, dates, artifact


def unresolved(dates):
    return [d for d in dates if any(p and p.kind == 'pending' for p in (d.value.start, d.value.end))]


def test_number_and_exact_title_bind_wrapped_list_to_repeated_header_without_cohort_guessing():
    bundle, dates, _ = document(attachments=[('schedule', TITLE, True), ('other', OTHER_TITLE, True)])
    resolved = _resolve_schedule_pointers(primary_view(bundle), dates)
    assert not unresolved(resolved)
    assert len(resolved) == 2
    target = next(d for d in resolved if any(r.segment_id == dates[1].evidence[0].segment_id for r in d.evidence))
    assert target.value == dates[1].value
    assert target.scope == dates[1].scope
    assert any('详见附件3' in ref.quote for ref in target.evidence)
    assert any('3.2028年学生考试' in ref.quote for ref in target.evidence)
    header = next(s for s in bundle.segments if s.asset_id == 'schedule' and s.location.endswith('row:1'))
    assert header.id in {r.segment_id for r in target.evidence}
    other = next(d for d in resolved if d.evidence[0].segment_id == dates[2].evidence[0].segment_id)
    assert other.evidence == dates[2].evidence


def test_duplicate_titles_across_assets_keep_the_numbered_pointer_ambiguous():
    bundle, dates, _ = document(attachments=[('first', TITLE, True), ('second', TITLE, True)], cohort=False)
    assert len(unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))) == 1


def test_same_number_with_conflicting_titles_does_not_choose_a_matching_schedule():
    bundle, dates, _ = document(listing=f'附件：3.{TITLE}\n3.{OTHER_TITLE}', cohort=False)
    assert len(unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))) == 1


@pytest.mark.parametrize('attachments', [
    [('schedule', TITLE, False)],
    [('schedule', TITLE, False), ('other', OTHER_TITLE, True)],
    [('other', OTHER_TITLE, True)],
])
def test_unread_or_missing_numbered_target_cannot_be_replaced_by_another_schedule(attachments):
    bundle, dates, _ = document(attachments=attachments, cohort=False)
    assert len(unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))) == 1


def test_a_bare_number_outside_an_attachment_list_does_not_establish_identity():
    bundle, dates, _ = document(listing=f'三、工作安排\n3.{TITLE}', cohort=False)
    assert len(unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))) == 1


def test_unnumbered_pointer_keeps_the_existing_conservative_resolution():
    bundle, dates, _ = document(numbered=False, listing='请按要求参加考试。', cohort=False)
    assert not unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))


@pytest.mark.parametrize('legacy', [True, False])
def test_binding_preserves_existing_bundle_fields_and_input_fingerprint(legacy):
    bundle, dates, artifact = document(legacy=legacy)
    before = bundle.model_dump(mode='json')
    fingerprint = bundle.input_fingerprint
    assert fingerprint == ('6c8fca7181e1b4032030d5ee59636bd843cf7be26bef0cb355710e143905298f' if legacy
                           else '820d870a2299203e804524d7902bdcf32bdbc03aab3ddda3250e7543472a313d')
    assert not unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))
    assert bundle.model_dump(mode='json') == before
    assert bundle.input_fingerprint == fingerprint == build_document_bundle(artifact).input_fingerprint


def test_chinese_attachment_number_is_explicit_and_matches_the_list_number():
    bundle, dates, _ = document(listing=f'附件：三、{TITLE}', pointer_text='具体考试安排详见附件三。')
    assert not unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))


def test_two_explicit_numbers_are_not_replaced_by_one_unique_schedule():
    bundle, dates, _ = document(cohort=False, pointer_text='具体考试安排详见附件3、4。')
    assert len(unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))) == 1


def test_audience_evidence_about_another_appendix_does_not_change_schedule_pointer():
    bundle, dates, _ = document(pointer_text='考试安排详见附件3。未通过的学生名单详见附件1。')
    main_ref = dates[0].evidence[0]
    dates[0] = dates[0].model_copy(update={'evidence': (
        RuleEvidence(segment_id=main_ref.segment_id, quote='考试安排详见附件3'),
        RuleEvidence(segment_id=main_ref.segment_id, quote='未通过的学生名单详见附件1'),
    )})
    assert not unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))


def test_omitted_header_year_requires_identical_remaining_title_and_explicit_content_year():
    bundle, dates, _ = document(attachments=[('schedule', TITLE.removeprefix('2028年'), True)])
    assert not unresolved(_resolve_schedule_pointers(primary_view(bundle), dates))
    changed = tuple(s.model_copy(update={'text': s.text.replace('2028年11月8日', '2027年11月8日')})
                    for s in bundle.segments)
    assert unresolved(_resolve_schedule_pointers(primary_view(bundle.model_copy(update={'segments': changed})), dates))


def test_missing_title_year_without_explicit_content_year_remains_unresolved():
    bundle, dates, _ = document(attachments=[('schedule', TITLE.removeprefix('2028年'), True)])
    changed = tuple(s.model_copy(update={'text': s.text.replace('2028年11月8日', '11月8日')})
                    for s in bundle.segments)
    assert unresolved(_resolve_schedule_pointers(primary_view(bundle.model_copy(update={'segments': changed})), dates))
