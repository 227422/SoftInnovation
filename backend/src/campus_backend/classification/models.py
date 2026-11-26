"""Internal S2 candidates, independent review, and admitted public facts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from campus_backend.documents.models import (
    Array, BodyStatus, Digest, EvidenceRef, NonBlankText, PublicValue,
)


Category = Literal['research_innovation', 'financial_aid', 'daily', 'excluded', 'unknown']
ActionKind = Literal[
    'scholarship_application', 'aid', 'award_selection', 'competition', 'research', 'innovation',
    'academic', 'activity', 'practice', 'career', 'exchange', 'other',
]
StudentScope = Literal['undergraduate', 'mixed', 'non_undergraduate', 'unknown']
CandidateVerification = Literal['confirmed', 'uncertain']
FieldPath = Literal[
    'actions', 'requirements.conditions', 'requirements.groups', 'time_windows',
    'benefit_conditions.conditions', 'benefit_conditions.groups', 'benefit_claims',
]
type BoundedArray[T] = Annotated[Array[T], Field(max_length=256)]
EvidenceIDs = Annotated[Array[NonBlankText], Field(max_length=64)]
NonEmptyTextArray = Annotated[BoundedArray[NonBlankText], Field(min_length=1)]
NonEmptyIntArray = Annotated[BoundedArray[int], Field(min_length=1)]


class FactAction(PublicValue):
    id: NonBlankText
    main: bool
    kind: ActionKind
    student_scope: StudentScope
    text: NonBlankText
    evidence_ids: EvidenceIDs


class Condition(PublicValue):
    id: NonBlankText
    kind: Literal['audience', 'eligibility']
    field: Literal[
        'education_stage', 'school_id', 'college_id', 'major_id', 'major_group_id',
        'grade', 'course_id', 'skill_id',
    ] | None
    operator: Literal['in', 'not_in', 'eq', 'gte', 'lte'] | None
    value: NonBlankText | int | NonEmptyTextArray | NonEmptyIntArray | None
    text: NonBlankText
    evidence_ids: EvidenceIDs
    verification: CandidateVerification | None = None


class GroupMember(PublicValue):
    type: Literal['condition', 'group']
    id: NonBlankText


class FactGroup(PublicValue):
    id: NonBlankText
    operator: Literal['all', 'any']
    members: Annotated[Array[GroupMember], Field(max_length=128)]
    track_id: NonBlankText | None = None
    label: NonBlankText


class Requirements(PublicValue):
    complete: bool = False
    conditions: BoundedArray[Condition] = ()
    groups: BoundedArray[FactGroup] = ()
    root_group_id: NonBlankText | None = None


class TemporalValue(PublicValue):
    value: NonBlankText
    precision: Literal['date', 'datetime']


class TimeWindowFact(PublicValue):
    id: NonBlankText
    action_id: NonBlankText | None = None
    track_id: NonBlankText | None = None
    audience_group_id: NonBlankText | None = None
    audience_complete: bool
    kind: Literal['registration', 'submission', 'event', 'appeal', 'policy_validity', 'other']
    label: NonBlankText
    audience_text: NonBlankText | None = None
    start: TemporalValue | None = None
    end: TemporalValue | None = None
    explicit_long_term: bool
    student_action: bool
    verification: CandidateVerification | None = None
    raw_text: NonBlankText
    uncertainty_reason: NonBlankText | None = None
    evidence_ids: EvidenceIDs


class BenefitConditionCandidate(PublicValue):
    id: NonBlankText
    kind: Literal['participation', 'completion', 'award', 'attendance', 'approval', 'other']
    target_id: NonBlankText | None = None
    target_text: NonBlankText
    operator: Literal['eq', 'in', 'gte', 'lte'] | None
    value: bool | NonBlankText | int | float | NonEmptyTextArray | None
    unit: NonBlankText | None = None
    text: NonBlankText
    evidence_ids: EvidenceIDs
    verification: CandidateVerification | None = None


class BenefitConditions(PublicValue):
    complete: bool = False
    conditions: BoundedArray[BenefitConditionCandidate] = ()
    groups: BoundedArray[FactGroup] = ()
    root_group_id: NonBlankText | None = None


class BenefitClaim(PublicValue):
    id: NonBlankText
    type: Literal['recommendation', 'credit', 'comprehensive', 'volunteer', 'sports', 'other']
    condition_root_id: NonBlankText | None = None
    action_id: NonBlankText | None = None
    amount: float | None = None
    unit: NonBlankText | None = None
    text: NonBlankText
    evidence_ids: EvidenceIDs


class FactCandidates(PublicValue):
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    actions: BoundedArray[FactAction] = ()
    requirements: Requirements = Field(default_factory=Requirements)
    time_windows: BoundedArray[TimeWindowFact] = ()
    benefit_conditions: BenefitConditions = Field(default_factory=BenefitConditions)
    benefit_claims: BoundedArray[BenefitClaim] = ()
    evidence_refs: Annotated[Array[EvidenceRef], Field(max_length=1024)] = ()
    uncertainties: BoundedArray[NonBlankText] = ()


class FieldCheck(PublicValue):
    field_path: FieldPath
    candidate_id: NonBlankText
    source_ok: bool
    semantic_status: Literal['supported', 'contradicted', 'insufficient']
    relation_complete: bool
    support_refs: EvidenceIDs
    counter_refs: EvidenceIDs
    unresolved_conflict: bool
    reason_code: NonBlankText


class VerificationReport(PublicValue):
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    candidate_digest: Digest
    checks: Annotated[Array[FieldCheck], Field(max_length=1792)]
    coverage_complete: bool
    missing_facts: BoundedArray[NonBlankText]

    @model_validator(mode='after')
    def coverage_is_consistent(self) -> Self:
        if self.coverage_complete and self.missing_facts:
            raise ValueError('complete review cannot list missing facts')
        return self


class FactGap(PublicValue):
    reason_code: NonBlankText
    field_path: FieldPath | Literal['document', 'evidence_refs', 'category', 'coverage'] | None = None
    candidate_id: NonBlankText | None = None
    detail: NonBlankText | None = None


class VerifiedFacts(PublicValue):
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    candidate_digest: Digest
    rules_version: NonBlankText
    body_status: BodyStatus
    category: Category
    complete: bool
    actions: BoundedArray[FactAction]
    requirements: Requirements
    time_windows: BoundedArray[TimeWindowFact]
    benefit_conditions: BenefitConditions
    benefit_claims: BoundedArray[BenefitClaim]
    evidence_refs: Array[EvidenceRef]
    candidates: FactCandidates
    checks: VerificationReport
    gaps: Array[FactGap]
