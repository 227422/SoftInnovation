"""Deterministic checks for independently reviewed public notice facts."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from graphlib import CycleError, TopologicalSorter

from campus_backend.documents.models import DocumentBundle, EvidenceRef, stable_digest

from .models import (
    BenefitClaim, BenefitConditionCandidate, BenefitConditions, Condition, FactAction, FactCandidates,
    FactGap, FactGroup, FieldPath, Requirements, TemporalValue, TimeWindowFact, VerificationReport,
    VerifiedFacts,
)


RULES_VERSION = 's2-facts-1'
_FINANCIAL = {'scholarship_application', 'aid', 'award_selection'}
_RESEARCH = {'competition', 'research', 'innovation'}
_DAILY = {'academic', 'activity', 'practice', 'career', 'exchange'}
_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_ZONED_DATETIME = re.compile(
    r'[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?'
    r'(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])'
)
_YEAR = re.compile(r'(?<![0-9])([0-9]{4})(?=\s*(?:年|[./-][0-9]{1,2}(?:[./-][0-9]|月)))')
_CLOCK = re.compile(r'[0-9]{1,2}\s*[:：]\s*[0-9]{2}|[0-9零〇一二两三四五六七八九十]{1,3}\s*[点點时時]')


def candidate_digest(candidates: FactCandidates) -> str:
    """Bind review to the exact validated candidate snapshot."""
    return stable_digest(candidates.model_dump(mode='json'))


def candidate_fields(candidates: FactCandidates) -> tuple[tuple[FieldPath, str], ...]:
    """Return the address of each field requiring an independent check."""
    collections = {
        'actions': candidates.actions,
        'requirements.conditions': candidates.requirements.conditions,
        'requirements.groups': candidates.requirements.groups,
        'time_windows': candidates.time_windows,
        'benefit_conditions.conditions': candidates.benefit_conditions.conditions,
        'benefit_conditions.groups': candidates.benefit_conditions.groups,
        'benefit_claims': candidates.benefit_claims,
    }
    return tuple((path, item.id) for path, values in collections.items() for item in values)


def _identity(value):
    return value.notice_id, value.content_version, value.input_fingerprint


def _check_bindings(document, candidates, checks, digest):
    if _identity(document) != _identity(candidates):
        raise ValueError('candidate notice, version or input fingerprint does not match document')
    if _identity(document) != _identity(checks) or checks.candidate_digest != digest:
        raise ValueError('verification report does not match the input and candidate snapshot')
    fields = candidate_fields(candidates)
    field_set = set(fields)
    if len(field_set) != len(fields):
        raise ValueError('duplicate candidate field ID')
    ref_ids = {ref.evidence_id for ref in candidates.evidence_refs}
    if len(ref_ids) != len(candidates.evidence_refs):
        raise ValueError('duplicate candidate evidence ID')
    checked = {}
    for check in checks.checks:
        key = check.field_path, check.candidate_id
        if key not in field_set or key in checked:
            raise ValueError(f'unexpected or duplicate verification check: {key}')
        if not ref_ids.issuperset(check.support_refs) or not ref_ids.issuperset(check.counter_refs):
            raise ValueError(f'verification check refers to unknown candidate evidence: {key}')
        checked[key] = check
    return checked


class _DocumentEvidence:
    def __init__(self, document: DocumentBundle):
        self.document = document
        self.segments = {segment.id: segment for segment in document.segments}
        self.assets = {asset.asset_id: asset.asset_hash for asset in document.assets}

    def supports(self, ref: EvidenceRef) -> bool:
        doc = self.document
        if (ref.source_kind != 'notice' or ref.source_id != doc.notice_id
                or ref.source_content_version != doc.content_version or ref.source_url != doc.source_url):
            return False

        if ref.asset_id is None:
            if ref.asset_hash is not None or ref.locator.segment_id is None or ref.locator.page is not None:
                return False
        elif ref.asset_hash is None or self.assets.get(ref.asset_id) != ref.asset_hash:
            return False

        locator = ref.locator
        if locator.segment_id is not None:
            segment = self.segments.get(locator.segment_id)
            possible = (segment,) if segment is not None else ()
        elif locator.page is not None or locator.clause is not None:
            possible = doc.segments
        else:
            return False
        return any(
            segment.asset_id == ref.asset_id
            and segment.asset_hash == ref.asset_hash
            and segment.page == locator.page
            and (locator.clause is None or locator.clause == segment.location)
            and ref.quote in segment.text
            for segment in possible
        )


@dataclass
class _GroupSupport:
    evidence_ids: set[str]
    condition_ids: set[str]
    group_ids: set[str]
    track_ids: set[str]
    track_id: str | None


class _Verification:
    def __init__(self, document: DocumentBundle, candidates: FactCandidates, checks: VerificationReport, digest: str):
        self.checks = _check_bindings(document, candidates, checks, digest)
        self.gaps = [FactGap(field_path='document', reason_code=code) for code in document.gaps]
        self.refs = {}
        self.used_refs: set[str] = set()
        source = _DocumentEvidence(document)
        for ref in candidates.evidence_refs:
            if source.supports(ref):
                self.refs[ref.evidence_id] = ref
            else:
                self.gaps.append(FactGap(field_path='evidence_refs', candidate_id=ref.evidence_id,
                                         reason_code='unverified_evidence'))

    def admits(self, path: FieldPath, id: str, evidence_ids, invalid_reason: str | None = None) -> bool:
        check = self.checks.get((path, id))
        if invalid_reason:
            reason = invalid_reason
        elif check is None:
            reason = 'missing_check'
        elif not evidence_ids or not self.refs.keys() >= set(evidence_ids):
            reason = 'unverified_evidence'
        elif not check.source_ok or not self.refs.keys() >= set(check.support_refs):
            reason = 'unverified_support'
        elif check.semantic_status != 'supported':
            reason = f'semantic_{check.semantic_status}'
        elif check.unresolved_conflict or check.counter_refs:
            reason = 'unresolved_conflict'
        elif not check.relation_complete:
            reason = 'incomplete_relation'
        elif not set(evidence_ids).intersection(check.support_refs):
            reason = 'missing_independent_support'
        else:
            self.used_refs.update(evidence_ids)
            self.used_refs.update(check.support_refs)
            return True
        self.gaps.append(FactGap(field_path=path, candidate_id=id, reason_code=reason,
                                 detail=check.reason_code if check else None))
        return False

    def groups(self, path: FieldPath, candidates: tuple[FactGroup, ...], conditions):
        by_id = {group.id: group for group in candidates}
        graph = TopologicalSorter({
            group.id: {member.id for member in group.members if member.type == 'group'}
            for group in candidates
        })
        try:
            graph.prepare()
        except CycleError:
            # Ready nodes are still safe to evaluate. Cycles and their dependants remain pending.
            pass
        visited = set()
        confirmed: dict[str, _GroupSupport] = {}
        while graph.is_active():
            ready = graph.get_ready()
            for group_id in ready:
                if group_id in by_id:
                    visited.add(group_id)
                    group = by_id[group_id]
                    support = _group_support(group, conditions, confirmed)
                    reason = None if support else 'invalid_or_unconfirmed_group_members'
                    if self.admits(path, group_id, support.evidence_ids if support else (), reason):
                        confirmed[group_id] = support
            graph.done(*ready)
        for group in candidates:
            if group.id not in visited:
                self.admits(path, group.id, (), 'cyclic_or_dependent_group')
        return confirmed


def _group_support(group: FactGroup, conditions, groups: dict[str, _GroupSupport]) -> _GroupSupport | None:
    member_keys = {(member.type, member.id) for member in group.members}
    if not member_keys or len(member_keys) != len(group.members):
        return None

    evidence_ids: set[str] = set()
    condition_ids: set[str] = set()
    group_ids = {group.id}
    track_ids = {group.track_id} if group.track_id else set()
    for member in group.members:
        if member.type == 'condition':
            condition = conditions.get(member.id)
            if condition is None:
                return None
            evidence_ids.update(condition.evidence_ids)
            condition_ids.add(member.id)
        else:
            child = groups.get(member.id)
            if child is None:
                return None
            evidence_ids.update(child.evidence_ids)
            condition_ids.update(child.condition_ids)
            group_ids.update(child.group_ids)
            track_ids.update(child.track_ids)
    if group.track_id is not None and track_ids != {group.track_id}:
        return None
    return _GroupSupport(evidence_ids, condition_ids, group_ids, track_ids, group.track_id)


def _condition_issue(condition: Condition) -> str | None:
    field, operator, value = condition.field, condition.operator, condition.value
    if condition.verification == 'uncertain' or field is None or operator is None:
        return 'unsupported_or_uncertain_condition'
    value_type = int if field == 'grade' else str
    if operator in ('in', 'not_in'):
        valid = isinstance(value, tuple) and bool(value) and all(type(item) is value_type for item in value)
    else:
        valid = type(value) is value_type and (operator == 'eq' or value_type is int)
    return None if valid else 'invalid_condition_value'


def _benefit_condition_issue(condition: BenefitConditionCandidate, actions: dict[str, FactAction]) -> str | None:
    if condition.target_id is not None and condition.target_id not in actions:
        return 'unconfirmed_benefit_target'
    if condition.verification == 'uncertain' or condition.kind == 'other':
        return 'unsupported_or_uncertain_benefit_condition'
    kind, operator, value, unit = condition.kind, condition.operator, condition.value, condition.unit
    if kind == 'award':
        valid = unit is None and (
            (operator == 'eq' and isinstance(value, str)) or (operator == 'in' and isinstance(value, tuple))
        )
    elif kind == 'attendance' and type(value) in (int, float):
        valid = operator in ('eq', 'gte', 'lte') and unit is not None and value >= 0
    else:
        valid = operator == 'eq' and type(value) is bool and unit is None
    return None if valid else 'invalid_benefit_condition_value'


def _graph_complete(candidate, groups: dict[str, _GroupSupport], input_complete: bool) -> bool:
    if not input_complete or not candidate.complete:
        return False
    if not candidate.conditions and not candidate.groups and candidate.root_group_id is None:
        return True
    root = groups.get(candidate.root_group_id)
    return bool(
        root
        and len(root.group_ids) == len(candidate.groups) and len(root.condition_ids) == len(candidate.conditions)
    )


def _read_time(value: TemporalValue) -> date | datetime:
    if value.precision == 'date' and _DATE.fullmatch(value.value):
        return date.fromisoformat(value.value)
    if value.precision == 'datetime' and _ZONED_DATETIME.fullmatch(value.value):
        return datetime.fromisoformat(value.value.upper())
    raise ValueError('invalid temporal value or precision')


def _ordered(start: date | datetime, end: date | datetime) -> bool:
    if isinstance(start, datetime) and isinstance(end, datetime):
        return start <= end
    if isinstance(start, datetime):
        end = datetime.combine(end, time.max, tzinfo=start.tzinfo)
    elif isinstance(end, datetime):
        start = datetime.combine(start, time.min, tzinfo=end.tzinfo)
    return start <= end


def _window_issue(window, actions, groups, refs, check) -> str | None:
    if window.verification == 'uncertain' or window.uncertainty_reason:
        return 'uncertain_date'
    if not window.audience_complete or (window.student_action and window.action_id is None):
        return 'incomplete_window_relation'
    if window.action_id is not None and window.action_id not in actions:
        return 'unconfirmed_window_action'

    if window.audience_group_id is not None:
        audience = groups.get(window.audience_group_id)
        if audience is None:
            return 'unconfirmed_window_audience'
        if audience.track_id != window.track_id:
            return 'mismatched_window_track'
    elif window.track_id is not None and not any(
        group.track_id == window.track_id for group in groups.values()
    ):
        return 'unconfirmed_window_track'

    if window.explicit_long_term and window.end is not None:
        return 'conflicting_long_term_window'
    if window.start is None and window.end is None and not window.explicit_long_term:
        return 'missing_window_date'
    try:
        start = _read_time(window.start) if window.start else None
        end = _read_time(window.end) if window.end else None
        if start is not None and end is not None and not _ordered(start, end):
            return 'reversed_window_dates'
    except (ValueError, OverflowError):
        return 'invalid_window_date'

    if check is not None:
        quotes = [refs[ref_id].quote for ref_id in check.support_refs if ref_id in refs]
        years = {year for quote in quotes for year in _YEAR.findall(quote)}
        if any(endpoint.value[:4] not in years for endpoint in (window.start, window.end) if endpoint):
            return 'missing_window_year_evidence'
        if (isinstance(start, datetime) or isinstance(end, datetime)) and not any(_CLOCK.search(quote) for quote in quotes):
            return 'missing_window_clock_evidence'
    return None


def _claim_issue(claim: BenefitClaim, actions, conditions, groups, unconditional: bool) -> str | None:
    if claim.action_id is None or claim.action_id not in actions:
        return 'unconfirmed_benefit_action'
    if claim.amount is not None and claim.unit is None:
        return 'missing_benefit_unit'
    if claim.condition_root_id is None:
        return None if unconditional else 'missing_benefit_condition_root'
    group = groups.get(claim.condition_root_id)
    if group is None:
        return 'unconfirmed_benefit_condition_root'
    if any(conditions[id].target_id != claim.action_id for id in group.condition_ids):
        return 'mismatched_benefit_action'
    return None


def _category(candidates: FactCandidates, actions: tuple[FactAction, ...], can_exclude: bool) -> str:
    main = [action for action in actions if action.main]
    if not main or len(main) != sum(action.main for action in candidates.actions):
        return 'unknown'
    if any(action.student_scope == 'unknown' for action in main):
        return 'unknown'

    eligible = [action for action in main if action.student_scope in ('undergraduate', 'mixed')]
    if not eligible:
        no_other_students = all(action.student_scope == 'non_undergraduate' for action in candidates.actions)
        return 'excluded' if can_exclude and no_other_students else 'unknown'

    kinds = {action.kind for action in eligible}
    if kinds <= _FINANCIAL:
        return 'financial_aid'
    if kinds <= _RESEARCH:
        return 'research_innovation'
    if kinds <= _DAILY:
        return 'daily'
    return 'unknown'


def verify_candidates(
    document: DocumentBundle, candidates: FactCandidates, checks: VerificationReport,
) -> VerifiedFacts:
    """Admit supported public facts and preserve the candidate and review history."""
    digest = candidate_digest(candidates)
    review = _Verification(document, candidates, checks, digest)
    coverage = checks.coverage_complete and not checks.missing_facts
    input_complete = document.body_status == 'full' and not document.gaps and coverage
    if not coverage:
        review.gaps.append(FactGap(field_path='coverage', reason_code='incomplete_independent_coverage'))
    review.gaps.extend(FactGap(field_path='coverage', reason_code='missing_fact', detail=item)
                       for item in checks.missing_facts)
    review.gaps.extend(FactGap(reason_code='candidate_uncertainty', detail=item)
                       for item in candidates.uncertainties)

    actions = tuple(action for action in candidates.actions
                    if review.admits('actions', action.id, action.evidence_ids))
    action_index = {action.id: action for action in actions}

    req = candidates.requirements
    conditions = {item.id: item.model_copy(update={'verification': 'confirmed'}) for item in req.conditions
                  if review.admits('requirements.conditions', item.id, item.evidence_ids, _condition_issue(item))}
    groups = review.groups('requirements.groups', req.groups, conditions)
    requirements = Requirements(
        complete=_graph_complete(req, groups, input_complete), conditions=tuple(conditions.values()),
        groups=tuple(group for group in req.groups if group.id in groups),
        root_group_id=req.root_group_id if req.root_group_id in groups else None,
    )
    if not requirements.complete:
        review.gaps.append(FactGap(field_path='requirements.groups', reason_code='incomplete_requirements'))

    windows = tuple(window.model_copy(update={'verification': 'confirmed'}) for window in candidates.time_windows
                    if review.admits('time_windows', window.id, window.evidence_ids,
                                     _window_issue(window, action_index, groups, review.refs,
                                                   review.checks.get(('time_windows', window.id)))))

    benefit = candidates.benefit_conditions
    benefit_leaves = {
        item.id: item.model_copy(update={'verification': 'confirmed'}) for item in benefit.conditions
        if review.admits('benefit_conditions.conditions', item.id, item.evidence_ids,
                         _benefit_condition_issue(item, action_index))
    }
    benefit_groups = review.groups('benefit_conditions.groups', benefit.groups, benefit_leaves)
    benefit_conditions = BenefitConditions(
        complete=_graph_complete(benefit, benefit_groups, input_complete),
        conditions=tuple(benefit_leaves.values()),
        groups=tuple(group for group in benefit.groups if group.id in benefit_groups),
        root_group_id=benefit.root_group_id if benefit.root_group_id in benefit_groups else None,
    )
    if not benefit_conditions.complete:
        review.gaps.append(FactGap(field_path='benefit_conditions.groups', reason_code='incomplete_benefit_conditions'))
    unconditional = benefit_conditions.complete and not benefit_conditions.groups
    claims = tuple(claim for claim in candidates.benefit_claims
                   if review.admits('benefit_claims', claim.id, claim.evidence_ids,
                                    _claim_issue(claim, action_index, benefit_leaves, benefit_groups, unconditional)))

    category = _category(candidates, actions, input_complete and not review.gaps)
    if category == 'unknown':
        review.gaps.append(FactGap(field_path='category', reason_code='unresolved_main_action_category'))
    return VerifiedFacts(
        notice_id=document.notice_id, content_version=document.content_version,
        input_fingerprint=document.input_fingerprint, candidate_digest=digest, rules_version=RULES_VERSION,
        body_status=document.body_status, category=category, complete=input_complete and not review.gaps,
        actions=actions, requirements=requirements, time_windows=windows, benefit_conditions=benefit_conditions,
        benefit_claims=claims, evidence_refs=tuple(ref for ref in candidates.evidence_refs
                                                 if ref.evidence_id in review.used_refs),
        candidates=candidates, checks=checks, gaps=tuple(review.gaps),
    )
