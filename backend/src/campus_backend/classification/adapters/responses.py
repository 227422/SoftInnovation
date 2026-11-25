"""Responses HTTP adapter for public JSON-only model requests."""

import asyncio
import re
from dataclasses import dataclass, field
from threading import BoundedSemaphore
from time import monotonic
from urllib.parse import urlsplit

import httpx

from ..json_io import json_object
from ..ports import ModelCallError, ModelErrorCode, ModelRequest


INPUT_TOKEN_LIMIT = 12_000
OUTPUT_TOKEN_LIMIT = 3_000
CALL_TIMEOUT_SECONDS = 60
CONTEXT_MARGIN = 1
MAX_RESPONSE_BYTES = 256 * 1024
MAX_INPUT_BYTES = 8 * 1024 * 1024
RESPONSES_PROTOCOL = 'responses-json-1'
PROCESS_CONCURRENCY_LIMIT = 2
_PROCESS_SLOTS = BoundedSemaphore(PROCESS_CONCURRENCY_LIMIT)


@dataclass(frozen=True, slots=True)
class ResponsesConfig:
    base_url: str
    model: str
    context_limit: int
    api_key: str = field(repr=False)

    def __post_init__(self):
        try:
            url = urlsplit(self.base_url)
            valid_url = (url.scheme == 'https' and url.hostname and url.port != 0
                         and url.username is None and '?' not in self.base_url and '#' not in self.base_url
                         and not any(char.isspace() for char in self.base_url)
                         and '\\' not in self.base_url)
        except ValueError:
            valid_url = False
        if (not valid_url or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', self.model)
                or type(self.context_limit) is not int or self.context_limit <= OUTPUT_TOKEN_LIMIT + CONTEXT_MARGIN
                or not re.fullmatch(r'[!-~]+', self.api_key)):
            raise ValueError('invalid_model_configuration')
        object.__setattr__(self, 'base_url', self.base_url.rstrip('/'))


class ResponsesModel:
    def __init__(self, config: ResponsesConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self._config = config
        self._transport = transport

    def complete(self, request: ModelRequest, *, timeout_seconds: float = CALL_TIMEOUT_SECONDS) -> dict:
        timeout = min(timeout_seconds, CALL_TIMEOUT_SECONDS)
        deadline = monotonic() + timeout
        if timeout <= 0 or not _PROCESS_SLOTS.acquire(timeout=timeout):
            raise ModelCallError('model_timeout')
        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._complete(request, deadline - monotonic()))
            finally:
                # Do not wait for an already cancelled OS DNS lookup to finish.
                loop.close()
        except (TimeoutError, httpx.TimeoutException):
            raise ModelCallError('model_timeout') from None
        finally:
            _PROCESS_SLOTS.release()

    async def _complete(self, request: ModelRequest, timeout: float) -> dict:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with asyncio.timeout_at(deadline):
            if timeout <= 0 or len(request.system.encode('utf-8')) + len(request.user.encode('utf-8')) > MAX_INPUT_BYTES:
                raise ModelCallError('context_limit' if timeout > 0 else 'model_timeout')
            payload = {
                'model': self._config.model,
                'input': [{'role': 'system', 'content': request.system},
                          {'role': 'user', 'content': request.user}],
                'text': {'format': {'type': 'json_object'}},
                'truncation': 'disabled',
            }
            async with httpx.AsyncClient(
                base_url=self._config.base_url, transport=self._transport, trust_env=False, follow_redirects=False,
                timeout=timeout, headers={'Authorization': f'Bearer {self._config.api_key}',
                                          'Accept-Encoding': 'identity'},
            ) as client:
                count = await _post(client, 'responses/input_tokens', payload, 'token_count_failed')
                tokens = count.get('input_tokens')
                if count.get('object') != 'response.input_tokens' or type(tokens) is not int or tokens <= 0:
                    raise ModelCallError('token_count_failed')
                if (tokens > INPUT_TOKEN_LIMIT
                        or tokens + OUTPUT_TOKEN_LIMIT + CONTEXT_MARGIN > self._config.context_limit):
                    raise ModelCallError('context_limit')
                if loop.time() >= deadline:
                    raise ModelCallError('model_timeout')
                raw = await _post(client, 'responses', payload | {'max_output_tokens': OUTPUT_TOKEN_LIMIT, 'store': False},
                                  'model_http_failed')
                result = _output_object(raw)
                if loop.time() >= deadline:
                    raise ModelCallError('model_timeout')
                return result


async def _post(client: httpx.AsyncClient, path: str, payload: dict, failure: ModelErrorCode) -> dict:
    try:
        async with client.stream('POST', path, json=payload) as response:
            if not response.is_success or response.headers.get('content-encoding', 'identity') != 'identity':
                raise ModelCallError(failure)
            data = bytearray()
            async for part in response.aiter_bytes(chunk_size=8192):
                if len(data) + len(part) > MAX_RESPONSE_BYTES:
                    raise ModelCallError('token_count_failed' if failure == 'token_count_failed'
                                         else 'model_response_too_large')
                data.extend(part)
        try:
            return json_object(bytes(data))
        except (ValueError, RecursionError):
            raise ModelCallError('token_count_failed' if failure == 'token_count_failed'
                                 else 'invalid_model_response') from None
    except httpx.TimeoutException:
        raise
    except (httpx.HTTPError, ValueError):
        raise ModelCallError(failure) from None


def _output_object(response: dict) -> dict:
    if response.get('status') == 'incomplete' or response.get('incomplete_details') is not None:
        raise ModelCallError('model_incomplete')
    output = response.get('output')
    if (response.get('object') != 'response' or response.get('status') != 'completed'
            or response.get('error') is not None or not isinstance(output, list)):
        raise ModelCallError('invalid_model_response')

    text = None
    for item in output:
        if not isinstance(item, dict):
            raise ModelCallError('invalid_model_response')
        if (item.get('type') == 'reasoning' and text is None and item.get('status') in (None, 'completed')
                and item.keys() <= {'type', 'id', 'status', 'summary', 'content', 'encrypted_content'}):
            # Opaque reasoning metadata may precede the one assistant message. Never use it as output.
            continue
        content = item.get('content')
        if (text is not None or item.get('type') != 'message' or item.get('role') != 'assistant'
                or item.get('status') != 'completed' or not isinstance(content, list) or len(content) != 1
                or not isinstance(content[0], dict)):
            raise ModelCallError('invalid_model_response')
        part = content[0]
        if part.get('type') == 'refusal':
            raise ModelCallError('model_refusal')
        if (part.get('type') != 'output_text' or not isinstance(part.get('text'), str)
                or part.keys() - {'type', 'text', 'annotations', 'logprobs'}
                or part.get('annotations') not in (None, [])):
            raise ModelCallError('invalid_model_response')
        text = part['text']
    if text is None:
        raise ModelCallError('invalid_model_response')
    try:
        return json_object(text)
    except (ValueError, RecursionError):
        raise ModelCallError('invalid_model_json') from None
