"""Public category test evidence agrees with the agreed quotas and underlying scorer."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "docs/quality/corpus/multischool-stages-2026-11-18"
STAGES = sorted(p for p in BENCHMARK.glob("stage*") if p.is_dir())
QUOTAS = Counter(daily=8, financial_aid=4, research_innovation=4, excluded=4)


def read(path):
    return json.loads(path.read_text())


def test_new_stages_have_transparent_school_holdouts():
    protocol = read(BENCHMARK / "protocol.json")
    old = [r for path in protocol["old_reference_files"] for r in read(ROOT / path)]
    seen_schools = {r["university"] for r in old} | set(protocol["extra_reserved_schools"])
    seen_bodies = {r["body_sha256"] for r in old}
    assert STAGES
    for stage in STAGES:
        sources = read(stage / "sources.json")
        freeze = read(stage / "freeze.json")
        schools = {r["university"] for r in sources}
        bodies = {r["body_sha256"] for r in sources}
        assert len(sources) == len(bodies) == 240
        assert schools.isdisjoint(seen_schools) and bodies.isdisjoint(seen_bodies)
        seen_schools.update(schools)
        seen_bodies.update(bodies)
        assert len(schools) == 12 and set(freeze["schools"]) == schools
        reviewed = {r["case_id"] for r in sources if "second_read_category" in r}
        assert len(reviewed) >= 48 and set(freeze["reviewed_ids"]) <= reviewed
        for school in schools:
            rows = [r for r in sources if r["university"] == school]
            assert Counter(r["reference_category"] for r in rows) == QUOTAS
            assert {r["reference_category"] for r in rows if r["case_id"] in reviewed} == QUOTAS.keys()
        for row in sources:
            assert len(row["evidence_sha256"]) == 64
            if row.get("second_read_category", row["reference_category"]) != row["reference_category"]:
                assert row["adjudication"]["final_category"] == row["reference_category"]


@pytest.mark.parametrize("stage", STAGES, ids=lambda p: p.name)
def test_published_scores_match_every_source_when_scored(stage):
    report = stage / "results.json"
    if not report.exists():
        assert not (stage / "outcome.json").exists()
        return
    result = read(report)
    refs = {r["case_id"]: r for r in read(stage / "sources.json")}
    correct = 0
    assert set(refs) == {r["case_id"] for r in result["cases"]}
    assert len(result["cases"]) == result["overall"]["total"] == 240
    for item in result["cases"]:
        ref = refs[item["case_id"]]
        assert (item["reference_category"], item["university"]) == (ref["reference_category"], ref["university"])
        matched = item["prediction"] == item["reference_category"]
        assert item["matches_reference"] == matched
        correct += matched
    assert result["overall"]["correct"] == correct
    assert result["stage1_passed"] == (correct >= 229)
    assert result["stage2_passed"] == (correct >= 236)
    assert result["freeze_sha256"] == hashlib.sha256((stage / "freeze.json").read_bytes()).hexdigest()
    matrix = result["confusion_matrix"]
    true_daily = matrix["daily"]["daily"]
    assert result["daily_recall"] == true_daily / 96
    assert result["daily_precision"] == true_daily / sum(row["daily"] for row in matrix.values())


def test_first_opened_cohort_is_preserved_in_scores_and_handoff():
    first = read(BENCHMARK / "stage1/results.json")
    assert first["overall"]["correct"] == 218
    assert first["by_category"]["daily"]["correct"] == 83
    assert not first["stage1_passed"]
    for prefix in ("07", "08", "09", "10"):
        handoff = next(ROOT.glob(prefix + "_*.md")).read_text()
        assert "218/240（90.83%）" in handoff
        assert "multischool-classifier-stages-2026-11-18.md" in handoff


def test_second_batch_result_and_pre_scoring_replacements_remain_traceable():
    result = read(BENCHMARK / "stage2/results.json")
    assert result["overall"]["correct"] == 227
    assert result["by_category"]["daily"]["correct"] == 88
    assert not result["stage1_passed"]
    for stage in STAGES:
        changes = read(stage / "collection-changes.json")
        sources = read(stage / "sources.json")
        ids = {r["case_id"] for r in sources}
        schools = {r["university"] for r in sources}
        removed = {r["case_removed"] for r in changes if "case_removed" in r}
        replaced_schools = {r["original"] for r in changes if "original" in r}
        for change in changes:
            assert change["reason"] and change["stage"] == int(stage.name[5:])
            if "case_removed" in change:
                assert change["case_removed"] not in ids
                assert change["case_added"] in ids | removed
            else:
                assert change["replacement"] in schools | replaced_schools
                assert change["original"] not in schools


def test_first_95_percent_milestone_is_backed_by_a_new_school_batch():
    result = read(BENCHMARK / "stage3/results.json")
    assert result["stage1_passed"] and not result["stage2_passed"]
    assert result["overall"]["correct"] == 231 and result["overall"]["total"] == 240
    assert result["by_category"]["daily"]["correct"] == 94
    assert result["by_category"]["research_innovation"]["correct"] == 48
    assert result["by_category"]["financial_aid"]["correct"] == 48
    assert result["by_category"]["excluded"]["correct"] == 41
    model = ROOT / "docs/quality/training/v5-model-candidate.json"
    assert result["model_manifest_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()


def test_additional_training_notices_are_from_already_opened_schools_and_never_score():
    later = read(BENCHMARK / "protocol-extra86.json")
    extra_file = BENCHMARK / "open-development-86.json"
    assert str(extra_file.relative_to(ROOT)) in later["old_reference_files"]
    extra = read(extra_file)
    assert len(extra) == len({r["url"] for r in extra}) == 86
    assert later["extra_development"]["public_index_sha256"] == hashlib.sha256(extra_file.read_bytes()).hexdigest()
    first = read(BENCHMARK / "stage1/sources.json")
    assert {r["university"] for r in extra} <= {r["university"] for r in first}
    extra_bodies = {r["body_sha256"] for r in extra}
    for stage in STAGES:
        assert extra_bodies.isdisjoint(r["body_sha256"] for r in read(stage / "sources.json"))
        if int(stage.name[5:]) >= 4:
            prep = read(stage / "freeze.json")
            assert later["extra_development"]["public_index_sha256"] in prep["history_sha256"]


def test_fourth_cohort_records_regression_and_preserves_prior_crossing():
    result = read(BENCHMARK / "stage4/results.json")
    assert result["overall"]["correct"] == 220
    assert result["by_category"]["excluded"]["correct"] == 38
    assert result["by_category"]["daily"]["correct"] == 90
    assert not (result["stage1_passed"] or result["stage2_passed"])
    assert read(BENCHMARK / "stage3/results.json")["stage1_passed"]


def test_sixth_cohort_preserves_pre_score_decisions_and_source_gaps():
    cohort = BENCHMARK / "stage6"
    rows = {r["case_id"]: r for r in read(cohort / "sources.json")}
    changes = {r.get("original"): r.get("replacement") for r in read(cohort / "collection-changes.json")}
    assert changes["西北师范大学"] == "河南农业大学"
    assert changes["南京邮电大学"] == "河海大学"
    assert changes["中国计量大学"] == "浙江农林大学"
    festival = rows["v3-n-imu-6ce1301682b0f1"]
    assert festival["second_read_category"] == "daily"
    assert festival["reference_category"] == festival["adjudication"]["final_category"] == "research_innovation"
    assert festival["adjudication"]["reason"]
    notes = read(cohort / "sampling-notes.json")
    assert len(notes["undated_cases"]) == 4 and set(notes["undated_cases"]) <= rows.keys()
    assert notes["pre_inclusion_changes"]


def test_sixth_score_and_fixed_comparison_bind_to_published_models():
    cohort = BENCHMARK / "stage6"
    result = read(cohort / "results.json")
    comparison = read(cohort / "comparison.json")
    assert result["overall"]["correct"] == 229 and result["stage1_passed"] and not result["stage2_passed"]
    assert {k: v["correct"] for k, v in result["by_category"].items()} == {
        "daily": 91, "financial_aid": 46, "research_innovation": 44, "excluded": 48
    }
    current_model = ROOT / "docs/quality/training/v8-model-candidate.json"
    assert result["model_manifest_sha256"] == hashlib.sha256(current_model.read_bytes()).hexdigest()
    assert comparison["overall"]["correct"] == 221
    assert comparison["paired"] == {
        "both_correct": 219, "only_current_correct": 10, "only_previous_correct": 2, "both_wrong": 9
    }
    assert comparison["main_result_sha256"] == hashlib.sha256((cohort / "results.json").read_bytes()).hexdigest()
    for prefix in ("07", "08", "09", "10"):
        assert "229/240（95.42%）" in next(ROOT.glob(prefix + "_*.md")).read_text()


def test_new_boundary_examples_are_reserved_before_any_seventh_cohort_predictions():
    protocol = read(BENCHMARK / "protocol-boundary77.json")
    index = BENCHMARK / "open-boundary-77.json"
    proof = protocol["additional_development_boundaries"]
    assert str(index.relative_to(ROOT)) in protocol["old_reference_files"]
    assert proof["public_index_sha256"] == hashlib.sha256(index.read_bytes()).hexdigest()
    rows = read(index)
    assert len(rows) == len({r["body_sha256"] for r in rows}) == proof["kept"] == 77
    assert Counter(r["reference_category"] for r in rows) == proof["category_counts"]
    open_schools = {r["university"] for i in range(2, 6) for r in read(BENCHMARK / f"stage{i}/sources.json")}
    assert {r["university"] for r in rows} <= open_schools
    assert proof["screened_against"] == 2246
    for stage in STAGES:
        if int(stage.name[5:]) >= proof["from_cohort"]:
            assert proof["public_index_sha256"] in read(stage / "freeze.json")["history_sha256"]


def test_seventh_protocol_rejects_cross_school_reprints_before_model_answers():
    cohort = BENCHMARK / "stage7"
    freeze = read(cohort / "freeze.json")
    notes = read(cohort / "sampling-notes.json")
    discarded = notes["withdrawn_pre_score_lock"]
    assert discarded["previous_candidate_inference"] is False
    assert len(discarded["previous_freeze_sha256"]) == 64
    assert discarded["previous_freeze_sha256"] != hashlib.sha256((cohort / "freeze.json").read_bytes()).hexdigest()
    assert freeze["protocol_sha256"] == hashlib.sha256((BENCHMARK / "protocol-boundary77.json").read_bytes()).hexdigest()
    changes = read(cohort / "collection-changes.json")
    removed = {r["case_removed"] for r in changes if "case_removed" in r}
    assert {"v3-n-sxau-7b85b7f47d63c2", "v3-n-hebtu-0c13386b505f6d"} <= removed
    sources = {r["case_id"]: r for r in read(cohort / "sources.json")}
    contest = sources["v3-n-hebtu-6fdd591a234883"]
    assert len(contest["decision_attachments"]) == 4
    for source in contest["decision_attachments"]:
        assert source["url"].startswith("https://jwc.hebtu.edu.cn/")
        assert len(source["sha256"]) == 64


def test_seventh_score_preserves_primary_failure_and_same_model_cross_school_retest():
    cohort = BENCHMARK / "stage7"
    result = read(cohort / "results.json")
    assert result["overall"]["correct"] == 225
    assert not result["stage1_passed"] and not result["stage2_passed"]
    assert not result["formal_s2_acceptance"]
    assert {k: v["correct"] for k, v in result["by_category"].items()} == {
        "daily": 90, "financial_aid": 48, "research_innovation": 44, "excluded": 43
    }
    for name, expected in (("comparison.json", 221), ("comparison-v8.json", 227)):
        control = read(cohort / name)
        assert control["overall"]["correct"] == expected
        assert sum(control["paired"].values()) == 240
        assert control["main_result_sha256"] == hashlib.sha256((cohort / "results.json").read_bytes()).hexdigest()
        assert not control["counts_for_milestone"]
    previous = read(BENCHMARK / "stage6/results.json")
    v8 = read(cohort / "comparison-v8.json")
    assert previous["model_manifest_sha256"] == v8["baseline_manifest_sha256"]
    assert previous["overall"]["correct"] + v8["overall"]["correct"] == 456


def test_eighth_protocol_reserves_every_opened_role_and_action_example():
    protocol = read(BENCHMARK / "protocol-role-action.json")
    index = BENCHMARK / "open-role-action.json"
    details = protocol["role_action_development"]
    assert str(index.relative_to(ROOT)) in protocol["old_reference_files"]
    assert details["index_sha256"] == hashlib.sha256(index.read_bytes()).hexdigest()
    rows = read(index)
    assert len(rows) == len({r["case_id"] for r in rows}) == details["reviewed"] == 214
    kept = [r for r in rows if r["eligible_for_development"]]
    assert len(kept) == len({r["body_sha256"] for r in kept}) == details["kept"] == 171
    assert Counter(r["reference_category"] for r in kept) == details["category_counts"]
    assert len({r["university"] for r in kept}) == details["schools"] == 45
    assert sum(r["in_first_diagnostic"] for r in kept) == 112
    assert all(r["eligible_for_development"] or not r["in_first_diagnostic"] for r in rows)
    prior = {r["university"] for i in range(2, 6) for r in read(BENCHMARK / f"stage{i}/sources.json")}
    assert {r["university"] for r in rows} <= prior
    assert all(r["audience_role"] and r["action_type"] and len(r["evidence_sha256"]) == 64 for r in rows)
    for stage in STAGES:
        if int(stage.name[5:]) >= details["from_cohort"]:
            assert details["index_sha256"] in read(stage / "freeze.json")["history_sha256"]


def test_new_school_sports_policy_distinguishes_athletic_performance_from_submitted_work():
    policy = read(BENCHMARK / "protocol-role-action.json")["sports_competitions"]
    assert policy["athletic_performance"] == "daily"
    assert policy["sports_technology_or_design_entries"] == "research_innovation"
    assert policy["first_prospective_cohort"] == 8
    for prefix in ("07", "08", "09", "10"):
        document = next(ROOT.glob(prefix + "_*.md")).read_text()
        assert "纯体育赛事" in document and "体育科技或设计作品竞赛" in document
    prior = read(BENCHMARK / "stage7/sources.json")
    example = next(r for r in prior if "国家学生体质健康项目挑战赛" in r["title"])
    assert example["reference_category"] == "daily"


def test_eighth_seal_discloses_counts_and_digests_without_reference_answers():
    receipt = read(BENCHMARK / "sealed-eighth-receipt.json")
    assert receipt["stage"] == 8 and receipt["status_at_freeze"] == "sealed_before_prediction"
    assert (receipt["source_count"], receipt["school_count"], receipt["independent_rereads"]) == (240, 12, 48)
    assert Counter(receipt["per_school"]) == QUOTAS
    assert receipt["matched_event_families_replaced"] == 6 and receipt["near_duplicate_pairs"] == 4
    assert not {"cases", "reference", "predictions", "schools", "score"} & receipt.keys()
    protocol = BENCHMARK / "protocol-role-action.json"
    assert receipt["protocol_sha256"] == hashlib.sha256(protocol.read_bytes()).hexdigest()
    assert len(receipt["disjoint_check_source_hashes"]) == len(read(protocol)["old_reference_files"]) + 7
    freeze = BENCHMARK / "stage8/freeze.json"
    if freeze.exists():
        assert hashlib.sha256(freeze.read_bytes()).hexdigest() == receipt["freeze_sha256"]
