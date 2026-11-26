"""Version 2 internal facts, preserving dates without a guessed calendar year."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from campus_backend.documents.models import Array, Digest, NonBlankText, PublicValue
from .rule_labels import Category, DateValue, RuleEvidence, RuleGap

RULES_VERSION = '2.3.0'


class AbsoluteEndpoint(DateValue):
    kind: Literal['absolute'] = 'absolute'


class MonthDayEndpoint(PublicValue):
    kind: Literal['month_day'] = 'month_day'
    month_day: Annotated[str, Field(pattern=r'^\d{2}-\d{2}$')]
    time: Annotated[str, Field(pattern=r'^\d{2}:\d{2}$')] | None = None

    @field_validator('month_day')
    @classmethod
    def calendar_day(cls, value: str) -> str:
        date.fromisoformat('2000-' + value)
        return value

    @field_validator('time')
    @classmethod
    def clock(cls, value: str | None) -> str | None:
        return DateValue.valid_time(value)


class RelativeEndpoint(PublicValue):
    kind: Literal['relative'] = 'relative'
    anchor: NonBlankText
    days: Annotated[int, Field(ge=0)] | None = None
    approximate: bool = False


class PendingEndpoint(PublicValue):
    kind: Literal['pending'] = 'pending'
    reason: Literal['to_be_announced', 'unresolved']


Endpoint = Annotated[
    AbsoluteEndpoint | MonthDayEndpoint | RelativeEndpoint | PendingEndpoint,
    Field(discriminator='kind'),
]


class AudienceGroup(PublicValue):
    audience: NonBlankText | None = None
    campus: NonBlankText | None = None
    college: NonBlankText | None = None
    class_name: NonBlankText | None = None

    @model_validator(mode='after')
    def nonempty(self) -> Self:
        if not any((self.audience, self.campus, self.college, self.class_name)):
            raise ValueError('audience group needs a qualifier')
        return self


class ProductScope(PublicValue):
    action: NonBlankText | None = None
    track: NonBlankText | None = None
    phase: NonBlankText | None = None
    audience_groups: Array[AudienceGroup] = ()


class Requirement(PublicValue):
    operator: Literal['text', 'all', 'any']
    items: Annotated[Array[NonBlankText], Field(min_length=1)]

    @model_validator(mode='after')
    def arity(self) -> Self:
        if (self.operator == 'text') != (len(self.items) == 1):
            raise ValueError('text requires one item and all/any require multiple items')
        return self


def endpoints_reversed(start: Endpoint | None, end: Endpoint | None) -> bool:
    """Compare explicit calendar endpoints only; a missing year is not inferred."""
    if not isinstance(start, AbsoluteEndpoint) or not isinstance(end, AbsoluteEndpoint):
        return False
    return start.date > end.date or (
        start.date == end.date and start.time is not None and end.time is not None and start.time > end.time)


class WindowValue(PublicValue):
    start: Endpoint | None = None
    end: Endpoint | None = None
    state: Literal['announced', 'tentative', 'conflicting', 'ended', 'cancelled', 'rescheduled'] = 'announced'
    student_action: bool = True
    requirement: Requirement | None = None

    @model_validator(mode='after')
    def has_time_or_status(self) -> Self:
        if self.start is None and self.end is None and self.state not in ('ended', 'cancelled'):
            raise ValueError('window requires an endpoint or explicit ended/cancelled status')
        if endpoints_reversed(self.start, self.end) and self.state != 'conflicting':
            raise ValueError('reversed absolute endpoints require conflicting state')
        return self


class ProductLabel(PublicValue):
    scope: ProductScope
    evidence: Annotated[Array[RuleEvidence], Field(min_length=1)]
    presentation: Literal['display', 'detail'] = 'display'


class WindowLabel(ProductLabel):
    kind: Literal['date'] = 'date'
    code: Literal['registration', 'application', 'submission', 'objection', 'event',
                  'policy_effective', 'policy_expiry', 'internal_reporting']
    value: WindowValue


class ProductBenefitValue(PublicValue):
    # direct_award measures a public grant statement. Unknown condition status
    # keeps the entitlement unresolved even when the grant itself was stated.
    amount: Annotated[int | float, Field(gt=0)] | None = None
    unit: Literal['小时', '分', '学分', '元', '万元'] | None = None
    claim_relation: Literal['direct_award', 'direct_conditional_award',
                            'necessary_condition_not_sufficient_guarantee',
                            'curriculum_requirement', 'curriculum_offering']
    quantity_operator: Literal['eq', 'gte', 'lte'] | None = None
    requirement: Requirement | None = None
    condition_status: Literal['stated', 'unknown'] = 'unknown'
    claim_only: Literal[True] = True

    @model_validator(mode='after')
    def valid_claim(self) -> Self:
        if (self.amount is None) != (self.unit is None):
            raise ValueError('amount and unit must be specified together')
        if self.quantity_operator is not None and self.amount is None:
            raise ValueError('quantity operator requires amount')
        if (self.condition_status == 'stated') != (self.requirement is not None):
            raise ValueError('condition status must match explicit condition')
        if self.claim_relation == 'direct_award' and self.requirement is not None:
            raise ValueError('direct award cannot have an explicit condition')
        if self.claim_relation in ('direct_conditional_award', 'necessary_condition_not_sufficient_guarantee') and self.requirement is None:
            raise ValueError('conditional claim requires its condition')
        return self


class ProductBenefitLabel(ProductLabel):
    kind: Literal['benefit'] = 'benefit'
    code: Literal['volunteer_hours', 'innovation_credit', 'course_credit', 'sports_points',
                  'second_classroom_points', 'recommendation_points', 'comprehensive_points',
                  'financial_award', 'certificate']
    value: ProductBenefitValue


class ProductConditionLabel(ProductLabel):
    kind: Literal['condition'] = 'condition'
    code: Literal['eligibility', 'benefit_requirement']
    value: Requirement


class ProductStatusLabel(ProductLabel):
    kind: Literal['status'] = 'status'
    code: Literal['document_status']
    value: Literal['result_publicity', 'event_ended', 'policy_valid', 'policy_expired']


ProductFact = Annotated[
    WindowLabel | ProductBenefitLabel | ProductConditionLabel | ProductStatusLabel,
    Field(discriminator='kind'),
]


class ProductRuleResult(PublicValue):
    schema_version: Literal['s2-rule-baseline/2'] = 's2-rule-baseline/2'
    rules_version: NonBlankText
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    category: Category
    complete: bool
    labels: Array[ProductFact]
    gaps: Array[RuleGap]

    @model_validator(mode='after')
    def complete_requires_coverage(self) -> Self:
        if self.complete and (self.gaps or self.category == 'unknown'):
            raise ValueError('complete results require a resolved category and no gaps')
        return self
