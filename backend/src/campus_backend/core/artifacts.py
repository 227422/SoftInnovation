"""Versioned, provider-neutral stage data and content-addressed original assets."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

STAGES = {'raw', 'document', 'analysis', 'enhancement', 'personal_result'}
STATUSES = {'complete', 'partial', 'title_only', 'failed', 'skipped'}


def make_artifact(stage, notice_id, content_version, payload, *, status='complete', errors=None,
                  input_refs=None, producer=None, now=None, run_id=None):
    value = {'schema_version': '1.0', 'stage': stage, 'notice_id': notice_id,
             'content_version': content_version, 'run_id': run_id or uuid4().hex,
             'created_at': (now or datetime.now(timezone.utc)).isoformat(),
             'producer': producer or {'name': f'campus.{stage}', 'version': '1.0'},
             'status': status, 'errors': errors or [], 'input_refs': input_refs or [], 'payload': payload}
    return validate_artifact(value)


def validate_artifact(value, expected_stage=None):
    if not isinstance(value, dict) or value.get('schema_version') != '1.0':
        raise ValueError('Unsupported artifact schema version')
    if value.get('stage') not in STAGES or (expected_stage and value['stage'] != expected_stage):
        raise ValueError('Unexpected artifact stage')
    for field in ('notice_id', 'content_version', 'run_id', 'created_at'):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f'Missing artifact {field}')
    try:
        if datetime.fromisoformat(value['created_at']).tzinfo is None:
            raise ValueError('Artifact time must include timezone')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid artifact time') from exc
    if value.get('status') not in STATUSES or not isinstance(value.get('payload'), dict):
        raise ValueError('Invalid artifact status/payload')
    producer = value.get('producer')
    if not isinstance(producer, dict) or not all(isinstance(producer.get(k), str) and producer[k] for k in ('name', 'version')):
        raise ValueError('Invalid artifact producer')
    if not isinstance(value.get('errors'), list) or not isinstance(value.get('input_refs'), list):
        raise ValueError('Invalid artifact errors/references')
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError('Artifact must contain finite JSON data') from exc
    return value


def _atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_artifact(path, value):
    validate_artifact(value)
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'))


def read_artifact(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Artifact exceeds 64 MiB')
    return validate_artifact(json.loads(path.read_text(encoding='utf-8')))


class AssetStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def put(self, data, *, filename, media_type, url=None):
        digest = hashlib.sha256(data).hexdigest()
        relative = f'{digest[:2]}/{digest}'
        path = self.root / relative
        if not path.exists():
            _atomic_write(path, data)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Stored original asset failed integrity check')
        return {'asset_id': digest, 'path': relative, 'sha256': digest, 'media_type': media_type,
                'filename': Path(filename).name, 'url': url, 'size': len(data), 'status': 'complete'}

    def read(self, asset):
        path = (self.root / asset['path']).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Asset path leaves its storage root')
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Asset exceeds 32 MiB')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset['sha256']:
            raise ValueError('Asset checksum mismatch')
        return data
