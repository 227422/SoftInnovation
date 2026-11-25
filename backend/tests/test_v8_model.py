from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/quality'))


def test_document_tokens_retain_title_and_intermediate_audience():
    assert (ROOT/'scripts/quality/v8_bert.py').exists()
    from v8_bert import pack
    ids=pack([5,7],list(range(500,1100)),list(range(2000,2300)),101,102)
    assert ids[:4]==[101,5,7,102] and 500 in ids and 2000 in ids and ids[-1]==102 and len(ids)<=256


def test_guardrail_has_a_single_predeclared_fallback():
    assert (ROOT/'scripts/quality/v8_model_development.py').exists()
    from v8_model_development import guarded_fraction
    assert guarded_fraction(.75,{'correct':150,'daily_correct':70},{'correct':148,'daily_correct':69})==.75
    assert guarded_fraction(.75,{'correct':150,'daily_correct':70},{'correct':147,'daily_correct':70})==.25


def test_pretrained_sequence_attention_and_feedforward_receive_gradient(tmp_path):
    import os
    import subprocess
    import pytest
    executable = os.environ.get('ML_PYTHON')
    if not executable:
        pytest.skip('requires the isolated learning environment')
    code = """
import sys
import numpy as np
import torch
from transformers import BertConfig, BertForSequenceClassification
from v8_bert import fine_tune, logits, original, tail_from
path=sys.argv[1]
torch.manual_seed(9)
config=BertConfig(vocab_size=128,hidden_size=24,intermediate_size=48,num_hidden_layers=12,
                  num_attention_heads=4,num_labels=4)
BertForSequenceClassification(config).save_pretrained(path,safe_serialization=True)
torch.set_num_threads(2)
lengths=np.array([8,9,10]*4)
mask=torch.arange(10)[None,:] < torch.tensor(lengths)[:,None]
ids=torch.randint(0,128,(len(lengths),10))
with torch.inference_mode():
    native=original(path).eval()(input_ids=ids,attention_mask=mask,output_hidden_states=True)
    boundary=native.hidden_states[10]
    # The new module must preserve the pretrained model's native token attention and mask.
    split=tail_from(path).eval()(boundary,mask)
    torch.testing.assert_close(split,native.logits,rtol=1e-5,atol=1e-6)
    features=boundary.to(torch.float16).numpy()
labels=np.repeat(np.arange(4),3)
trained,proof=fine_tune(path,features,lengths,labels,np.ones(12),np.arange(12),1)
assert all(proof['before'][key]!=value for key,value in proof['after'].items())
assert proof['optimizer_steps']==1 and proof['trainable_layers']==[11,12]
scores=logits(trained,features,lengths,np.arange(12),proof['device'])
assert scores.shape==(12,4) and np.isfinite(scores).all()
"""
    proc = subprocess.run([str(Path(executable).absolute()), '-c', code, str(tmp_path)],
                          cwd=ROOT/'scripts/quality', capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def test_published_school_groups_are_disjoint_from_training_and_each_other():
    from v8_model_data import partitions
    rows = [{'university':f'{group}-school-{s}','historical_split':group}
            for group in ['test',*(f'consumed_cohort{i}' for i in range(1,6))] for s in range(12)]
    rows.extend([{'university':'base-train','historical_split':'train'},
                 {'university':'base-selection','historical_split':'validation'},
                 dict(rows[0],historical_split='development_supplement')])
    tr, va, guard = partitions(rows)
    schools = [{rows[i]['university'] for i in indices} for indices in (tr, va, guard)]
    assert len(schools[1]) == len(schools[2]) == 12
    assert not (schools[0] & schools[1] or schools[0] & schools[2] or schools[1] & schools[2])
    assert {'base-train','base-selection'} <= schools[0]
    assert sorted([*tr,*va,*guard]) == list(range(len(rows)))
