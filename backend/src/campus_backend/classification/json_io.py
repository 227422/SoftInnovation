"""Strict JSON parsing shared by the model and local run boundaries."""

import json
import math


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError('non-finite JSON number')


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number')
    return value


def compact_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def json_object(data: bytes | str) -> dict:
    if isinstance(data, bytes):
        data = data.decode('utf-8')
    value = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant,
                       parse_float=_finite_float)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    # JSON escapes can decode to lone surrogates that cannot be persisted or transmitted as UTF-8.
    compact_json(value).encode('utf-8')
    return value
