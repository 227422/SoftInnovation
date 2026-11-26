"""Public fact extraction and independent semantic review boundaries."""

from dataclasses import dataclass
from typing import Literal, Protocol, get_args

from campus_backend.documents.models import DocumentBundle, stable_digest

from .models import FactCandidates, VerificationReport


class FactExtractor(Protocol):
    def extract(self, document: DocumentBundle) -> FactCandidates: ...


class FactVerifier(Protocol):
    def verify(self, document: DocumentBundle, candidates: FactCandidates) -> VerificationReport: ...


ModelStage = Literal['extract', 'independent', 'compare', 'repair']


@dataclass(frozen=True, slots=True)
class ModelRequest:
    stage: ModelStage
    system: str
    user: str

    @property
    def fingerprint(self) -> str:
        return stable_digest([self.stage, self.system, self.user])


class FactModel(Protocol):
    def complete(self, request: ModelRequest, *, timeout_seconds: float = 60) -> dict: ...


ModelErrorCode = Literal[
    'context_limit', 'invalid_extraction', 'invalid_comparison', 'invalid_model_json',
    'invalid_model_response', 'model_call_budget', 'model_time_budget', 'model_http_failed',
    'model_incomplete', 'model_refusal', 'model_response_too_large', 'model_timeout',
    'token_count_failed', 'invalid_replay', 'processing_failed',
]


class ModelCallError(Exception):
    def __init__(self, code: ModelErrorCode):
        self.code = code if code in get_args(ModelErrorCode) else 'processing_failed'
        super().__init__(self.code)
