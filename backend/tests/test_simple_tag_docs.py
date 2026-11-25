import re
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from campus_backend.classification.simple_labels import RULES_VERSION


ROOT = Path(__file__).resolve().parents[2]
QUALITY = ROOT / 'docs' / 'quality'
CURRENT_DOCS = (
    'README.md', 'backend/README.md', '07_本科生首版范围与开发顺序.md',
    '08_模块实现与前后端接口规范.md', '09_开发问题与处理规范.md',
    '10_交付前端的首版修正说明.md', 'docs/verification/s1/progress_report.md',
    'docs/handoff/frontend/README.md', 'docs/verification/handoff/frontend-2026-11-20.md',
    'docs/verification/handoff/frontend-2026-11-21.md',
    'docs/verification/s1/android_handoff.md', 'docs/quality/95-percent-acceptance.md',
    'docs/handoff/backend/README.md', 'docs/verification/handoff/backend-2026-11-17.md',
)
PUBLISHED_HANDOFF_DOCS = (
    'README.md', '07_本科生首版范围与开发顺序.md',
    '08_模块实现与前后端接口规范.md', '09_开发问题与处理规范.md',
    '10_交付前端的首版修正说明.md', 'docs/handoff/backend/README.md',
)
BACKEND_REPOSITORY = 'https://github.com/Yuki-Asunaaa/campus-notice-backend'


@pytest.mark.parametrize('name', PUBLISHED_HANDOFF_DOCS)
def test_current_handoff_names_the_published_private_backend_repository(name):
    document = (ROOT / name).read_text()
    assert BACKEND_REPOSITORY in document, f'{name}: missing published backend repository'
    assert '3a52ea7' in document, f'{name}: missing verified code baseline'
    assert '连接、创建及上传尚待完成' not in document
    assert '后端远端地址需以实际创建、上传成功后的交付回执为准' not in document


def test_published_handoff_provides_clone_command_and_pending_invitation():
    handoff = (ROOT / 'docs/handoff/backend/README.md').read_text()
    assert f'git clone --branch main {BACKEND_REPOSITORY}.git campus-backend' in handoff
    assert '227422' in handoff and '待接受' in handoff
    assert 'GitHub不托管这个运行服务' in handoff


def test_historical_verification_keeps_prepublication_record_and_adds_publication_update():
    report = (ROOT / 'docs/verification/handoff/backend-2026-11-17.md').read_text()
    historical, publication = report.split('## GitHub发布补记', 1)
    assert '未创建远端、上传源码或发送协作邀请' in historical
    assert BACKEND_REPOSITORY in publication
    assert '3a52ea77c6e4ae6eda39f5ab18e59e653aad87d5' in publication
    assert 'Awaiting 227422’s response' in publication


def test_current_documentation_uses_matching_s2_contract_versions():
    baseline = (QUALITY / 'rule-baseline.md').read_text()
    acceptance = (QUALITY / '95-percent-acceptance.md').read_text()
    scoring = (QUALITY / 'reference-agreement.md').read_text()
    for document in (baseline, acceptance, scoring):
        assert 's2-label-semantics/3' in document
        assert 's2-rule-baseline/3' in document
    assert '3.1.0' in baseline
    assert '严格大于95%' in acceptance
    assert '重新冻结' in acceptance


def test_current_scope_lists_nine_presence_only_benefit_types():
    scope = (ROOT / '07_本科生首版范围与开发顺序.md').read_text()
    labels = scope.split('## 五 日期、收益、面向群体和状态标签', 1)
    assert len(labels) == 2, '07 must specify the unified current display scope'
    current = labels[1].split('## 六 ', 1)[0]
    for benefit in ('志愿时长', '创新学分', '课程/实践学分', '体育分', '第二课堂积分/学分',
                    '推免加分', '综测加分', '奖金/奖学金/补助', '证书'):
        assert benefit in current
    assert '不输出数值或获得条件' in current
    assert '单位内部报送' in current
    assert '期限未注明' in current and '时间待确认' in current


def test_planned_app_prose_keeps_presence_only_benefit_and_independent_labels():
    api = (ROOT / '08_模块实现与前后端接口规范.md').read_text()
    handoff = (ROOT / '10_交付前端的首版修正说明.md').read_text()
    planned_benefit = api.split('### 5.4 ', 1)[1].split('## 6. ', 1)[0]
    assert re.search(r'\b(condition_text|amount|unit)\b', planned_benefit) is None
    for field in ('date_labels', 'benefit_labels', 'audience_labels', 'status_labels'):
        assert field in api and field in handoff
    for group in ('handling', 'event', 'policy_validity'):
        assert group in api and group in handoff


def test_accuracy_delivery_keeps_unknown_references_and_development_scope_visible():
    report = json.loads((ROOT / 'docs/verification/s2/accuracy-2026-11-14.json').read_text())
    assert report['scope'] == 'development'
    assert report['formal_held_out_evaluated'] == 0
    assert report['reference_agreement'] is None
    assert report['release_claim'] == 'not_established'
    cases = report['cases']
    assert len(cases) == report['cases_total']
    assert sum(case['after_joint'] is True for case in cases) == report['confirmed_joint_after']
    assert sum(case['after_joint'] is None for case in cases) == report['incomplete_references']
    for name in ('07_本科生首版范围与开发顺序.md', '10_交付前端的首版修正说明.md'):
        assert 'accuracy-2026-11-14.md' in (ROOT / name).read_text()


def test_current_progress_numbers_match_frozen_development_evidence():
    report = json.loads((ROOT / 'docs/verification/s2/accuracy-2026-11-14.json').read_text())
    scope = (ROOT / '07_本科生首版范围与开发顺序.md').read_text()
    block = scope.split('### S2当前开发验证', 1)[1].split('\n## ', 1)[0]
    rows = dict(re.findall(r'^\| ([^|]+?) \| ([^|]+?) \|$', block, re.M))
    assert rows['开发通知数'] == str(report['cases_total'])
    assert rows['分类一致'] == f"{report['category_after']}/{report['cases_total']}"
    assert rows['整条已确认一致'] == f"{report['confirmed_joint_after']}/{report['cases_total']}"
    assert rows['应收通知整条一致'] == f"{report['collectable_joint_after']}/{report['collectable_total']}"
    assert rows['应排通知一致'] == f"{report['excluded_correct_after']}/{report['excluded_total']}"
    assert rows['参考未完整'] == str(report['incomplete_references'])
    assert rows['正式留出已评测'] == str(report['formal_held_out_evaluated'])
    assert report['reference_agreement'] is None and '`null`' in rows['本批主分数']


def test_current_rule_version_is_consistent_at_execution_entry_points():
    for name in ('README.md', 'backend/README.md', 'docs/quality/rule-baseline.md',
                 'docs/quality/95-percent-acceptance.md'):
        document = (ROOT / name).read_text()
        assert RULES_VERSION in document, f'{name} must name the actual current rule version'


def test_frontend_planned_route_table_matches_implementation_inventory():
    inventory = json.loads((ROOT / 'docs/contracts/app-v2/implementation-status.json').read_text())
    handoff = (ROOT / '10_交付前端的首版修正说明.md').read_text()
    block = handoff.split('### 切换至v2的业务接口', 1)[1].split('\n## ', 1)[0]
    documented = re.findall(
        r'\| (GET|PUT|POST|PATCH|DELETE) `([^`]+)` \| (S\d+)／(planned|implemented) \|', block)
    actual = {(row['method'], row['path'], row['target_phase'], row['status'])
              for row in inventory['operations']
              if row['status'] == 'planned'}
    assert len(documented) == len(actual)
    assert {(method, path.split('?', 1)[0], phase, status)
            for method, path, phase, status in documented} == actual
    assert '目标契约' in block and '合成fixture' in block


@pytest.mark.parametrize('name', CURRENT_DOCS)
def test_current_handoff_local_links_resolve(name):
    document = ROOT / name
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', document.read_text()):
        parsed = urlsplit(target.strip('<>'))
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        resolved = document.parent / unquote(parsed.path)
        assert resolved.exists(), f'{name}: broken handoff link {target}'
