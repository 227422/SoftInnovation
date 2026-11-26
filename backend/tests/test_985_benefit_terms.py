"""Offline checks for the scope and evidence in the university terminology register."""
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs/quality/985-benefit-terms.md"
WORKBOOK = ROOT / "outputs/985-terms-20261118/39校本科收益术语对照表.xlsx"
# In the Ministry's published roster the military university used its earlier name.
SCHOOLS = dict(line.split() for line in """
北京大学 pku
中国人民大学 ruc
清华大学 tsinghua
北京航空航天大学 buaa
北京理工大学 bit
中国农业大学 cau
北京师范大学 bnu
中央民族大学 muc
南开大学 nankai
天津大学 tju
大连理工大学 dlut
东北大学 neu
吉林大学 jlu
哈尔滨工业大学 hit
复旦大学 fudan
同济大学 tongji
上海交通大学 sjtu
华东师范大学 ecnu
南京大学 nju
东南大学 seu
浙江大学 zju
中国科学技术大学 ustc
厦门大学 xmu
山东大学 sdu
中国海洋大学 ouc
武汉大学 whu
华中科技大学 hust
湖南大学 hnu
中南大学 csu
国防科技大学 nudt
中山大学 sysu
华南理工大学 scut
四川大学 scu
重庆大学 cqu
电子科技大学 uestc
西安交通大学 xjtu
西北工业大学 nwpu
西北农林科技大学 nwsuaf,nwafu
兰州大学 lzu
""".strip().splitlines())
BASE = set("志愿时长 创新学分 课程/实践学分 体育分 第二课堂积分/学分 推免加分 综测加分 奖金/奖学金/补助 证书".split())


def register_rows():
    lines = [line for line in REGISTER.read_text().splitlines() if line.startswith("| ")]
    assert len(lines[0].strip("|").split("|")) == 7
    return [[field.strip() for field in line.strip("|").split("|")] for line in lines[1:]]


def file_links(source):
    return re.findall(r"\[([^\]]+)\]\((https?://[^\s]+?)\)", source)


def test_official_terms_include_the_39_schools_and_distinguish_uncertainty():
    confirmed, statuses, records = set(), set(), set()
    sources_by_school = defaultdict(set)
    for school, term, concept, label, status, evidence, source in register_rows():
        assert school in SCHOOLS and term and concept and evidence
        assert status in {"已核定义", "校本概念", "待核"}
        assert label and (label == "—") == (status == "待核")
        urls = [url for _, url in file_links(source)]
        assert urls and all(urlsplit(u).path not in ("", "/") for u in urls), source
        sources_by_school[school].update(urls)
        for url in urls:
            host = urlsplit(url).hostname or ""
            domains = [alias + ".edu.cn" for alias in SCHOOLS[school].split(",")]
            assert any(host == domain or host.endswith("." + domain) for domain in domains), (school, host)
        key = (school, term, concept, evidence)
        assert key not in records, key
        records.add(key)
        statuses.add(status)
        if status != "待核":
            confirmed.add(concept)
    assert set(sources_by_school) == set(SCHOOLS)
    assert all(len(urls) >= 2 for urls in sources_by_school.values())
    assert BASE <= confirmed
    assert statuses == {"已核定义", "校本概念", "待核"}


def test_implementation_and_frontend_documents_point_to_the_register():
    for prefix in ("07_", "08_", "09_", "10_"):
        doc, = ROOT.glob(prefix + "*.md")
        assert "](docs/quality/985-benefit-terms.md)" in doc.read_text()
    assert "](985-benefit-terms.md)" in (REGISTER.parent / "multischool-tag-design.md").read_text()


def test_school_terms_keep_distinct_meanings_and_reverse_labels():
    rows = {(row[0], row[1]): row for row in register_rows()}
    hours = rows["中国海洋大学", "志愿服务工时"]
    credits = rows["中国海洋大学", "志愿服务工时学分"]
    assert (hours[2], credits[2]) == ("志愿时长", "创新学分")
    assert rows["北京师范大学", "荣誉京师奖学金"][2] == "证书"
    local = [rows["北京航空航天大学", "同等条件下可优先考虑"],
             rows["大连理工大学", "同等条件下优先考虑"]]
    assert {r[2] for r in local} == {"同等条件推免优先"}
    assert len({r[3] for r in local}) == 2


def test_filterable_workbook_matches_source_text_and_every_official_link():
    rows = register_rows()
    workbook = load_workbook(WORKBOOK)
    try:
        sheet, = workbook.worksheets
        assert sheet.freeze_panes == "A4"
        assert sheet.tables["UniversityBenefitTerms"].autoFilter.ref == f"A3:H{len(rows) + 3}"
        assert sheet.max_row == len(rows) + 3
        for index, row in enumerate(rows, 4):
            assert [sheet.cell(index, col).value for col in range(1, 7)] == row[:6]
            expected = file_links(row[6])
            actual = [(cell.value, cell.hyperlink.target) for cell in sheet[index][6:] if cell.hyperlink]
            assert actual == expected
    finally:
        workbook.close()
