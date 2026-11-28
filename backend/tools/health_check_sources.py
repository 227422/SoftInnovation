"""栏目健康检查：只抓列表页，不入库。

对注册表里每个来源：抓一次列表页，记录能否解析、条目数、有无日期、最新日期。
列表页没有日期时，再抓一条详情页补日期（每个栏目最多 1 次额外请求）。

用法：
    python tools/health_check_sources.py [--limit N] [--no-detail]
输出：
    控制台摘要 + .runtime/reports/health-YYYYMMDD-HHMM.json
"""
import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from campus_backend.collection.html import decode_html, parse_detail, parse_list  # noqa: E402
from campus_backend.collection.http import FetchError, PublicHTTPClient  # noqa: E402

REGISTRY = ROOT / 'src/campus_backend/sources/data/runtime_registry.json'
REPORT_DIR = ROOT / '.runtime/reports'


def month_diff(value):
    try:
        then = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    today = date.today()
    return (today.year - then.year) * 12 + (today.month - then.month)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--no-detail', action='store_true')
    args = parser.parse_args()

    sources = json.loads(REGISTRY.read_text(encoding='utf-8'))['sources']
    if args.limit:
        sources = sources[:args.limit]
    client = PublicHTTPClient(min_interval=0.5)
    rows = []
    began = time.time()
    try:
        for index, source in enumerate(sources, 1):
            row = {'source_id': source['source_id'], 'name': source['name'],
                   'url': source['url'], 'status': 'ok', 'items': 0, 'dated': 0,
                   'max_date': None, 'sample': None, 'detail_date': None, 'error': None}
            started = time.time()
            try:
                response = client.get(source['url'], source['allowed_hosts'])
                parsed = parse_list(decode_html(response), source, response['url'])
                items = parsed['items']
                row['items'] = len(items)
                row['next_urls'] = len(parsed['next_urls'])
                dated = [item['published_at'] for item in items if item.get('published_at')]
                row['dated'] = len(dated)
                row['max_date'] = max(dated) if dated else None
                row['sample'] = items[0]['title'][:80] if items else None
                if not dated and items and not args.no_detail:
                    try:
                        detail = parse_detail(decode_html(client.get(items[0]['url'], source['allowed_hosts'])),
                                              source, items[0]['url'])
                        row['detail_date'] = detail.get('published_at')
                    except Exception as exc:  # 补日期失败不影响列表结论
                        row['detail_date'] = None
                        row['detail_error'] = f'{type(exc).__name__}:{getattr(exc, "message", exc)}'
            except (FetchError, Exception) as exc:  # noqa: B014
                row['status'] = getattr(exc, 'code', type(exc).__name__)
                row['error'] = getattr(exc, 'message', str(exc))[:120]
            row['seconds'] = round(time.time() - started, 1)
            rows.append(row)
            if index % 10 == 0 or index == len(sources):
                print(f'  ...{index}/{len(sources)}  {round(time.time() - began)}s', flush=True)
    finally:
        client.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M')
    report = REPORT_DIR / f'health-{stamp}.json'
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')

    ok = [r for r in rows if r['status'] == 'ok']
    failed = [r for r in rows if r['status'] != 'ok']
    print(f"\n栏目 {len(rows)} 个，成功 {len(ok)}，失败 {len(failed)}，用时 {round(time.time() - began)}s")
    buckets = {'6个月内': 0, '6-12个月': 0, '1-2年': 0, '超过2年': 0, '无日期': 0}
    for row in ok:
        value = row['max_date'] or row['detail_date']
        months = month_diff(value)
        if months is None:
            buckets['无日期'] += 1
        elif months <= 6:
            buckets['6个月内'] += 1
        elif months <= 12:
            buckets['6-12个月'] += 1
        elif months <= 24:
            buckets['1-2年'] += 1
        else:
            buckets['超过2年'] += 1
    print('最新内容分布：', buckets)
    print('\n失败栏目：')
    for row in failed:
        print(f"  [{row['status']}] {row['name']}  {row['url']}")
    print('\n报告：', report)


if __name__ == '__main__':
    main()
