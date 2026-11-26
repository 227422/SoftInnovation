import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from campus_backend.classification.adapters.responses import ResponsesConfig, ResponsesModel
from campus_backend.classification.extraction import process
from campus_backend.classification.ports import ModelCallError
from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.facts_input import build_document_bundle


TEXT = '全体本科生可申请本奖学金。无额外申请条件。'
CANDIDATE_ID = 'initial-candidate-only'
INDEPENDENT_ID = 'independent-candidate-only'


def public_document():
    return build_document_bundle(make_artifact(
        'document', 'synthetic-n1', 'v1',
        {'title': '奖学金申请', 'source_url': 'https://example.edu.cn/1',
         'body_status': 'complete', 'content': TEXT,
         'cookie': 'private-cookie', 'local_path': 'private-path'},
    ))


def extracted(document, action_id=CANDIDATE_ID, *, quote=TEXT):
    return {
        'actions': [{'id': action_id, 'main': True, 'kind': 'scholarship_application',
                     'student_scope': 'undergraduate', 'text': TEXT, 'evidence_ids': ['e-1']}],
        'requirements': {'complete': True},
        'benefit_conditions': {'complete': True},
        'evidence_refs': [{'evidence_id': 'e-1', 'source_kind': 'notice',
                           'source_id': document.notice_id, 'source_content_version': document.content_version,
                           'source_url': document.source_url,
                           'locator': {'segment_id': document.segments[1].id}, 'quote': quote}],
    }


def comparison(action_id=CANDIDATE_ID, *, missing=()):
    return {
        'checks': [{'field_path': 'actions', 'candidate_id': action_id, 'source_ok': True,
                    'semantic_status': 'supported', 'relation_complete': True, 'support_refs': ['e-1'],
                    'counter_refs': [], 'unresolved_conflict': False, 'reason_code': 'supported_by_text'}],
        'coverage_complete': True,
        'missing_facts': list(missing),
    }


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, request, *, timeout_seconds=60):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_complete_flow_independently_reads_document_then_compares():
    document = public_document()
    model = ScriptedModel(extracted(document), extracted(document, INDEPENDENT_ID), comparison())

    outcome = process(document, model)

    assert outcome.facts.complete and outcome.facts.category == 'financial_aid'
    assert outcome.facts.actions[0].id == CANDIDATE_ID
    assert outcome.facts.checks.input_fingerprint == document.input_fingerprint
    assert outcome.facts.checks.candidate_digest == outcome.facts.candidate_digest
    assert [request.stage for request in model.requests] == ['extract', 'independent', 'compare']
    for request in model.requests:
        assert 'JSON' in request.system and '非可信' in request.system
        assert json.loads(request.user)['document']['segments'][1]['text'] == TEXT
        assert 'private-cookie' not in request.user and 'private-path' not in request.user
        assert 'output_schema' in json.loads(request.user)
    assert CANDIDATE_ID not in model.requests[1].user
    assert CANDIDATE_ID in model.requests[2].user and INDEPENDENT_ID in model.requests[2].user
    assert len({request.fingerprint for request in model.requests}) == 3


def test_missing_facts_override_complete_and_get_one_repair():
    document = public_document()
    model = ScriptedModel(
        extracted(document), extracted(document, INDEPENDENT_ID), comparison(missing=['遗漏第二批日期']),
        extracted(document, 'repaired'), extracted(document, INDEPENDENT_ID),
        comparison('repaired', missing=['仍有缺口']),
    )

    outcome = process(document, model)

    assert [request.stage for request in model.requests] == [
        'extract', 'independent', 'compare', 'repair', 'independent', 'compare',
    ]
    assert '遗漏第二批日期' in model.requests[3].user
    assert 'repaired' not in model.requests[4].user
    assert outcome.facts.checks.missing_facts == ('仍有缺口',)
    assert outcome.facts.checks.coverage_complete is False
    assert outcome.facts.complete is False


def test_local_verifier_rejects_unmatched_quote_even_when_model_approves():
    document = public_document()
    model = ScriptedModel(extracted(document, quote='原文中没有这一句'),
                          extracted(document, INDEPENDENT_ID), comparison())

    outcome = process(document, model, allow_repair=False)

    assert not outcome.facts.complete
    assert not outcome.facts.actions
    assert 'unverified_evidence' in {gap.reason_code for gap in outcome.facts.gaps}


def test_repair_error_retains_previously_verified_local_facts():
    document = public_document()
    model = ScriptedModel(extracted(document), extracted(document), comparison(missing=['遗漏']),
                          ModelCallError('model_timeout'))

    outcome = process(document, model)

    assert outcome.error_code == 'model_timeout'
    assert outcome.facts.actions[0].id == CANDIDATE_ID
    assert not outcome.facts.complete


def test_model_cannot_supply_own_binding():
    document = public_document()
    model = ScriptedModel(extracted(document) | {'input_fingerprint': 'f' * 64})

    with pytest.raises(ModelCallError, match='invalid_extraction') as exc:
        process(document, model)

    assert str(exc.value) == 'invalid_extraction'


def test_independent_unknown_graphs_cannot_mark_full_coverage():
    document = public_document()
    independent = extracted(document, INDEPENDENT_ID)
    independent.pop('requirements')
    model = ScriptedModel(extracted(document), independent, comparison())

    outcome = process(document, model, allow_repair=False)

    assert outcome.facts.checks.coverage_complete is False
    assert not outcome.facts.complete


def config(context_limit=15001):
    return ResponsesConfig(base_url='https://responses.example/v1', model='configured-model',
                           context_limit=context_limit, api_key='secret-key')


def api_response(text='{"answer":"ok"}'):
    return {
        'object': 'response', 'status': 'completed', 'error': None, 'incomplete_details': None,
        'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}],
    }


def test_responses_counts_same_input_before_one_generation():
    seen = []

    def handle(request):
        assert request.headers['authorization'] == 'Bearer secret-key'
        seen.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 12000})
        response = api_response()
        response['output'].insert(0, {'type': 'reasoning', 'summary': [], 'id': 'rs_test'})
        return httpx.Response(200, json=response)

    model = ResponsesModel(config(), transport=httpx.MockTransport(handle))

    assert model.complete(_request()) == {'answer': 'ok'}
    assert [item[0] for item in seen] == ['/v1/responses/input_tokens', '/v1/responses']
    count, generate = [item[1] for item in seen]
    assert generate == count | {'max_output_tokens': 3000, 'store': False}
    assert generate['text'] == {'format': {'type': 'json_object'}}
    assert generate['truncation'] == 'disabled'
    assert 'tools' not in generate and 'previous_response_id' not in generate
    assert generate['model'] == 'configured-model'
    assert generate['input'][1]['content'] == '{"key":"全文，不截断"}'
    assert 'secret-key' not in repr(config()) and 'secret-key' not in repr(model)


def _request():
    from campus_backend.classification.ports import ModelRequest
    return ModelRequest(stage='extract', system='Return JSON.', user='{"key":"全文，不截断"}')


@pytest.mark.parametrize(('tokens', 'limit', 'expected'), [
    (12001, 20000, 'context_limit'), (12000, 15000, 'context_limit'),
    (True, 20000, 'token_count_failed'), (0, 20000, 'token_count_failed'),
])
def test_bad_count_or_context_limit_prevents_generation(tokens, limit, expected):
    def handle(request):
        assert request.url.path.endswith('/input_tokens')
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': tokens})

    model = ResponsesModel(config(limit), transport=httpx.MockTransport(handle))
    with pytest.raises(ModelCallError, match=expected):
        model.complete(_request())


@pytest.mark.parametrize(('body', 'code'), [
    (api_response() | {'status': 'incomplete'}, 'model_incomplete'),
    (api_response() | {'output': [{'type': 'function_call', 'arguments': '{}'}]}, 'invalid_model_response'),
    (api_response() | {'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                                  'content': [{'type': 'refusal', 'refusal': 'secret-key'}]}]}, 'model_refusal'),
    (api_response() | {'output': api_response()['output'] * 2}, 'invalid_model_response'),
    (api_response('{"x":1,"x":2}'), 'invalid_model_json'),
    (api_response('{"x":NaN}'), 'invalid_model_json'),
    (api_response('{"x":1e9999}'), 'invalid_model_json'),
    (api_response('{"x":"\\ud800"}'), 'invalid_model_json'),
    (api_response('["not object"]'), 'invalid_model_json'),
    (api_response('{"x":"' + 'a' * (256 * 1024) + '"}'), 'model_response_too_large'),
])
def test_generation_rejects_unsafe_shape_or_json(body, code):
    def handle(request):
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        return httpx.Response(200, json=body)

    model = ResponsesModel(config(), transport=httpx.MockTransport(handle))
    with pytest.raises(ModelCallError, match=code) as exc:
        model.complete(_request())
    assert 'secret-key' not in str(exc.value)


def test_count_redirect_is_never_followed_and_error_is_sanitized():
    requests = []

    def handle(request):
        requests.append(request.url.host)
        return httpx.Response(307, headers={'location': 'https://redirect.example/secret-key'})

    model = ResponsesModel(config(), transport=httpx.MockTransport(handle))
    with pytest.raises(ModelCallError, match='token_count_failed') as exc:
        model.complete(_request())
    assert requests == ['responses.example']
    assert str(exc.value) == 'token_count_failed'


def test_one_timeout_covers_count_and_generation_together():
    stages = []

    async def handle(request):
        stages.append(request.url.path)
        await asyncio.sleep(0.05)
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        return httpx.Response(200, json=api_response())

    model = ResponsesModel(config(), transport=httpx.MockTransport(handle))
    with pytest.raises(ModelCallError, match='model_timeout'):
        model.complete(_request(), timeout_seconds=0.08)
    assert stages == ['/v1/responses/input_tokens', '/v1/responses']



def test_responses_allows_two_concurrent_calls_per_process():
    entered = 0
    guard = threading.Lock()
    two_inside = threading.Event()
    third_inside = threading.Event()
    release = threading.Event()

    async def handle(request):
        nonlocal entered
        if request.url.path.endswith('/input_tokens'):
            with guard:
                entered += 1
                if entered == 2:
                    two_inside.set()
                elif entered == 3:
                    third_inside.set()
            await asyncio.to_thread(release.wait)
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        return httpx.Response(200, json=api_response())

    def call():
        return ResponsesModel(config(), transport=httpx.MockTransport(handle)).complete(_request())

    with ThreadPoolExecutor(max_workers=3) as pool:
        calls = [pool.submit(call) for _ in range(3)]
        try:
            assert two_inside.wait(2)
            assert not third_inside.wait(0.15)
        finally:
            release.set()
        assert all(result.result(timeout=2) == {'answer': 'ok'} for result in calls)


def test_response_rejects_tool_annotation_even_when_text_is_valid_json():
    body = api_response()
    body['output'][0]['content'][0]['annotations'] = [
        {'type': 'url_citation', 'url': 'https://example.edu.cn/other'},
    ]

    def handle(request):
        if request.url.path.endswith('/input_tokens'):
            return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})
        return httpx.Response(200, json=body)

    with pytest.raises(ModelCallError, match='invalid_model_response'):
        ResponsesModel(config(), transport=httpx.MockTransport(handle)).complete(_request())


def test_timeout_does_not_wait_for_cancelled_network_lookup_to_finish():
    from time import monotonic, sleep

    async def handle(request):
        await asyncio.to_thread(sleep, 0.40)
        return httpx.Response(200, json={'object': 'response.input_tokens', 'input_tokens': 100})

    model = ResponsesModel(config(), transport=httpx.MockTransport(handle))
    start = monotonic()
    with pytest.raises(ModelCallError, match='model_timeout'):
        model.complete(_request(), timeout_seconds=0.05)
    assert monotonic() - start < 0.30
