"""Compose collector analysis and bind rule evidence to its document snapshot."""

from campus_backend.documents.facts_input import build_document_bundle
from campus_backend.documents.models import stable_digest

from .product_labels import ProductRuleResult
from .simple_labels import SimpleRuleResult, RULES_VERSION
from .simple_rules import analyze_simple_rules
from .rule_labels import RuleBaselineResult
from .service import analyze_document


_PRODUCER = {'name': 'campus-classification-collected', 'version': '3.0'}
_RESULT_TYPES = {
    's2-rule-baseline/1': RuleBaselineResult,
    's2-rule-baseline/2': ProductRuleResult,
    's2-rule-baseline/3': SimpleRuleResult,
}


def _reference(stage):
    return {key: stage[key] for key in ('stage', 'notice_id', 'content_version', 'run_id')}


def analyze_collected_document(document: dict, *, now=None) -> dict:
    """Keep the shared legacy projection and attach the versioned S2 result."""
    bundle = build_document_bundle(document)
    rules = analyze_simple_rules(bundle).model_dump(mode='json')
    analysis = analyze_document(document, now=now)
    analysis['producer'] = _PRODUCER.copy()
    analysis['payload'].update(rule_baseline=rules, facts_version=stable_digest(rules))
    # The envelope marks execution of the shared stage. Rule coverage is in
    # rule_baseline.complete and gaps, independently of the legacy evaluation.
    return analysis


def validate_collected_rule_facts(
    document: dict | None, analysis: dict, *, require_current_method: bool = False,
) -> RuleBaselineResult | ProductRuleResult | SimpleRuleResult | None:
    """Validate the typed extension against prevalidated stage envelopes."""
    payload = analysis['payload']
    extension_keys = {'rule_baseline', 'facts_version'} & payload.keys()
    if not extension_keys and analysis['producer']['name'] != _PRODUCER['name']:
        return None
    if document is None or len(extension_keys) != 2:
        raise ValueError('Missing rule facts or their source document')

    if analysis['input_refs'] != [_reference(document)]:
        raise ValueError('Rule facts must reference this document run')
    # Historical results retain their own defaults and exact digest projection.
    # Never reinterpret historical detailed labels as current simplified tags.
    value = payload['rule_baseline']
    result_type = _RESULT_TYPES.get(value.get('schema_version'))
    if result_type is None:
        raise ValueError('Unsupported rule facts schema')
    result = result_type.model_validate(value)
    bundle = build_document_bundle(document)
    expected = (bundle.notice_id, bundle.content_version, bundle.input_fingerprint)
    if (result.notice_id, result.content_version, result.input_fingerprint) != expected:
        raise ValueError('Rule facts do not match the document input')
    if require_current_method and (result.rules_version != RULES_VERSION or not isinstance(result, SimpleRuleResult)):
        raise ValueError('Rule facts were generated with a different rules version')
    if payload['facts_version'] != stable_digest(result.model_dump(mode='json')):
        raise ValueError('Rule facts version digest does not match the result')

    segments = {segment.id: segment.text for segment in bundle.segments}
    for item in (*result.labels, *result.gaps):
        for ref in item.evidence:
            if ref.segment_id not in segments or ref.quote not in segments[ref.segment_id]:
                raise ValueError('Rule evidence does not occur in its referenced segment')
    return result


def validate_collected_raw_reference(document: dict, raw: dict) -> None:
    """Check the source run whenever the document carries raw provenance."""
    if document['input_refs'] and document['input_refs'] != [_reference(raw)]:
        raise ValueError('Rule document does not reference the stored raw run')
