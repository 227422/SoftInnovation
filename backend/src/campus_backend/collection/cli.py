"""Local operator commands over feature ports; no SQL or public URL input."""
import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from pathlib import Path, PurePosixPath
from threading import Event

from campus_backend.classification.collected_facts import (
    validate_collected_raw_reference,
    validate_collected_rule_facts,
)
from campus_backend.core.artifacts import validate_artifact, write_artifact
from campus_backend.core.storage import StorageError
from campus_backend.sources.service import load_registry


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('必须是正整数')
    return number


def duration_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('运行秒数必须是有限正数')
    return number


def add_commands(commands):
    sync = commands.add_parser('sources-sync', help='同步已核验的本地来源注册表（不联网）')
    sync.add_argument('--registry', type=Path)
    once = commands.add_parser('collect-once', help='执行一批到期来源及持久任务')
    once.add_argument('--source', action='append', dest='source_ids', help='仅处理指定来源，可重复')
    once.add_argument('--max-jobs', type=positive_int, default=20)
    worker = commands.add_parser('collector-worker', help='运行可停止、可重启的采集工作进程')
    worker.add_argument('--workers', type=positive_int, default=4)
    worker.add_argument('--duration', type=duration_seconds, help='运行秒数；省略则持续至Ctrl+C')
    worker.add_argument('--registry', type=Path, help='启动前同步此本地注册表；省略则使用数据库现有来源')
    reprocess = commands.add_parser('reprocess-notice', help='重新排队最新原件版本的提取与公共分析')
    reprocess.add_argument('notice_id')


COMMANDS = {'sources-sync', 'collect-once', 'collector-worker', 'reprocess-notice'}
_PRIVATE_KEYS = {'profile', 'trusted_profile', 'personal_result', 'user_id', 'account_id', 'email',
                 'password', 'password_hash', 'session_token', 'csrf_token', 'cookie', 'cookies'}


def _public_only(value):
    if isinstance(value, dict):
        if value.get('stage') == 'personal_result' or _PRIVATE_KEYS.intersection(value):
            raise ValueError('公共导出中出现个人资料或账号字段，已拒绝导出')
        for child in value.values():
            _public_only(child)
    elif isinstance(value, list):
        for child in value:
            _public_only(child)


def _run_workers(worker, workers, duration):
    stop = Event()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='campus-collector') as pool:
        if workers == 1:
            futures = [pool.submit(worker.run_forever, stop=stop, duration=duration)]
        else:
            futures = [pool.submit(worker.run_forever, stop=stop, duration=duration,
                                   kinds=['source'], schedule=True)]
            futures.extend(pool.submit(worker.run_forever, stop=stop, duration=duration,
                kinds=['history', 'detail', 'document'], schedule=False) for _ in range(workers - 1))
        try:
            for future in as_completed(futures):
                future.result()
        except KeyboardInterrupt:
            stop.set()
            for future in futures:
                future.result()
        except BaseException:
            stop.set()
            raise
    return {'workers': workers, 'status': 'stopped'}


def execute(args, settings):
    """Return a process status, with machine-readable output and redacted failures."""
    from campus_backend.providers import build_collector
    worker = engine = None
    try:
        # Loading an invalid registry must fail before any persistent mutation.
        registry = load_registry(args.registry) if args.command == 'sources-sync' or (
            args.command == 'collector-worker' and args.registry is not None) else None
        worker, engine = build_collector(settings)
        if registry is not None:
            worker.sources.sync(registry['sources'], worker.clock())
        if args.command == 'sources-sync':
            result = {'sources': len(registry['sources']), 'enabled': sum(
                row.get('status') == 'enabled' for row in registry['sources'])}
        elif args.command == 'collect-once':
            selected = list(dict.fromkeys(args.source_ids)) if args.source_ids else None
            if selected:
                for source_id in selected:
                    source = worker.sources.get(source_id)
                    if source is None or source.get('status') != 'enabled':
                        raise ValueError('指定来源不存在或尚未启用')
            result = worker.tick(max_jobs=args.max_jobs, source_ids=selected)
        elif args.command == 'collector-worker':
            result = _run_workers(worker, args.workers, args.duration)
        elif args.command == 'reprocess-notice':
            record = worker.notices.get(args.notice_id)
            if record is None:
                raise ValueError('通知不存在')
            version = record['latest_version']
            if worker.notices.raw(args.notice_id, version) is None:
                raise ValueError('最新原件不存在，无法重新处理')
            job_id = f'document:{args.notice_id}:{version}'
            queued = worker.jobs.enqueue(job_id, 'document', record['source_id'],
                {'notice_id': args.notice_id, 'content_version': version}, worker.clock(), repeat=True)
            result = {'notice_id': args.notice_id, 'content_version': version, 'job_id': job_id,
                      'queued': queued, 'status': 'queued' if queued else 'already_pending_or_running'}
        else:
            raise ValueError('未知本机管理命令')
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError):
        print(json.dumps({'error': {'code': 'invalid_command', 'message': '命令参数、来源清单或通知原件不完整；请核对后重试'}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, StorageError):
        print(json.dumps({'error': {'code': 'storage_unavailable', 'message': '本地文件或数据库暂不可用；请检查初始化、目录权限及磁盘空间后重试'}}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({'error': {'code': 'collector_unavailable', 'message': '采集命令暂未完成；已保留持久任务和原成功内容，可重启后重试'}}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if worker is not None:
            with suppress(Exception):
                worker.http.close()
        if engine is not None:
            with suppress(Exception):
                engine.dispose()
