"""Preregistered Qwen transfer school isolation, native-layer equivalence and safe reload."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/quality'))


def test_preregistered_model_and_data_are_bound():
    path = ROOT / 'docs/quality/training/v12-transfer-protocol.json'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '70cbe62e6fae66fc28e13338ad5c7f3676d50bf351868b20a7b6bbba39a0357e'
    assert json.loads(path.read_bytes())['population']['total'] == 2675


def test_fit_supplements_follow_the_fit_schools():
    from v12_training import with_supplement
    rows = [{'university': school} for school in ['甲', '乙', '丙', '甲', '乙', '丙']]
    assert with_supplement(rows, 3, [2, 0]) == [2, 0, 3, 5]


def test_text_allocation_keeps_title_evidence_and_end():
    from v12_encoder import token_ids

    class CharacterTokenizer:
        eos_token_id = -1

        def encode(self, value, add_special_tokens=False):
            return list(map(ord, value))

    ids = token_ids(CharacterTokenizer(), '题' * 100, '首' * 200 + '。申请对象为本科生。' + '末' * 100)
    assert ids[:48] == [ord('题')] * 48 and ids[-25:] == [ord('末')] * 24 + [-1]
    assert '申请对象为本科生' in ''.join(map(chr, ids[:-1]))
    assert len(ids) <= 206


def test_zero_adapters_reproduce_original_and_learn_from_labels():
    torch = pytest.importorskip('torch')
    from transformers import Qwen3Config, Qwen3Model
    from v12_layers import TransferTail
    from v12_encoder import cached_residuals

    torch.manual_seed(9)
    cfg = Qwen3Config(vocab_size=40, hidden_size=32, intermediate_size=48, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, head_dim=8)
    model = Qwen3Model(cfg).eval()
    texts = [[11, 17, 8], [5, 6]]
    residual = cached_residuals(model, texts, 0, 'cpu')
    with torch.no_grad():
        targets = torch.stack([model(torch.tensor([seq]), use_cache=False).last_hidden_state[0, -1]
                               for seq in texts])
    tail = TransferTail(model.layers[-1].mlp, model.layers[-1].post_attention_layernorm, model.norm)
    expected = torch.nn.functional.normalize(targets)
    assert torch.allclose(tail.features(residual), expected, atol=2e-5)
    original = {k: v.clone() for k, v in model.layers[-1].mlp.state_dict().items()}
    loss = torch.nn.functional.cross_entropy(tail(residual), torch.tensor([0, 3]))
    loss.backward()
    assert all(getattr(tail, name).b.grad.abs().sum() > 0 for name in ('gate', 'up', 'down'))
    opt = torch.optim.AdamW([p for p in tail.parameters() if p.requires_grad], lr=.01)
    opt.step()
    assert all(torch.equal(p, original[k]) for k, p in model.layers[-1].mlp.state_dict().items())
    assert not torch.allclose(tail.features(residual), expected, atol=2e-5)


def test_replay_rejects_metadata_before_opening_any_model(tmp_path):
    from v12_classifier import predict
    with pytest.raises(ValueError, match='only case_id, title and body'):
        predict([dict(case_id='x', title='校赛', body='比赛', university='学校')], tmp_path / 'missing', 'bad')


def test_replication_gate_requires_both_accuracy_and_near_baseline():
    from v12_experiment import replicated
    assert replicated(dict(total=100, correct=94), dict(total=100, correct=96))
    assert not replicated(dict(total=100, correct=93), dict(total=100, correct=93))
    assert not replicated(dict(total=100, correct=95), dict(total=100, correct=98))


def test_unsafe_transfer_tensors_do_not_reload(tmp_path):
    torch = pytest.importorskip('torch')
    from safetensors.torch import save_file
    from v12_layers import load_updates
    head = torch.nn.Linear(3, 4)
    file = tmp_path / 'candidate.safetensors'
    save_file(dict(weight=torch.zeros(4, 3), bias=torch.full((4,), float('nan'))), str(file))
    with pytest.raises(ValueError, match='invalid transfer parameters'):
        load_updates(head, file)


def test_postfreeze_diagnostic_excludes_fit_ids_and_rejects_duplicates():
    from v12_verify import difference
    initial = [{'case_id': 'a'}]
    expanded = [{'case_id': i} for i in ('a', 'b', 'c')]
    assert [r['case_id'] for r in difference(initial, expanded, 2)] == ['b', 'c']
    with pytest.raises(ValueError, match='distinct'):
        difference(initial, expanded + [expanded[-1]], 2)


def test_diagnostic_returns_full_new_rows_in_expanded_order():
    from v12_verify import difference

    retained = {'case_id': 'a', 'reference_category': '日常通知'}
    first, second = {'case_id': 'c', 'title': '甲'}, {'case_id': 'b', 'title': '乙'}
    assert difference([retained], [first, retained, second], 2) == [first, second]


@pytest.mark.parametrize(('initial', 'expanded', 'expected', 'error'), [
    ([{'case_id': 'a'}, {'case_id': 'a'}], [{'case_id': 'a'}], 0, 'distinct'),
    ([{'case_id': 'a'}], [{'case_id': 'b'}], 1, 'retain'),
    ([{'case_id': 'a', 'title': '甲'}], [{'case_id': 'a', 'title': '乙'}], 0, 'retain'),
    ([{'case_id': 'a'}], [{'case_id': 'a'}], 1, 'expected'),
    ([], [{'title': 'missing identifier'}], 1, 'case_id'),
    ([], [{'case_id': ' '}], 1, 'case_id'),
])
def test_diagnostic_rejects_inconsistent_manifests(initial, expanded, expected, error):
    from v12_verify import difference

    with pytest.raises(ValueError, match=error):
        difference(initial, expanded, expected)
