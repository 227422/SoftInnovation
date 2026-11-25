"""Extract, independently review, and deterministically admit public facts."""

from dataclasses import dataclass

from campus_backend.documents.models import DocumentBundle

from .facts import candidate_digest, candidate_fields, verify_candidates
from .models import FactCandidates, FactGap, VerificationReport, VerifiedFacts
from .ports import FactModel, ModelCallError, ModelErrorCode, ModelStage
from .prompts import IDENTITY_FIELDS, REVIEW_BINDINGS, make_request


def _bound_output(raw, document, bindings, *, code, **local):
    if not isinstance(raw, dict) or raw.keys() & set(bindings):
        raise ModelCallError(code)
    return raw | {field: getattr(document, field) for field in IDENTITY_FIELDS} | local


class SemanticFactExtractor:
    def __init__(self, model: FactModel):
        self._model = model

    def extract(self, document: DocumentBundle) -> FactCandidates:
        return self._extract(document, 'extract')

    def repair(self, document: DocumentBundle, candidates: FactCandidates, gaps: tuple[FactGap, ...]) -> FactCandidates:
        return self._extract(
            document, 'repair', candidates=candidates.model_dump(mode='json'),
            review_feedback=[gap.model_dump(mode='json') for gap in gaps],
        )

    def _extract(self, document: DocumentBundle, stage: ModelStage, **data) -> FactCandidates:
        raw = self._model.complete(make_request(stage, document, **data))
        values = _bound_output(raw, document, IDENTITY_FIELDS, code='invalid_extraction')
        try:
            candidates = FactCandidates.model_validate(values)
        except ValueError:
            raise ModelCallError('invalid_extraction') from None
        fields = candidate_fields(candidates)
        if (len(set(fields)) != len(fields)
                or len({ref.evidence_id for ref in candidates.evidence_refs}) != len(candidates.evidence_refs)):
            raise ModelCallError('invalid_extraction')
        return candidates


class IndependentFactVerifier:
    def __init__(self, model: FactModel):
        self._model = model

    def verify(self, document: DocumentBundle, candidates: FactCandidates) -> VerificationReport:
        # This separate call has no candidate, check, or repair data from any previous request.
        independent = SemanticFactExtractor(self._model)._extract(document, 'independent')
        request = make_request(
            'compare', document,
            candidates=candidates.model_dump(mode='json'),
            independent_candidates=independent.model_dump(mode='json'),
            review_targets=[{'field_path': path, 'candidate_id': id} for path, id in candidate_fields(candidates)],
        )
        raw = self._model.complete(request)
        values = _bound_output(raw, document, REVIEW_BINDINGS, code='invalid_comparison',
                               candidate_digest=candidate_digest(candidates))
        independent_complete = (document.body_status == 'full' and not document.gaps
                                and independent.requirements.complete and independent.benefit_conditions.complete
                                and not independent.uncertainties)
        if values.get('coverage_complete') is True and (values.get('missing_facts') or not independent_complete):
            values['coverage_complete'] = False
        try:
            return VerificationReport.model_validate(values)
        except ValueError:
            raise ModelCallError('invalid_comparison') from None


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    facts: VerifiedFacts
    error_code: ModelErrorCode | None = None


def process(document: DocumentBundle, model: FactModel, *, allow_repair: bool = True) -> ProcessingOutcome:
    """Run at most one repair, with independent re-extraction and comparison."""
    if 'segment_limit' in document.gaps:
        raise ModelCallError('context_limit')
    extractor = SemanticFactExtractor(model)
    reviewer = IndependentFactVerifier(model)

    def review(candidates):
        checks = reviewer.verify(document, candidates)
        try:
            return verify_candidates(document, candidates, checks)
        except ValueError:
            raise ModelCallError('invalid_comparison') from None

    candidates = extractor.extract(document)
    facts = review(candidates)
    repair_gaps = tuple(gap for gap in facts.gaps if (
        gap.candidate_id is not None or gap.reason_code == 'missing_fact'
        or (document.body_status == 'full'
            and gap.reason_code in ('incomplete_requirements', 'incomplete_benefit_conditions'))
    ))
    if not allow_repair or not repair_gaps:
        return ProcessingOutcome(facts)
    try:
        return ProcessingOutcome(review(extractor.repair(document, candidates, repair_gaps)))
    except ModelCallError as exc:
        return ProcessingOutcome(facts, exc.code)
