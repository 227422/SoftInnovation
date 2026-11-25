import json
from pathlib import Path

import pytest


def test_artifact_roundtrip_and_invalid_contract(tmp_path):
    from campus_backend.core.artifacts import make_artifact, read_artifact, write_artifact, validate_artifact
    original = make_artifact('raw', 'n1', 'v1', {'title': '通知', 'assets': []})
    write_artifact(tmp_path / 'raw.json', original)
    assert read_artifact(tmp_path / 'raw.json') == original
    assert validate_artifact(original, 'raw') == original
    for change in ({'schema_version': '99'}, {'notice_id': ''}, {'payload': []}, {'stage': 'executable'}):
        with pytest.raises(ValueError):
            validate_artifact(original | change)
    with pytest.raises(ValueError):
        validate_artifact(original, 'document')


def test_assets_are_immutable_and_paths_cannot_escape(tmp_path):
    from campus_backend.core.artifacts import AssetStore
    store = AssetStore(tmp_path)
    record = store.put(b'example', filename='../../a.txt', media_type='text/plain', url='https://csu.edu.cn/a')
    assert store.read(record) == b'example'
    assert store.put(b'example', filename='a.txt', media_type='text/plain')['path'] == record['path']
    with pytest.raises(ValueError):
        store.read(record | {'path': '../outside'})
    (tmp_path / record['path']).write_bytes(b'tampered')
    with pytest.raises(ValueError):
        store.read(record)
