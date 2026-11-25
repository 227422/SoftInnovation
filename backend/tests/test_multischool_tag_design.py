"""The proposed multi-school examples must remain valid under the existing tag contract."""
import json
from pathlib import Path

from pydantic import TypeAdapter

from campus_backend.classification.simple_labels import SimpleFact

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / 'docs/quality/multischool-tag-examples.json'


def test_design_examples_are_scoped_and_supported_by_their_own_text():
    examples = json.loads(ARTIFACT.read_text())['examples']
    facts = {}
    for example in examples:
        tags = [TypeAdapter(SimpleFact).validate_python(row) for row in example['labels']]
        for tag in tags:
            assert all(ev.quote in example['segments'][ev.segment_id] for ev in tag.evidence)
        facts[example['id']] = tags
    offered = [t for t in facts['multi-benefits'] if t.kind == 'benefit']
    assert {(t.code, t.scope.action) for t in offered} == {('volunteer_hours', '志愿服务'), ('certificate', '培训')}
    deadlines = [t for t in facts['parallel-deadlines'] if t.kind == 'date']
    assert {(t.value.end.month_day, t.scope.audience_groups[0].audience) for t in deadlines} == {
        ('11-12', '甲学院2026级本科生'), ('11-15', '乙学院2025级本科生')}
    assert {t.kind for t in facts['publicity-objection']} == {'status', 'date', 'audience', 'benefit'}
    assert facts['internal-excluded'] == []
