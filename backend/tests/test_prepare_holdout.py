from scripts.quality.prepare_holdout import near_title, prepare, title_key, url_key

import json
import pytest


def test_normalization_keeps_notice_identifiers_and_distinct_years():
    assert url_key('http://Example.edu/item/?JL=abc&utm_source=test') == 'https://example.edu/item?JL=abc'
    assert not near_title(title_key('关于2026届毕业生考试报名的通知'), title_key('关于2027届毕业生考试报名的通知'))


def test_holdout_keeps_identifiable_failures_and_excludes_dev_urls():
    def row(i, title, status):
        return {
            'kind': 'source', 'source_id': f's{i}', 'unit_id': 'u', 'status': 'parsed',
            'first_item': {'url': f'https://example.edu/{i}', 'title': title},
            'detail': {'status': status},
        }

    registry = {
        'units': [{'unit_id': 'u', 'unit_type': 'education'}],
        'sources': [{'source_id': f's{i}', 'unit_id': 'u', 'url': 'https://example.edu/list',
                     'name': '考试通知', 'status': 'enabled'} for i in (1, 2, 3)],
    }
    audit = [
        row(1, '学生期末报名通知', 'access_restricted'),
        row(2, '学生入学报到通知', 'parsed_body'),
        row(3, '', 'url_missing'),
    ]
    result = prepare(audit, registry, {'https://example.edu/2'}, set())
    assert [r['audit_status'] for r in result['selected']] == ['access_restricted']
    assert {r['reason'] for r in result['exclusions']} == {
        'development_overlap_or_quarantine', 'no_identifiable_notice',
    }
    assert result == prepare(list(reversed(audit)), registry, {'https://example.edu/2'}, set())


def test_final_selection_stops_at_stratum_cap_without_transferring():
    from scripts.quality.prepare_holdout import select

    rows = [
        {'rank': str(i), 'stratum': 'general', 'unit_id': 'u', 'source_id': str(i),
         'media_lane': 'unknown', 'staff_only_channel': False}
        for i in range(3)
    ]
    chosen, standby, delta = select(rows, {'general': 1, 'aid': 1}, permit_transfer=False)
    assert len(chosen) == 1
    assert len(standby) == 2
    assert delta == {'general': 0, 'aid': 1}


def test_close_title_does_not_drop_temporal_grade_boundaries():
    title = title_key('关于2026年第2批转专业名单公示')
    assert near_title(title, title_key('关于2026年第2批转专业名单的公示'))
    assert not near_title(title, title_key('关于2026年第3批转专业名单公示'))


def test_list_title_fallback_only_assigns_unambiguous_non_staff_general_channels():
    rows = [
        {'kind': 'source', 'source_id': f's{i}', 'unit_id': 'u', 'status': 'listed',
         'first_item': {'url': f'https://example.edu/{i}', 'title': title}}
        for i, title in enumerate(('学生奖学金申请', '大赛和奖学金', '教师奖学金申请', '学生竞赛入选名单'))
    ]
    sources = [
        {'source_id': f's{i}', 'unit_id': 'u', 'name': name, 'url': f'https://example.edu/list/{i}',
         'status': 'enabled'}
        for i, name in enumerate(('通知', '通知', '教师发展', '教务信息'))
    ]
    result = prepare(rows, {'sources': sources, 'units': [{'unit_id': 'u', 'unit_type': 'education'}]},
                     set(), set(), list_title_patterns={'innovation': '竞赛|大赛', 'aid': '奖学金'})
    assert {r['source_id']: r['stratum'] for r in result['selected']} == {
        's0': 'aid', 's1': 'general', 's2': 'general', 's3': 'daily',
    }


def test_frozen_list_binding_requires_actual_title_with_matching_hash():
    import pytest
    from scripts.quality.prepare_holdout import bind_title, digest

    title = '关于本科生报名的通知'
    row = {'url': 'https://example.edu/a', 'title_sha256': digest(title_key(title).encode())}
    entry = {'title': title, 'url': row['url']}
    assert bind_title(row, entry)['title'] == title
    with pytest.raises(ValueError):
        bind_title(row, entry | {'title': title_key(title) + '其他'})


def redirect_audit(*, second_hash='2' * 64, final_updates=None):
    rows, sources = [], []
    for i, title in enumerate(('本科选课登记', '校级奖助申请'), 1):
        url, final = f'https://example.edu/{i}', f'https://example.edu/final/{i}'
        response = {'url': final, 'http_status': 200, 'truncated': False,
                    'sha256': '1' * 64 if i == 1 else second_hash, 'media_type': 'text/html'}
        if final_updates:
            response.update(final_updates)
        rows.append({'kind': 'source', 'source_id': f's{i}', 'unit_id': 'u', 'status': 'parsed',
            'first_item': {'url': url, 'title': title},
            'detail': {'status': 'parsed_body', 'final_url': final,
                       'responses': [{'url': url, 'http_status': 302, 'sha256': 'a' * 64,
                                      'truncated': False}, response]}})
        sources.append({'source_id': f's{i}', 'unit_id': 'u', 'url': 'https://example.edu/list',
                        'name': '考试通知', 'status': 'enabled'})
    return rows, {'sources': sources, 'units': [{'unit_id': 'u', 'unit_type': 'education'}]}


def test_redirect_shell_hash_does_not_merge_distinct_final_notice_bodies():
    rows, registry = redirect_audit()
    result = prepare(rows, registry, set(), set())
    assert len(result['selected']) == 2
    assert not result['exclusions']


def test_identical_confirmed_final_bodies_are_still_deduplicated():
    rows, registry = redirect_audit(second_hash='1' * 64)
    result = prepare(rows, registry, set(), set())
    assert len(result['selected']) == 1
    assert result['exclusions'][0]['reason'] == 'duplicate'


@pytest.mark.parametrize('final_updates', [
    {'url': 'https://example.edu/unrelated'}, {'http_status': 302},
    {'http_status': 206}, {'truncated': True}, {'sha256': 'not-a-hash'},
])
def test_unverified_final_response_is_not_used_for_body_deduplication(final_updates):
    rows, registry = redirect_audit(second_hash='1' * 64, final_updates=final_updates)
    assert len(prepare(rows, registry, set(), set())['selected']) == 2


@pytest.fixture
def frozen_collection(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import scripts.quality.prepare_holdout as module
    from campus_backend.collection.service import CollectionService, title_only
    from campus_backend.core.artifacts import AssetStore, write_artifact

    sources = [{'source_id': f's{i}', 'unit_id': 'u', 'name': '本科通知',
                'school_id': 'csu', 'url': 'https://example.edu/list', 'allowed_hosts': ['example.edu']}
               for i in (1, 2)]
    items = [{'url': f'https://example.edu/{i}', 'title': f'本科课程第{i}次报名通知',
              'published_at': '2026-11-13'} for i in (1, 2)]
    rows = [{'candidate_id': module.digest(module.url_key(item['url']).encode()),
             'source_id': source['source_id'], 'unit_id': 'u', 'url': item['url'],
             'title_sha256': module.digest(module.title_key(item['title']).encode()),
             'published_at': item['published_at']} for source, item in zip(sources, items)]
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'sources': sources}))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'REGISTRY', registry)
    plan = {'purpose': 'frozen_holdout_candidates', 'selected': rows,
            'input_sha256': {'registry.json': module.digest(registry.read_bytes())}}
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan))
    plan_hash = module.digest(plan_path.read_bytes())
    titles = tmp_path / 'titles.json'
    titles.write_text(json.dumps({'plan_sha256': plan_hash,
                                 'items': {row['candidate_id']: item for row, item in zip(rows, items)}}))
    output = tmp_path / 'collected'
    output.mkdir()
    (output / 'checkpoints').mkdir()
    store = AssetStore(output / 'assets')
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)

    class MemoryHTTP:
        def get(self, url, allowed_hosts, **kwargs):
            return {'url': url, 'data': '<div id="vsb_content">本科生报名。</div>'.encode(),
                    'headers': {}, 'media_type': 'text/html', 'status': 200}

    records = []
    for i, (source, item, row) in enumerate(zip(sources, items, rows)):
        raw = (CollectionService(MemoryHTTP(), store).article(source, item, now=now) if i == 0 else
               title_only(source, item, code='network_error', message='offline', now=now))
        path = 'raw/' + row['candidate_id'] + '.json'
        write_artifact(output / path, raw)
        record = {'candidate_id': row['candidate_id'], 'source_id': source['source_id'],
                  'notice_id': raw['notice_id'], 'content_version': raw['content_version'],
                  'file': path, 'sha256': module.digest((output / path).read_bytes()),
                  'status': raw['status'], 'responses': [], 'assets': raw['payload']['assets'],
                  'errors': [error['code'] for error in raw['errors']]}
        records.append(record)
        (output / 'checkpoints' / (row['candidate_id'] + '.json')).write_text(json.dumps(record))
    calls = []

    class OfflineHTTP:
        def __init__(self, **kwargs):
            pass

        def get(self, *args, **kwargs):
            calls.append(args)
            raise AssertionError('valid checkpoint must not fetch again')

        def close(self):
            pass

    monkeypatch.setattr('campus_backend.collection.http.PublicHTTPClient', OfflineHTTP)
    return SimpleNamespace(module=module, output=output, plan_path=plan_path, plan_hash=plan_hash,
                           titles=titles, rows=rows, sources=sources, records=records, calls=calls, store=store)


def save_checkpoint(state, index, record):
    target = state.output / 'checkpoints' / (state.rows[index]['candidate_id'] + '.json')
    target.write_text(json.dumps(record))


def resume(state):
    state.module.collect_frozen(state.plan_path, state.plan_hash, state.output, state.titles)


def test_valid_checkpoint_resume_is_offline_and_keeps_failed_candidate(frozen_collection):
    state = frozen_collection
    protected = [state.plan_path, state.titles,
                 *(state.output / row['file'] for row in state.records),
                 *sorted((state.output / 'checkpoints').glob('*.json'))]
    before = {path: path.read_bytes() for path in protected}
    resume(state)
    manifest = json.loads((state.output / 'manifest.json').read_text())
    assert [r['candidate_id'] for r in manifest['items']] == [r['candidate_id'] for r in state.rows]
    assert [r['status'] for r in manifest['items']] == ['complete', 'title_only']
    assert manifest['items'][1]['errors'] == ['network_error']
    assert state.calls == []
    assert all(path.read_bytes() == data for path, data in before.items())


def test_copied_checkpoint_cannot_replace_another_frozen_candidate(frozen_collection):
    state = frozen_collection
    save_checkpoint(state, 0, state.records[1])
    with pytest.raises(ValueError):
        resume(state)
    assert not (state.output / 'manifest.json').exists()


@pytest.mark.parametrize(('field', 'value'), [
    ('source_id', 'wrong-source'), ('notice_id', 'wrong-notice'),
    ('content_version', 'f' * 64), ('status', 'title_only'), ('assets', []), ('errors', ['different-error']),
])
def test_checkpoint_metadata_must_match_raw_and_candidate(frozen_collection, field, value):
    state = frozen_collection
    save_checkpoint(state, 0, state.records[0] | {field: value})
    with pytest.raises(ValueError):
        resume(state)


@pytest.mark.parametrize('mutation', ['empty', 'stage', 'url', 'title', 'source', 'version'])
def test_hash_correct_raw_still_requires_frozen_identity_and_semantic_version(frozen_collection, mutation):
    state = frozen_collection
    record = state.records[0].copy()
    path = state.output / record['file']
    raw = json.loads(path.read_text())
    if mutation == 'empty':
        raw = {}
    elif mutation == 'stage':
        raw['stage'] = 'document'
    elif mutation == 'version':
        raw['content_version'] = record['content_version'] = 'f' * 64
    else:
        raw['payload'][{'url': 'source_url', 'title': 'title', 'source': 'source_id'}[mutation]] = 'wrong'
    path.write_text(json.dumps(raw))
    record['sha256'] = state.module.digest(path.read_bytes())
    save_checkpoint(state, 0, record)
    with pytest.raises(ValueError):
        resume(state)


def test_resume_revalidates_current_frozen_listing_title_binding(frozen_collection):
    state = frozen_collection
    titles = json.loads(state.titles.read_text())
    titles['items'][state.rows[0]['candidate_id']]['title'] = '另一个真实通知'
    state.titles.write_text(json.dumps(titles))
    with pytest.raises(ValueError):
        resume(state)


@pytest.mark.parametrize('escape', ['relative', 'absolute', 'symlink'])
def test_checkpoint_raw_path_cannot_escape_collection_directory(frozen_collection, escape):
    state = frozen_collection
    record = state.records[0].copy()
    path = state.output / record['file']
    outside = state.output.parent / 'other.json'
    outside.write_bytes(path.read_bytes())
    if escape == 'symlink':
        path.unlink()
        path.symlink_to(outside)
    else:
        record['file'] = '../other.json' if escape == 'relative' else str(outside)
    save_checkpoint(state, 0, record)
    with pytest.raises(ValueError):
        resume(state)


def test_checkpoint_assets_are_verified_before_resuming(frozen_collection):
    state = frozen_collection
    asset = state.records[0]['assets'][0]
    (state.output / 'assets' / asset['path']).write_bytes(b'changed original')
    with pytest.raises(ValueError):
        resume(state)


def test_checkpoint_response_originals_are_verified_even_when_not_raw_attachments(frozen_collection):
    state = frozen_collection
    asset = state.store.put(b'redirect response', filename='response', media_type='text/html',
                            url='https://example.edu/redirect')
    save_checkpoint(state, 0, state.records[0] | {'responses': [asset | {'http_status': 302}]})
    (state.output / 'assets' / asset['path']).write_bytes(b'changed redirect')
    with pytest.raises(ValueError):
        resume(state)


def test_resume_only_collects_missing_candidate_and_retains_its_network_failure(frozen_collection, monkeypatch):
    from campus_backend.collection.http import FetchError

    state = frozen_collection
    (state.output / 'checkpoints' / (state.rows[1]['candidate_id'] + '.json')).unlink()
    calls = []

    class UnavailableHTTP:
        def __init__(self, **kwargs):
            pass

        def get(self, url, allowed_hosts, **kwargs):
            calls.append(url)
            raise FetchError('network_error', 'offline')

        def close(self):
            pass

    monkeypatch.setattr('campus_backend.collection.http.PublicHTTPClient', UnavailableHTTP)
    resume(state)
    manifest = json.loads((state.output / 'manifest.json').read_text())
    assert calls == [state.rows[1]['url']]
    assert [row['candidate_id'] for row in manifest['items']] == [row['candidate_id'] for row in state.rows]
    assert manifest['items'][1]['status'] == 'title_only'
    assert manifest['items'][1]['errors'] == ['network_error']
    resume(state)
    assert calls == [state.rows[1]['url']]


def test_hash_correct_asset_symlink_still_cannot_escape_collection_directory(frozen_collection):
    state = frozen_collection
    path = state.output / 'assets' / state.records[0]['assets'][0]['path']
    outside = state.output.parent / 'outside-original'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        resume(state)


def test_checkpoint_file_itself_cannot_be_a_symlink_to_another_directory(frozen_collection):
    state = frozen_collection
    path = state.output / 'checkpoints' / (state.rows[0]['candidate_id'] + '.json')
    outside = state.output.parent / 'outside-checkpoint.json'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        resume(state)
