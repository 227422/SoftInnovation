import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts/quality"))
from fresh_school_comparison import paired
from fresh_school_benchmark import checksum


def test_control_is_the_preregistered_first_95_percent_candidate():
    dataset = ROOT/"docs/quality/corpus/multischool-stages-2026-11-18"
    protocol = json.loads((dataset/"baseline-from-fifth.json").read_text())
    initial = json.loads((dataset/"stage3/results.json").read_text())
    assert protocol["first_cohort"] == 5
    assert checksum(ROOT/protocol["candidate"]) == initial["model_manifest_sha256"] == protocol["sha256"]


def test_compare_uses_identical_inputs_and_references_without_picking_per_row():
    def case(identifier, matched):
        return dict(case_id=identifier, reference_category="daily", university="A", matches_reference=matched)
    main = {"cases":[case("a",True),case("b",False)]}
    baseline = {"cases":[case("b",True),case("a",False)]}
    assert paired(main,baseline) == {"only_current_correct":1,"only_previous_correct":1}
    with pytest.raises(ValueError):paired(main,{"cases":[case("c",True)]})
    with pytest.raises(ValueError):paired(main,{"cases":baseline["cases"]+[case("a",True)]})
    with pytest.raises(ValueError):paired(main,{"cases":[case("a",False),case("b",True)|{"university":"B"}]})


def test_fifth_on_same_cases_and_strict_95_percent_threshold():
    folder = ROOT/"docs/quality/corpus/multischool-stages-2026-11-18/stage5"
    primary = json.loads((folder/"results.json").read_text())
    control = json.loads((folder/"comparison.json").read_text())
    assert primary["overall"]["correct"] == 228
    assert not primary["stage1_passed"] and not primary["stage2_passed"]
    assert control["overall"]["correct"] == 223
    assert sum(control["paired"].values()) == 240
    assert control["paired"]["only_current_correct"] - control["paired"]["only_previous_correct"] == 5
    assert control["main_result_sha256"] == checksum(folder/"results.json")
    assert not control["counts_for_milestone"]


def test_prospective_recheck_uses_exact_sixth_model_on_another_cohort():
    dataset = ROOT / "docs/quality/corpus/multischool-stages-2026-11-18"
    protocol = json.loads((dataset / "v8-confirmation-from-seventh.json").read_text())
    initial = json.loads((dataset / "stage6/results.json").read_text())
    assert protocol["first_cohort"] == 7
    assert checksum(ROOT / protocol["candidate"]) == initial["model_manifest_sha256"] == protocol["sha256"]
    assert protocol["score_for_selection"] is False
