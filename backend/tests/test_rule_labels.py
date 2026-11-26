import importlib

import pytest
from pydantic import ValidationError


def test_label_code_and_value_validation():
    protocol = importlib.import_module('campus_backend.classification.rule_labels')
    payload = {
        'kind': 'date', 'code': 'registration_deadline', 'scope': {},
        'value': {'date': '2026-11-21'},
        'evidence': [{'segment_id': 'p0', 'quote': '报名截止至2026年11月21日'}],
    }
    assert protocol.DateLabel.model_validate(payload).model_dump(mode='json')['value']['date'] == '2026-11-21'
    with pytest.raises(ValidationError):
        protocol.DateLabel.model_validate({**payload, 'code': 'innovation_credit'})
    with pytest.raises(ValidationError):
        protocol.DateLabel.model_validate({**payload, 'value': {'date': '2026-02-30'}})
