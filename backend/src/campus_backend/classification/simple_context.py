"""Evidence-preserving main-document context for the v3 rules only."""
import re

from .product_context import reading_text
from .rule_labels import RuleEvidence


def _title_key(text):
    return re.sub(r'[\W_]+', '', reading_text(text))


def primary_view(document):
    """A PDF-only article may carry its main notice as an ordinary attachment.

    Promote only a unique, hash-verified first page starting with the article
    title. No source data or input fingerprint is rewritten; this is a view
    used by the current method. A populated HTML body keeps its own priority.
    """
    if document.primary_asset_ids or any(s.kind == 'body' for s in document.segments):
        return document
    verified = {(a.asset_id, a.asset_hash) for a in document.assets if a.asset_hash}
    key = _title_key(document.title)
    candidates = set()
    for segment in document.segments:
        if (segment.kind == 'attachment' and segment.page == 1
                and (segment.asset_id, segment.asset_hash) in verified
                and len(key) >= 8 and _title_key(segment.text[:250]).startswith(key)):
            candidates.add(segment.asset_id)
    if len(candidates) != 1:
        return document
    return document.model_copy(update={'primary_asset_ids': tuple(candidates)})


def calendar_context(document):
    """Use an explicit notice year, never today's year or a cohort's year."""
    title = reading_text(document.title)
    title = re.sub(r'(?:依据|根据|按照|参照)《[^》]*》', '', title)
    if re.search(r'\d{4}\s*[-—–至/]\s*\d{4}|\d{4}学年', title):
        return None, ()
    years = set(re.findall(r'(?<!\d)(\d{4})年(?!级|届|学年)', title))
    if len(years) == 1:
        return next(iter(years)), (RuleEvidence(segment_id='title', quote=document.title),)
    if years:
        return None, ()
    # Publication and signing years cannot disambiguate a January deadline
    # published in December. They are provenance, not an event-year anchor.
    return None, ()
