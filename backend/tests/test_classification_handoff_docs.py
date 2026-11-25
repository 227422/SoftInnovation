import json
import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs/handoff/backend/completed-features-2026-11-25.md"
COHORTS = ROOT / "docs/quality/corpus/multischool-stages-2026-11-18"


def local_links(document):
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text())
    return {
        (document.parent / link.path).resolve()
        for target in links
        if (link := urlsplit(target)).path and not link.scheme and not link.netloc
    }


def test_current_handoff_is_reachable_and_cites_accessible_verification():
    for entry in ("README.md", "backend/README.md", "10_交付前端的首版修正说明.md", "docs/handoff/backend/README.md"):
        assert HANDOFF in local_links(ROOT / entry)
    links = local_links(HANDOFF)
    for date in ("2026-11-20", "2026-11-21"):
        assert ROOT / f"docs/verification/handoff/frontend-{date}.md" in links
    assert all(target.exists() for target in links)


def test_category_scores_in_handoff_match_published_cohorts():
    text = HANDOFF.read_text()
    for stage in ("stage3", "stage6", "stage7"):
        result = json.loads((COHORTS / stage / "results.json").read_text())
        overall = result["overall"]
        assert f'{overall["correct"]}/{overall["total"]}（{overall["accuracy"]:.2%}）' in text


def test_handoff_lists_planned_routes_from_contract():
    operations = json.loads((ROOT / "docs/contracts/app-v2/implementation-status.json").read_text())["operations"]
    planned = {f'{op["method"]} {op["path"]}' for op in operations if op["status"] == "planned"}
    assert planned == set(re.findall(r"`((?:GET|PUT|PATCH|POST|DELETE) /v2/[^\s`]+)`", HANDOFF.read_text()))
