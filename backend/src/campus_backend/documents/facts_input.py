"""Adapt the existing document artifact to a public-only S2 input."""

import re
from collections import Counter
from datetime import date, datetime

from campus_backend.core.artifacts import validate_artifact

from .models import DocumentAsset, DocumentBundle, DocumentSegment, stable_digest, validated_table_merges


_HASH = re.compile(r'[a-f0-9]{64}')
_LOCATION = re.compile(r'(?:file|image|html:body|page:[1-9]\d*|paragraph:\d+|table:\d+/row:\d+|sheet:.+/row:\d+|embedded:.+)')
_BODY_STATES = {
    'complete': 'full', 'full': 'full', 'partial': 'partial', 'title_only': 'title_only',
    'unavailable': 'unavailable', 'restricted': 'unavailable', 'login_required': 'unavailable',
}
_ASSET_READY = ('downloaded', 'complete', 'available', 'success', None)
_SEGMENT_METHODS = ('text', 'native', 'ocr', 'html_text', None)
_MAX_SEGMENTS = 16_384


def _text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _publication_date(value, gaps: set[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                date.fromisoformat(value)
                return value
            if re.match(r'\d{4}-\d{2}-\d{2}T', value) and datetime.fromisoformat(value).utcoffset() is not None:
                return value
        except ValueError:
            pass
    gaps.add('invalid_publication_date')
    return None


def _assets(raw, body_asset_id, gaps: set[str]) -> dict[str, DocumentAsset]:
    if not isinstance(raw, list):
        gaps.add('unknown_asset_manifest')
        return {}

    assets = {}
    conflicts = set()
    for item in raw:
        if not isinstance(item, dict) or not (asset_id := _text(item.get('asset_id'))):
            gaps.add('unavailable_asset')
            continue
        if item.get('status') not in _ASSET_READY:
            gaps.add('unavailable_asset')
            continue
        if asset_id == body_asset_id:
            continue
        asset_hash = item.get('sha256')
        if not isinstance(asset_hash, str) or not _HASH.fullmatch(asset_hash):
            asset_hash = None
            gaps.add('missing_asset_hash')
        if asset_id in assets and assets[asset_id].asset_hash != asset_hash:
            conflicts.add(asset_id)
        assets[asset_id] = DocumentAsset(asset_id=asset_id, asset_hash=asset_hash)
    if conflicts:
        gaps.add('conflicting_asset_manifest')
        for asset_id in conflicts:
            del assets[asset_id]
    return assets


def _fragments(payload: dict, assets: dict[str, DocumentAsset], gaps: set[str]):
    raw_segments = payload.get('segments', [])
    content = payload.get('content')
    if not isinstance(raw_segments, list):
        gaps.add('unknown_segment_format')
        return
    if not raw_segments and _text(content):
        if payload.get('assets'):
            gaps.add('unlocated_body_or_attachment')
            return
        yield dict(kind='body', text=content, location='html:body')
        return

    if content is not None and (not isinstance(content, str) or content != '\n\n'.join(
        segment['text'] for segment in raw_segments if isinstance(segment, dict) and _text(segment.get('text'))
    )):
        gaps.add('content_segment_mismatch')

    body_asset_id = payload.get('body_asset_id')
    for segment in raw_segments:
        if not isinstance(segment, dict):
            gaps.add('unknown_segment_format')
            continue
        text = _text(segment.get('text'))
        location = _text(segment.get('location'))
        page = segment.get('page')
        asset_id = segment.get('asset_id')
        if (text is None or location is None or not _LOCATION.fullmatch(location)
                or (page is not None and (type(page) is not int or page < 1))
                or (asset_id is not None and _text(asset_id) is None)
                or (location.startswith('page:') and (page is None or location != f'page:{page}'))):
            gaps.add('unknown_segment_format')
            continue
        method = segment.get('method')
        if method not in _SEGMENT_METHODS:
            gaps.add('unknown_segment_method')
            continue
        if location == 'html:body' and (asset_id is None or asset_id == body_asset_id) and page is None:
            yield dict(kind='body', text=text, location=location, method=method)
        elif asset_id is not None and asset_id != body_asset_id:
            asset = assets.get(asset_id)
            if asset is None or asset.asset_hash is None:
                gaps.add('unverified_segment_asset')
            extra = {}
            if 'table_merges' in segment:
                try:
                    merges = validated_table_merges(segment['table_merges'], location)
                    if merges:
                        extra['table_merges'] = merges
                except ValueError:
                    gaps.add('unverified_table_merge')
            yield dict(kind='attachment', text=text, location=location, method=method,
                       asset_id=asset_id, asset_hash=asset.asset_hash if asset else None, page=page, **extra)
        else:
            gaps.add('unknown_segment_format')


def _segments(title: str, payload: dict, assets: dict[str, DocumentAsset], gaps: set[str]):
    segments = [DocumentSegment(id='title', kind='title', location='title', text=title)]
    occurrences: Counter[str] = Counter()
    for fragment in _fragments(payload, assets, gaps):
        # HTML extraction emits one public text paragraph per line. Preserve attachment pages and rows.
        parts = fragment['text'].splitlines() if fragment['kind'] == 'body' else (fragment['text'],)
        for part in parts:
            if not part.strip():
                continue
            if len(segments) == _MAX_SEGMENTS:
                gaps.add('segment_limit')
                return tuple(segments)
            values = fragment | {'text': part}
            fingerprint = stable_digest(values)
            occurrences[fingerprint] += 1
            segment_id = f'{fragment["kind"]}:{fingerprint}:{occurrences[fingerprint]}'
            segments.append(DocumentSegment(id=segment_id, **values))
    return tuple(segments)



def _primary_pdf_ids(raw_assets, segments: tuple[DocumentSegment, ...], gaps: set[str]) -> tuple[str, ...]:
    if not isinstance(raw_assets, list):
        return ()
    located_assets = {(seg.asset_id, seg.asset_hash) for seg in segments
                      if seg.kind == 'attachment' and seg.page is not None and seg.asset_hash}
    primary = set()
    for item in raw_assets:
        if not isinstance(item, dict) or item.get('role') != 'original_pdf':
            continue
        asset_id = _text(item.get('asset_id'))
        asset_hash = _text(item.get('sha256'))
        if ((asset_id, asset_hash) in located_assets and item.get('status') in _ASSET_READY):
            primary.add(asset_id)
        else:
            gaps.add('unverified_primary_pdf')
    return tuple(sorted(primary))


def build_document_bundle(document: dict) -> DocumentBundle:
    """Read only explicitly public text and metadata from a v1 document envelope."""
    try:
        validate_artifact(document, expected_stage='document')
    except TypeError as exc:
        raise ValueError('Invalid document envelope') from exc
    for ref in document['input_refs']:
        if (not isinstance(ref, dict) or ref.get('stage') != 'raw'
                or ref.get('notice_id') != document['notice_id']
                or ref.get('content_version') != document['content_version']
                or not _text(ref.get('run_id'))):
            raise ValueError('Invalid raw input reference for document')
    payload = document['payload']
    title = _text(payload.get('title'))
    if title is None:
        raise ValueError('document title must be a nonblank string')

    gaps: set[str] = set()
    status = payload.get('body_status')
    body_status = _BODY_STATES.get(status) if isinstance(status, str) else None
    if body_status is None:
        body_status = 'unavailable'
        gaps.add('unknown_body_status')
    elif document['status'] in ('failed', 'skipped', 'title_only') and body_status != 'unavailable':
        body_status = 'title_only'

    # Source error details can contain internal paths or response data. Keep only a fixed gap code.
    if document['errors'] or document['status'] != 'complete':
        gaps.add('document_extraction_incomplete')

    primary_asset_ids = ()
    if body_status in ('title_only', 'unavailable'):
        assets = {}
        segments = (DocumentSegment(id='title', kind='title', location='title', text=title),)
    else:
        assets = _assets(payload.get('assets', []), payload.get('body_asset_id'), gaps)
        segments = _segments(title, payload, assets, gaps)
        primary_asset_ids = _primary_pdf_ids(payload.get('assets', []), segments, gaps)
        if assets.keys() - {segment.asset_id for segment in segments}:
            gaps.add('unread_asset')
        if len(segments) == 1:
            body_status = 'title_only'
            gaps.add('no_readable_body')

    published_at = _publication_date(payload.get('published_at'), gaps)
    if gaps and body_status == 'full':
        body_status = 'partial'
    if body_status != 'full':
        gaps.add('body_incomplete')

    values = dict(notice_id=document['notice_id'], title=title, source_url=payload.get('source_url'),
                  school_id=_text(payload.get('school_id')), source_id=_text(payload.get('source_id')),
                  source_name=_text(payload.get('source_name')), published_at=published_at, body_status=body_status,
                  segments=segments, assets=tuple(assets[key] for key in sorted(assets)), gaps=tuple(sorted(gaps)))
    if primary_asset_ids:
        values['primary_asset_ids'] = primary_asset_ids
    fingerprint_input = values | {'segments': [segment.model_dump(mode='json') for segment in segments],
                                  'assets': [asset.model_dump(mode='json') for asset in values['assets']]}
    return DocumentBundle(content_version=document['content_version'], input_fingerprint=stable_digest(fingerprint_input),
                          **values)
