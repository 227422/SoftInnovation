"""Versioned inputs and durable worker state shared with the local storage port."""

from dataclasses import dataclass
from typing import Annotated, ContextManager, Literal, Protocol, Self

from pydantic import Field, model_validator

from campus_backend.documents.models import Array, Digest, DocumentBundle, NonBlankText, PublicValue, stable_digest

from .facts import RULES_VERSION, candidate_digest
from .models import VerifiedFacts
from .ports import ModelErrorCode, ModelStage
from .prompts import IDENTITY_FIELDS, PROMPT_FINGERPRINT


RUN_CALL_LIMIT = 16
RUN_TIME_LIMIT_MS = 600_000
CALL_TIME_LIMIT_MS = 60_000
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
Positive = Annotated[int, Field(gt=0)]
NonNegative = Annotated[int, Field(ge=0)]
RunStatus = Literal['pending', 'running', 'complete', 'incomplete', 'failed']


class FactRunError(Exception):
    """An operational error with a stable CLI code."""


class RunMethod(PublicValue):
    provider: Literal['responses-json-1', 'synthetic-replay-1']
    model: NonBlankText | None = None
    endpoint: NonBlankText | None = None
    context_limit: Positive | None = None
    fixture_digest: Digest | None = None
    input_token_limit: Positive | None = None
    output_token_limit: Positive | None = None
    context_margin: NonNegative | None = None
    max_prompt_bytes: Positive | None = None
    max_response_bytes: Positive | None = None
    token_counts_per_call: Literal[0, 1]
    process_concurrency_limit: Positive | None = None
    prompt_fingerprint: Digest = PROMPT_FINGERPRINT
    rules_version: NonBlankText = RULES_VERSION
    workflow_version: NonBlankText = 's2-semantic-1'
    repair_limit: NonNegative = 1
    call_limit: Positive = RUN_CALL_LIMIT
    call_time_limit_ms: Positive = CALL_TIME_LIMIT_MS
    run_time_limit_ms: Positive = RUN_TIME_LIMIT_MS

    @property
    def fingerprint(self) -> str:
        return stable_digest(self.model_dump(mode='json'))


class RunSpec(PublicValue):
    document: DocumentBundle
    method: RunMethod
    method_fingerprint: Digest

    @model_validator(mode='after')
    def fingerprints_match(self) -> Self:
        document_content = self.document.model_dump(mode='json', exclude={'content_version', 'input_fingerprint'})
        if (self.document.input_fingerprint != stable_digest(document_content)
                or self.method_fingerprint != self.method.fingerprint):
            raise ValueError('run fingerprint mismatch')
        return self

    @property
    def job_key(self) -> str:
        return stable_digest([*(getattr(self.document, field) for field in IDENTITY_FIELDS), self.method_fingerprint])


class CallRecord(PublicValue):
    attempt: Positive
    stage: ModelStage
    request_fingerprint: Digest
    reserved_ms: Positive
    elapsed_ms: NonNegative | None = None


class RunState(PublicValue):
    status: RunStatus = 'pending'
    attempts: NonNegative = 0
    charged_ms: NonNegative = 0
    calls: Array[CallRecord] = ()
    facts: VerifiedFacts | None = None
    error_code: ModelErrorCode | None = None

    def validate_for(self, spec: RunSpec) -> None:
        if (len(self.calls) > spec.method.call_limit
                or sum(call.stage == 'repair' for call in self.calls) > spec.method.repair_limit
                or any(call.attempt > self.attempts or call.reserved_ms > spec.method.call_time_limit_ms
                for call in self.calls)
                or self.charged_ms < sum(call.reserved_ms if call.elapsed_ms is None else call.elapsed_ms
                                         for call in self.calls)):
            raise ValueError('inconsistent call ledger')
        completed = self.error_code is None and self.facts is not None and self.facts.complete
        if (self.status == 'complete') != completed:
            raise ValueError('inconsistent result status')
        if self.facts is None:
            return
        result = self.facts
        if (self.status not in ('complete', 'incomplete')
                or result.rules_version != spec.method.rules_version
                or result.candidate_digest != candidate_digest(result.candidates)
                or result.checks.candidate_digest != result.candidate_digest
                or any(getattr(item, field) != getattr(spec.document, field)
                       for item in (result, result.candidates, result.checks) for field in IDENTITY_FIELDS)):
            raise ValueError('result does not match run')


@dataclass(frozen=True, slots=True)
class RunResult:
    state: RunState
    cached: bool = False


class LockedFactRun(Protocol):
    def read_spec(self) -> RunSpec: ...
    def read_state(self, spec: RunSpec) -> RunState: ...
    def save_state(self, state: RunState) -> None: ...


class FactRunStore(Protocol):
    def prepare(self, spec: RunSpec) -> str: ...
    def lock(self, job_key: str) -> ContextManager[LockedFactRun]: ...
