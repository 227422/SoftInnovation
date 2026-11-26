"""Versioned internal protocol for rule-based public notice analysis."""

from datetime import date, time
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from campus_backend.documents.models import Array, Digest, NonBlankText, PublicValue

Category = Literal['research_innovation', 'financial_aid', 'daily', 'excluded', 'unknown']
GapCode = Literal['body_incomplete', 'attachment_unread', 'document_gap', 'category_unknown',
                  'date_unresolved', 'date_conflict', 'benefit_unresolved', 'coverage_unconfirmed']


class RuleEvidence(PublicValue):
    segment_id: NonBlankText
    quote: NonBlankText


class RuleScope(PublicValue):
    action: NonBlankText | None = None
    track: NonBlankText | None = None
    audience: NonBlankText | None = None


class RuleLabel(PublicValue):
    scope: RuleScope
    evidence: Annotated[Array[RuleEvidence], Field(min_length=1)]


class DateValue(PublicValue):
    date: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
    time: Annotated[str, Field(pattern=r'^\d{2}:\d{2}$')] | None = None
    timezone: Literal['Asia/Shanghai'] = 'Asia/Shanghai'

    @field_validator('date')
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @field_validator('time')
    @classmethod
    def valid_time(cls, value: str | None) -> str | None:
        if value is not None:
            time.fromisoformat(value)
        return value


class DateLabel(RuleLabel):
    kind: Literal['date'] = 'date'
    code: Literal['registration_start', 'application_start', 'submission_start',
                  'registration_deadline', 'application_deadline', 'submission_deadline',
                  'internal_reporting_deadline', 'objection_deadline', 'event_start', 'event_end',
                  'publicity_end', 'policy_expiry']
    value: DateValue


class BenefitValue(PublicValue):
    text: NonBlankText
    amount: Annotated[int | float, Field(gt=0)] | None = None
    unit: Literal['小时', '分', '学分', '元', '万元'] | None = None
    condition: NonBlankText | None = None
    condition_status: Literal['stated', 'unknown'] = 'unknown'
    claim_only: Literal[True] = True

    @model_validator(mode='after')
    def amount_has_unit(self) -> Self:
        if (self.condition_status == 'stated') != (self.condition is not None):
            raise ValueError('stated conditions require text and unknown conditions omit text')
        if (self.amount is None) != (self.unit is None):
            raise ValueError('amount and unit must be specified together')
        return self


class BenefitLabel(RuleLabel):
    kind: Literal['benefit'] = 'benefit'
    code: Literal['volunteer_hours', 'innovation_credit', 'course_credit', 'sports_points',
                  'second_classroom_points', 'recommendation_points', 'comprehensive_points',
                  'financial_award', 'certificate']
    value: BenefitValue


class ConditionValue(PublicValue):
    text: NonBlankText


class ConditionLabel(RuleLabel):
    kind: Literal['condition'] = 'condition'
    code: Literal['eligibility', 'benefit_requirement']
    value: ConditionValue


class StatusLabel(RuleLabel):
    kind: Literal['status'] = 'status'
    code: Literal['document_status']
    value: Literal['result_publicity', 'event_ended', 'policy_valid', 'policy_expired']


Label = Annotated[DateLabel | BenefitLabel | ConditionLabel | StatusLabel, Field(discriminator='kind')]


class RuleGap(PublicValue):
    code: GapCode
    detail: NonBlankText
    evidence: Array[RuleEvidence] = ()


class RuleBaselineResult(PublicValue):
    schema_version: Literal['s2-rule-baseline/1'] = 's2-rule-baseline/1'
    rules_version: NonBlankText
    notice_id: NonBlankText
    content_version: NonBlankText
    input_fingerprint: Digest
    category: Category
    complete: bool
    labels: Array[Label]
    gaps: Array[RuleGap]

    @model_validator(mode='after')
    def complete_requires_coverage(self) -> Self:
        if self.complete and (self.gaps or self.category == 'unknown'):
            raise ValueError('complete results require a resolved category and no gaps')
        return self
