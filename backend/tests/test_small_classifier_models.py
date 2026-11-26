"""Pure input checks plus opt-in real ML integration in an isolated Python."""
import inspect
import os
from pathlib import Path
import runpy
import subprocess
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/quality/small_classifier_models.py'


@pytest.fixture
def models():
    assert SCRIPT.is_file(), 'The isolated small-classifier training module must exist'
    return runpy.run_path(str(SCRIPT))


def test_input_keeps_complete_short_text_and_only_explicit_features(models):
    assert models['head_tail_ids']([10, 11], [20, 21], 101, 102, max_length=8) == [101, 10, 11, 102, 20, 21, 102]
    assert models['feature_text']({'title': '标题', 'body': '正文', 'label': 'excluded',
                                   'case_id': 'hidden-answer'}) == '标题\n标题\n标题\n正文'


def test_long_input_preserves_both_ends_with_explicit_token_limit(models):
    ids = models['head_tail_ids']([10, 11, 12], list(range(20, 30)), 101, 102,
                                  max_length=10, title_limit=2)
    assert ids == [101, 10, 11, 102, 20, 21, 22, 28, 29, 102]
    assert len(ids) == 10


@pytest.mark.parametrize('max_length,title_limit', [(3, 96), (512, 0), (1, 1)])
def test_invalid_input_budget_is_rejected(models, max_length, title_limit):
    with pytest.raises(ValueError):
        models['head_tail_ids']([1], [2], 101, 102,
                                max_length=max_length, title_limit=title_limit)


def test_category_order_and_training_boundary_are_fixed(models):
    assert models['CATEGORIES'] == ('research_innovation', 'financial_aid', 'daily', 'excluded')
    assert list(inspect.signature(models['train_candidates']).parameters) == [
        'train', 'validation', 'model_dir', 'output_dir', 'config']
    cfg = models['normalized_config']({})
    assert cfg['epochs'] == 5
    assert cfg['last_trainable_layers'] == 2
    assert cfg['cpu_threads'] == 2


def test_checkpoint_selection_uses_all_classes_and_earlier_tie(models):
    rows = [{'case_id': str(i), 'label': c} for i, c in enumerate(models['CATEGORIES'])]
    perfect = [{'case_id': r['case_id'], 'prediction': r['label']} for r in rows]
    assert models['validation_key'](rows, perfect, 1) == (1.0, 1.0, -1)
    assert models['validation_key'](rows, perfect, 1) > models['validation_key'](rows, perfect, 2)
    with pytest.raises(ValueError, match='case'):
        models['validation_key'](rows, perfect[:-1], 1)


def test_training_rejects_empty_or_overlapping_ids_before_loading_models(models, tmp_path):
    example = {'case_id': 'same', 'title': 't', 'body': 'b', 'label': 'daily'}
    with pytest.raises(ValueError, match='overlap'):
        models['train_candidates']([example], [example], model_dir=tmp_path,
                                   output_dir=tmp_path / 'out', config={})
    with pytest.raises(ValueError, match='empty'):
        models['train_candidates']([], [example], model_dir=tmp_path,
                                   output_dir=tmp_path / 'out', config={})


def run_ml(code, tmp_path):
    if os.environ.get('RUN_SMALL_MODEL_TESTS') != '1':
        pytest.skip('Real ML integration requires RUN_SMALL_MODEL_TESTS=1 and ML_PYTHON; pure tests still run')
    executable = os.environ.get('ML_PYTHON')
    assert executable and Path(executable).is_file(), 'ML_PYTHON must name the isolated ML Python'
    prelude = f"import runpy\nfrom pathlib import Path\nm = runpy.run_path({str(SCRIPT)!r})\ntmp = Path({str(tmp_path)!r})\n"
    result = subprocess.run([executable, '-c', prelude + textwrap.dedent(code)],
                            text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_linear_real_fit_uses_train_vocabulary_and_reloads_identically(tmp_path):
    run_ml('''
        import json
        rows = []
        for label, word in zip(m['CATEGORIES'], ['科研竞赛', '奖学金资助', '课程考试', '教师采购']):
            for i in range(3):
                rows.append({'case_id': f'{label}{i}', 'title': word, 'body': word * 4, 'label': label})
        val = [{'case_id': 'v', 'title': '仅验证独有词', 'body': '独有词课程考试', 'label': 'daily'}]
        candidate = m['train_linear'](rows, val, tmp / 'linear', m['normalized_config']({}), 2.0)
        metadata = json.loads((tmp / 'linear' / 'model.json').read_text())
        assert '独有' not in metadata['vocabulary']
        assert '仅验' not in metadata['vocabulary']
        actual = m['predict_saved'](tmp / 'linear', val)
        assert actual == candidate['validation_predictions']
        without_label = [{k: v for k, v in r.items() if k != 'label'} for r in rows]
        predictions = m['predict_saved'](tmp / 'linear', without_label)
        assert [r['prediction'] for r in predictions] == [r['label'] for r in rows]
        assert metadata['classes'] == list(m['CATEGORIES'])
        assert not list(tmp.rglob('*.pkl'))
        assert not list(tmp.rglob('*.joblib'))
    ''', tmp_path)


def test_tiny_bert_real_training_updates_only_unfrozen_weights_and_reloads(tmp_path):
    run_ml('''
        import torch
        from transformers import BertConfig, BertForSequenceClassification, BertTokenizer
        torch.set_num_threads(2)
        base = tmp / 'base'; base.mkdir()
        vocab = ['[PAD]', '[UNK]', '[CLS]', '[SEP]', '[MASK]', '科', '研', '奖', '助', '日', '常', '排', '除']
        (base / 'vocab.txt').write_text('\\n'.join(vocab) + '\\n')
        tok = BertTokenizer(vocab_file=str(base / 'vocab.txt'))
        tok.save_pretrained(base)
        model = BertForSequenceClassification(BertConfig(vocab_size=len(vocab), hidden_size=16,
                    num_hidden_layers=3, num_attention_heads=2, intermediate_size=24, num_labels=4))
        counts = m['configure_trainable_layers'](model, 1)
        assert not model.bert.embeddings.word_embeddings.weight.requires_grad
        assert not model.bert.encoder.layer[0].attention.self.query.weight.requires_grad
        assert model.bert.encoder.layer[-1].attention.self.query.weight.requires_grad
        assert model.classifier.weight.requires_grad
        assert 0 < counts['trainable_parameters'] < counts['total_parameters']
        model.save_pretrained(base, safe_serialization=True)
        rows = [{'case_id': str(i), 'title': t, 'body': t * 3, 'label': c}
                for i, (c, t) in enumerate(zip(m['CATEGORIES'], ['科研', '奖助', '日常', '排除']))]
        val = [dict(r, case_id='v' + r['case_id']) for r in rows]
        cfg = m['normalized_config']({'epochs': 1, 'last_trainable_layers': 1, 'max_length': 16,
                                     'title_limit': 4, 'gradient_accumulation_steps': 2})
        candidate = m['train_bert'](rows, val, base, tmp / 'trained', cfg)
        details = candidate['training_details']
        assert details['head_sha256_before'] != details['head_sha256_after']
        assert details['trained_encoder_sha256_before'] != details['trained_encoder_sha256_after']
        assert details['frozen_embeddings_sha256_before'] == details['frozen_embeddings_sha256_after']
        assert details['frozen_first_layer_sha256_before'] == details['frozen_first_layer_sha256_after']
        assert details['optimizer_steps'] == 1
        assert candidate['validation_predictions'] == m['predict_saved'](tmp / 'trained', val)
        ignored_labels = [dict(r, label='invalid-but-ignored') for r in val]
        assert candidate['validation_predictions'] == m['predict_saved'](tmp / 'trained', ignored_labels)
        assert (tmp / 'trained' / 'model.safetensors').is_file()
    ''', tmp_path)
