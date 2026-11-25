"""Single-document fact processing with a persisted attempt and call budget."""

import math
from time import monotonic
from typing import Callable

from campus_backend.documents.models import DocumentBundle

from .extraction import process
from .ports import FactModel, ModelCallError, ModelRequest
from .run_contract import (
    CallRecord, FactRunError, FactRunStore, LockedFactRun, RunMethod, RunResult, RunSpec, RunState,
)


_TERMINAL_LIMITS = {'context_limit', 'model_call_budget', 'model_time_budget'}
_INCOMPLETE_ERRORS = _TERMINAL_LIMITS | {'model_incomplete', 'model_response_too_large', 'model_timeout'}


class _BudgetedModel:
    def __init__(self, model: FactModel, method: RunMethod, run: LockedFactRun, state: RunState, clock):
        self._model = model
        self._method = method
        self._run = run
        self._clock = clock
        self._last = clock()
        self.state = state

    def _elapsed_ms(self, start):
        return max(0, math.ceil((self._clock() - start) * 1000))

    def checkpoint(self):
        self.state = self.state.model_copy(update={'charged_ms': self.state.charged_ms + self._elapsed_ms(self._last)})
        self._last = self._clock()

    def complete(self, request: ModelRequest, *, timeout_seconds: float = 60) -> dict:
        request_fingerprint = request.fingerprint
        self.checkpoint()
        remaining = self._method.run_time_limit_ms - self.state.charged_ms
        if remaining <= 0:
            raise ModelCallError('model_time_budget')
        if len(self.state.calls) >= self._method.call_limit:
            raise ModelCallError('model_call_budget')
        reserved = min(self._method.call_time_limit_ms, remaining, math.ceil(timeout_seconds * 1000))
        if reserved <= 0:
            raise ModelCallError('model_timeout')

        record = CallRecord(attempt=self.state.attempts, stage=request.stage, request_fingerprint=request_fingerprint,
                            reserved_ms=reserved)
        self.state = self.state.model_copy(update={'charged_ms': self.state.charged_ms + reserved,
                                                  'calls': (*self.state.calls, record)})
        # Persist before invoking the adapter, including before its token count. A crash retains the reservation.
        self._run.save_state(self.state)
        try:
            milliseconds_left = reserved - self._elapsed_ms(self._last)
            if milliseconds_left <= 0:
                raise ModelCallError('model_time_budget' if reserved == remaining else 'model_timeout')
            try:
                return self._model.complete(request, timeout_seconds=milliseconds_left / 1000)
            except ModelCallError:
                raise
            except Exception:
                raise ModelCallError('processing_failed') from None
        finally:
            elapsed = self._elapsed_ms(self._last)
            self._last = self._clock()
            record = record.model_copy(update={'elapsed_ms': elapsed})
            self.state = self.state.model_copy(update={'charged_ms': self.state.charged_ms - reserved + elapsed,
                                                      'calls': (*self.state.calls[:-1], record)})
            self._run.save_state(self.state)


class FactWorker:
    def __init__(self, store: FactRunStore, model: FactModel, method: RunMethod, *,
                 clock: Callable[[], float] = monotonic):
        self._store = store
        self._model = model
        self._method = method
        self._clock = clock

    def prepare(self, document: DocumentBundle) -> str:
        try:
            spec = RunSpec(document=document, method=self._method, method_fingerprint=self._method.fingerprint)
        except ValueError:
            raise FactRunError('invalid_document') from None
        return self._store.prepare(spec)

    def run(self, job_key: str) -> RunResult:
        with self._store.lock(job_key) as run:
            spec = run.read_spec()
            if spec.method_fingerprint != self._method.fingerprint:
                raise FactRunError('method_mismatch')
            state = run.read_state(spec)
            if state.facts is not None or state.error_code in _TERMINAL_LIMITS:
                return RunResult(state, cached=True)
            if state.charged_ms >= self._method.run_time_limit_ms:
                return self._limit(run, state, 'model_time_budget')
            if len(state.calls) >= self._method.call_limit:
                return self._limit(run, state, 'model_call_budget')

            state = state.model_copy(update={'status': 'running', 'attempts': state.attempts + 1, 'error_code': None})
            model = _BudgetedModel(self._model, self._method, run, state, self._clock)
            run.save_state(state)
            facts = None
            try:
                used_repairs = sum(call.stage == 'repair' for call in state.calls)
                outcome = process(spec.document, model, allow_repair=used_repairs < self._method.repair_limit)
                facts, error = outcome.facts, outcome.error_code
            except ModelCallError as exc:
                error = exc.code

            model.checkpoint()
            if model.state.charged_ms > self._method.run_time_limit_ms:
                error = 'model_time_budget'
            status = ('complete' if error is None and facts and facts.complete else
                      'incomplete' if facts or error in _INCOMPLETE_ERRORS else 'failed')
            state = model.state.model_copy(update={'status': status, 'facts': facts, 'error_code': error})
            state.validate_for(spec)
            run.save_state(state)
            return RunResult(state)

    @staticmethod
    def _limit(run, state, code):
        state = state.model_copy(update={'status': 'incomplete', 'error_code': code})
        run.save_state(state)
        return RunResult(state)
