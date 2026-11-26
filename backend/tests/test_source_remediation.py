import json
from pathlib import Path

import pytest

from campus_backend.collection.html import parse_detail, parse_list

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "backend/src/campus_backend/sources/data/runtime_registry.json"

CASES = [
    ("csu-lib-5155695ea066", "lib", "/index/tzgg.htm", "3610"),
    ("csu-lib-612792fa6f04", "lib", "/index/pxyhd.htm", "3612"),
    ("csu-mse-b93bb9d42d2e", "mse", "/bksjy/pyfa.htm", "1020"),
    ("csu-mse-31438ebd4e8e", "mse", "/yjsjy/pyfa.htm", "1034"),
    ("csu-mse-2c8e172b8cb1", "mse", "/index/tzgg.htm", "1003"),
    ("csu-mse-45c27a1f5340", "mse", "/cywj/zdwj.htm", "1069"),
    ("csu-mse-420281fec789", "mse", "/cywj/cyxz.htm", "1073"),
]


def source(source_id):
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return next(row for row in registry["sources"] if row["source_id"] == source_id)


@pytest.mark.parametrize(("source_id", "department", "path", "section"), CASES)
def test_repaired_source_matches_observed_cms_article_family(source_id, department, path, section):
    config = source(source_id)
    host = f"{department}.csu.edu.cn"
    assert config["unit_id"] == f"csu-{department}"
    assert config["url"] == f"https://{host}{path}"
    assert host in config["allowed_hosts"]
    # Minimal reconstruction of navigation and compact article cards from the public pages.
    html = f"""
    <nav><a href="/info/9999/42.htm">页眉中的无关链接</a></nav>
    <a href="/info/{section}/3317.htm"><div class="list-tx"><h3>独立标题</h3>
    <p>独立标题以外的摘要</p></div></a>
    """
    result = parse_list(html, config, config["url"])
    assert [item["url"] for item in result["items"]] == [f"https://{host}/info/{section}/3317.htm"]
    if department == "lib":
        assert result["items"][0]["title"] == "独立标题"


def test_library_borrowing_rules_remains_direct():
    config = source("csu-lib-ca10c2ef589c")
    assert config["unit_id"] == "csu-lib"
    assert config["direct_article"]
    assert config["url"] == "https://lib.csu.edu.cn/jyfw/jybl/jygz/jyqx.htm"
    detail = parse_detail('<div id="vsb_content"><p>借阅权限说明</p></div>', config, config["url"])
    assert "借阅权限说明" in detail["html"]
