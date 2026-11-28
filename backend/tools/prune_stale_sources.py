"""按健康检查结果修剪注册表：修失效路径、停抓停更栏目。

输入是最新一份 .runtime/reports/health-*.json。
规则：
- 最新一条超过 18 个月的栏目 → 停抓（避开一年才发一次的年度通知）；
- 拿不到日期且列表只有 1–2 条的栏目 → 停抓；
- 已知改版的站点按 OVERRIDES 换路径（改完不再算失效）；
- 改版后合并成同一页的重复栏目只留一条。

用法：python tools/prune_stale_sources.py [--dry-run]
"""
import argparse
import glob
import json
import shutil
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / 'src/campus_backend/sources/data/runtime_registry.json'
REPORT_DIR = ROOT / '.runtime/reports'
BACKUP_DIR = ROOT.parent / '.workbuddy/backup'

# 站点改版后的新地址；pattern 与 sample 一并更新，保证 load_registry 的样本校验通过。
OVERRIDES = {
    'csu-mse-faf238ee0bd5': {
        'name': '材料科学与工程学院—学生工作',
        'url': 'https://mse.csu.edu.cn/xsgz/tzgg.htm',
        'article_url_pattern': r'/info/1054/\d+\.htm(?:$|\?)',
        'sample_urls': ['https://mse.csu.edu.cn/info/1054/1996.htm'],
    },
    'csu-srse-591cf0e960a6': {
        'name': '资源与安全工程学院—通知公告',
        'url': 'https://srse.csu.edu.cn/xyzx/tzgg/qb.htm',
        'article_url_pattern': r'/info/\d+/\d+\.htm(?:$|\?)',
        'sample_urls': ['https://srse.csu.edu.cn/info/1295/3667.htm'],
    },
}
# 改版后这几个栏目已经没有独立页面，内容都并入保留的那一条。
MERGED_AWAY = ['csu-srse-41f93ebd20df', 'csu-srse-25ebb43919b4',
               'csu-srse-0e42e2797486', 'csu-srse-ccffb93764e6']
# 列表由前端脚本渲染，静态页没有条目，短期无法抓取。
UNPARSEABLE = ['csu-gra-948179e9667e']


def months_since(value):
    try:
        then = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    today = date.today()
    return (today.year - then.year) * 12 + (today.month - then.month)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    report_path = sorted(glob.glob(str(REPORT_DIR / 'health-*.json')))[-1]
    health = {row['source_id']: row for row in json.loads(Path(report_path).read_text(encoding='utf-8'))}
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    before = registry['sources']

    drop = set(MERGED_AWAY) | set(UNPARSEABLE)
    reasons = {}
    for item in before:
        row = health.get(item['source_id'])
        if row is None or item['source_id'] in drop:
            continue
        latest = row.get('max_date') or row.get('detail_date')
        if row['status'] != 'ok' and item['source_id'] not in OVERRIDES:
            drop.add(item['source_id'])
            reasons[item['source_id']] = f"抓取失败:{row['status']}"
            continue
        # 换过地址的栏目，健康检查跑的还是旧地址，这一轮数据不能用来判断停更。
        if item['source_id'] in OVERRIDES:
            continue
        age = months_since(latest)
        if age is None and row.get('items', 0) <= 2:
            drop.add(item['source_id'])
            reasons[item['source_id']] = '无日期且列表几乎为空'
        elif age is not None and age > 18:
            drop.add(item['source_id'])
            reasons[item['source_id']] = f'最新内容 {latest}'

    kept = []
    for item in before:
        if item['source_id'] in drop:
            continue
        override = OVERRIDES.get(item['source_id'])
        if override:
            item.update(override)
            item['repaired_at'] = datetime.now().isoformat(timespec='seconds')
        kept.append(item)

    print(f'修剪前 {len(before)} → 修剪后 {len(kept)}（移除 {len(drop)}）')
    names = {item['source_id']: item['name'] for item in before}
    for source_id in sorted(drop, key=lambda key: reasons.get(key, '')):
        print(f"  - {names.get(source_id, source_id)}：{reasons.get(source_id, '并入其他栏目或前端渲染')}")

    if args.dry_run:
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M')
    shutil.copy2(REGISTRY, BACKUP_DIR / f'runtime_registry-{len(before)}-{stamp}.json')

    registry['sources'] = kept
    registry.setdefault('notes', {})
    registry['notes']['stale_pruned_at'] = datetime.now().isoformat(timespec='seconds')
    registry['notes']['stale_rule'] = '最新内容超过 18 个月、或前端渲染无条目、或改版后并入其他栏目'
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
    print('已写入', REGISTRY)


if __name__ == '__main__':
    main()
