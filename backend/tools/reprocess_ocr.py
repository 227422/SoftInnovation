"""把「正文在 PDF/图片里」的通知重新排队识别一次。

只处理 document 阶段的持久任务，不触发列表抓取（schedule=False）。
用法：python tools/reprocess_ocr.py [--limit N] [--dry-run]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from campus_backend.core.config import Settings  # noqa: E402
from campus_backend.providers import build_collector  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--minutes', type=float, default=30)
    args = parser.parse_args()

    worker, engine = build_collector(Settings.from_env())
    try:
        targets = []
        for row in worker.notices.list():
            document = row.get('document') or {}
            errors = document.get('errors') or []
            if row.get('fetch_status') != 'partial':
                continue
            if not any(str(error.get('code', '')).startswith('ocr') for error in errors):
                continue
            targets.append(row)
        if args.limit:
            targets = targets[:args.limit]
        print(f'待重处理 {len(targets)} 条', flush=True)
        for row in targets:
            print(f"  {row['notice_id'][:12]} {row['title'][:36]}", flush=True)
        if args.dry_run or not targets:
            return

        for row in targets:
            worker.jobs.enqueue(
                f"document:{row['notice_id']}:{row['latest_version']}", 'document', row['source_id'],
                {'notice_id': row['notice_id'], 'content_version': row['latest_version']},
                worker.clock(), repeat=True,
            )

        deadline = time.monotonic() + args.minutes * 60
        total = failed = 0
        while time.monotonic() < deadline:
            stats = worker.tick(max_jobs=5, schedule=False, kinds=['document'])
            total += stats['processed']
            failed += stats['failed']
            print(f"  进度 processed={total} failed={failed}", flush=True)
            if stats['processed'] == 0 and stats['failed'] == 0:
                break
        print(f'结束：处理 {total} 条，失败 {failed} 条（超时重试留在队列里）')
    finally:
        worker.http.close()
        engine.dispose()


if __name__ == '__main__':
    main()
