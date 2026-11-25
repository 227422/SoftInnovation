"""Current S2 tags and their evidence-backed values."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from campus_backend.documents.models import Array, Digest, NonBlankText, PublicValue
from .product_labels import AudienceGroup, Endpoint, ProductScope, endpoints_reversed
from .rule_labels import Category, RuleEvidence, RuleGap

RULES_VERSION = '3.1.0'

BenefitCode = Literal['volunteer_hours', 'innovation_credit', 'course_credit', 'sports_points',
                      'second_classroom_points', 'recommendation_points', 'comprehensive_points',
                      'financial_award', 'certificate']
DateCode = Literal['registration', 'application', 'submission', 'objection', 'event', 'policy_validity']
StatusValue = Literal['result_publicity', 'event_ended', 'policy_valid', 'policy_expired']


class SimpleLabel(PublicValue):
    scope: ProductScope
    evidence: Annotated[Array[RuleEvidence], Field(min_length=1)]


class SimpleBenefitLabel(SimpleLabel):
    kind: Literal['benefit'] = 'benefit'
    code: BenefitCode
    value: Literal[True] = True

    @field_validator('value', mode='before')
    @classmethod
    def true_only(cls, value):
        if value is not True:
            raise ValueError('benefit value must be true')
        return value


class SimpleDateValue(PublicValue):
    start: Endpoint | None = None
    end: Endpoint | None = None
    state: Literal['announced', 'tentative', 'conflicting', 'ended', 'cancelled', 'rescheduled', 'unknown'] = 'announced'
    explicit_long_term: bool = False

    @model_validator(mode='after')
    def valid_window(self) -> Self:
        if self.start is None and self.end is None and not self.explicit_long_term and self.state not in (
                'ended', 'cancelled', 'unknown'):
            raise ValueError('date needs an endpoint or explicit temporal state')
        if endpoints_reversed(self.start, self.end) and self.state != 'conflicting':
            raise ValueError('reversed absolute endpoints require conflicting state')
        if self.explicit_long_term and self.end is not None:
            raise ValueError('explicit long-term validity cannot have an end')
        return self


class SimpleDateLabel(SimpleLabel):
    kind: Literal['date'] = 'date'
    code: DateCode
    value: SimpleDateValue

    @model_validator(mode='after')
    def long_term_is_policy_validity(self) -> Self:
        if self.value.explicit_long_term and self.code != 'policy_validity':
            raise ValueError('explicit long-term validity requires a policy')
        return self


class SimpleAudienceLabel(SimpleLabel):
    kind: Literal['audience'] = 'audience'
    code: Literal['target_group'] = 'target_group'
    value: AudienceGroup


class SimpleStatusLabel(SimpleLabel):
    kind: Literal['status'] = 'status'
    code: Literal['document_status'] = 'document_status'
    value: StatusValue


SimpleFact = Annotated[
    SimpleBenefitLabel | SimpleDateLabel | SimpleAudienceLabel | SimpleStatusLabel,
    Field(discriminator='kind'),
]


class SimpleRuleResult(PublicValue):
    schema_version: Literal['s2-rule-baseline/3'] = 's2-rule-baseline/3'
    rules_version: NonBlankText = RULES_VERSION
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    category: Category
    complete: bool
    labels: Array[SimpleFact]
    gaps: Array[RuleGap]

    @model_validator(mode='after')
    def consistent_result(self) -> Self:
        if self.complete and (self.gaps or self.category == 'unknown'):
            raise ValueError('complete results require a resolved category and no gaps')
        if self.category == 'excluded' and self.labels:
            raise ValueError('excluded notices cannot have product tags')
        return self
