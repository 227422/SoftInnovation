"""Explicit offline synthetic model replay for the fact-processing CLI."""

import hashlib
import re
from pathlib import Path
from threading import local

from ..json_io import json_object
from ..ports import ModelCallError, ModelRequest
from ..prompts import IDENTITY_FIELDS
from ..run_contract import FactRunError


_MAX_FIXTURE_BYTES = 2 * 1024 * 1024
_STAGES = ('extract', 'independent', 'compare', 'repair', 'independent', 'compare')


class ReplayModel:
    def __init__(self, path: Path):
        try:
            if not Path(path).is_file():
                raise ValueError
            with Path(path).open('rb') as handle:
                data = handle.read(_MAX_FIXTURE_BYTES + 1)
            if len(data) > _MAX_FIXTURE_BYTES:
                raise ValueError
            fixture = json_object(data)
            identity = fixture.get('document_identity')
            responses = fixture.get('responses')
            if (fixture.keys() != {'synthetic', 'document_identity', 'responses'} or fixture['synthetic'] is not True
                    or not isinstance(identity, dict) or identity.keys() != set(IDENTITY_FIELDS)
                    or not all(isinstance(value, str) and value for value in identity.values())
                    or not isinstance(responses, list) or not 1 <= len(responses) <= len(_STAGES)
                    or any(not isinstance(item, dict) or item.keys() != {'stage', 'request_fingerprint', 'output'}
                           or item['stage'] != stage or not isinstance(item['output'], dict)
                           or not isinstance(item['request_fingerprint'], str)
                           or not re.fullmatch(r'[0-9a-f]{64}', item['request_fingerprint'])
                           for item, stage in zip(responses, _STAGES))):
                raise ValueError
        except (OSError, ValueError, RecursionError):
            raise FactRunError('invalid_replay') from None
        self.fingerprint = hashlib.sha256(data).hexdigest()
        self._identity = identity
        self._responses = responses
        self._session = local()

    def complete(self, request: ModelRequest, *, timeout_seconds: float = 60) -> dict:
        # Every processing attempt starts with extract, including in a reused CLI worker.
        index = 0 if request.stage == 'extract' else getattr(self._session, 'index', 0)
        document = json_object(request.user)['document']
        if (any(document[field] != expected for field, expected in self._identity.items())
                or index >= len(self._responses)):
            raise ModelCallError('invalid_replay')
        response = self._responses[index]
        if response['stage'] != request.stage or response['request_fingerprint'] != request.fingerprint:
            raise ModelCallError('invalid_replay')
        self._session.index = index + 1
        return response['output']
