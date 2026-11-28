"""快速看几个栏目最近发了什么，不做入库。

用法：
    python tools/peek_sources.py --limit 6 csu-gra-xxxx csu-yz-yyyy ...
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from campus_backend.collection.html import decode_html, parse_list  # noqa: E402
from campus_backend.collection.http import PublicHTTPClient  # noqa: E402

REGISTRY = Path(__file__).resolve().parent.parent / 'src/campus_backend/sources/data/runtime_registry.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_ids', nargs='+')
    parser.add_argument('--limit', type=int, default=6)
    args = parser.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    sources = {row['source_id']: row for row in registry['sources']}
    client = PublicHTTPClient(min_interval=0.5)
    try:
        for source_id in args.source_ids:
            source = sources.get(source_id)
            if source is None:
                print(f'!! 未找到来源 {source_id}')
                continue
            print(f"\n===== {source['name']}  {source['url']}")
            try:
                response = client.get(source['url'], source['allowed_hosts'])
                parsed = parse_list(decode_html(response), source, response['url'])
            except Exception as exc:  # 探针脚本，不掩盖失败原因
                print(f'  抓取失败：{type(exc).__name__} {getattr(exc, "message", exc)}')
                continue
            items = parsed['items']
            print(f'  列表解析 {len(items)} 条，下一页 {len(parsed["next_urls"])} 个')
            for item in items[:args.limit]:
                print(f"  {item.get('published_at') or '----------'}  {item['title'][:56]}")
            dates = sorted(i.get('published_at') or '' for i in items)
            if dates:
                print(f"  本页日期范围 {dates[0]} ~ {dates[-1]}")
    finally:
        client.close()


if __name__ == '__main__':
    main()
