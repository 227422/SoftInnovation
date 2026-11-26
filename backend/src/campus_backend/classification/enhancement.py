"""Versioned opt-in candidate port. No model SDKs or network implementation."""
from copy import deepcopy
import math
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from typing import Protocol

from campus_backend.core.artifacts import make_artifact, validate_artifact

# Hung adapters can occupy at most two daemon workers, never grow an unbounded
# thread pool, and never block rule-only analysis or process shutdown.
_SLOTS = BoundedSemaphore(2)
_ALLOWED_FIELDS = {'category', 'notice_type', 'audience_hint', 'summary'}
_ENVELOPE_FIELDS = {'schema_version', 'stage', 'notice_id', 'content_version', 'run_id',
                    'created_at', 'producer', 'status', 'errors', 'input_refs', 'payload'}


class ClassificationEnhancer(Protocol):
    """Optional adapter: enforce your own I/O limits and return an envelope.

    ``timeout_seconds`` defaults to 0.25 and is capped at 5 seconds by the caller.
    The request contains only public document/rule analysis, never a profile.
    """
    timeout_seconds: float

    def enhance(self, request: dict) -> dict: ...


def _validate(value, document):
    validate_artifact(value, expected_stage='enhancement')
    if value['notice_id'] != document['notice_id'] or value['content_version'] != document['content_version']:
        raise LookupError('version mismatch')
    if set(value) - _ENVELOPE_FIELDS or set(value['payload']) != {'candidates'}:
        raise ValueError('Unexpected enhancement fields')
    if value['status'] != 'complete' or value['errors']:
        raise ValueError('Incomplete enhancement')
    candidates = value['payload']['candidates']
    if not isinstance(candidates, list) or len(candidates) > 32:
        raise ValueError('Invalid candidates')
    payload = document['payload']
    title_only = payload.get('body_status') == 'title_only' or not payload.get('content', '').strip()
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) - {'field', 'value', 'evidence', 'confidence'}:
            raise ValueError('Invalid candidate fields')
        if candidate.get('field') not in _ALLOWED_FIELDS:
            raise ValueError('Official facts are not enhancement candidate fields')
        if not isinstance(candidate.get('value'), str) or not 1 <= len(candidate['value']) <= 2048:
            raise ValueError('Invalid candidate value')
        if 'confidence' in candidate and (type(candidate['confidence']) not in (int, float)
                or not math.isfinite(candidate['confidence']) or not 0 <= candidate['confidence'] <= 1):
            raise ValueError('Invalid confidence')
        citations = candidate.get('evidence')
        if not isinstance(citations, list) or not 1 <= len(citations) <= 16:
            raise ValueError('Missing evidence')
        for citation in citations:
            if not isinstance(citation, dict) or set(citation) - {'source', 'quote', 'segment_index'}:
                raise ValueError('Invalid evidence')
            quote = citation.get('quote')
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 4096:
                raise ValueError('Invalid evidence quote')
            source = citation.get('source')
            if source == 'title':
                text = payload.get('title', '')
            elif source == 'content' and not title_only:
                text = payload.get('content', '')
            elif source == 'segment' and not title_only:
                index = citation.get('segment_index')
                segments = payload.get('segments', [])
                if type(index) is not int or not 0 <= index < len(segments):
                    raise ValueError('Invalid segment reference')
                text = segments[index].get('text', '')
            else:
                raise ValueError('Evidence source is unavailable')
            if quote not in text:
                raise ValueError('Evidence quote not in official text')
    return deepcopy(value)


def _fallback(code):
    return {'status': 'fallback', 'candidates': [], 'errors': [{'code': code}]}


def apply_enhancement(document, analysis, *, enhancer=None):
    """Validate optional suggestions separately and fall back on all failures."""
    if enhancer is None:
        return {'status': 'disabled', 'candidates': [], 'errors': []}
    try:
        timeout = float(getattr(enhancer, 'timeout_seconds', 0.25))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Invalid adapter timeout')
        timeout = min(timeout, 5.0)
        method = enhancer.enhance
    except Exception:
        return _fallback('enhancement_invalid')
    if not _SLOTS.acquire(blocking=False):
        return _fallback('enhancement_busy')
    request = make_artifact('enhancement', document['notice_id'], document['content_version'],
                    {'document': deepcopy(document), 'analysis': deepcopy(analysis)},
                    producer={'name': 'campus-classification-request', 'version': '1.0'},
                    input_refs=[{'stage': 'document', 'notice_id': document['notice_id'],
                                 'content_version': document['content_version'], 'run_id': document['run_id']}])
    queue = Queue(maxsize=1)

    def run():
        try:
            value = method(request)
            # Validate in the worker and copy before returning: a provider cannot
            # retain and mutate the public result after it has been accepted.
            try:
                queue.put(('success', _validate(value, document)))
            except LookupError:
                queue.put(('error', 'enhancement_version_mismatch'))
            except Exception:
                queue.put(('error', 'enhancement_invalid'))
        except TimeoutError:
            queue.put(('error', 'enhancement_timeout'))
        except Exception:
            queue.put(('error', 'enhancement_failed'))
        finally:
            _SLOTS.release()

    try:
        Thread(target=run, daemon=True, name='classification-enhancer').start()
    except Exception:
        _SLOTS.release()
        return _fallback('enhancement_failed')
    try:
        status, value = queue.get(timeout=timeout)
    except Empty:
        return _fallback('enhancement_timeout')
    if status == 'error':
        return _fallback(value)
    return {'status': 'accepted', 'candidates': deepcopy(value['payload']['candidates']),
            'artifact': value, 'errors': []}
