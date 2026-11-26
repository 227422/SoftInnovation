"""Command-line entry point; the standard output is a JSON-only interface."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

from .engine import analyze_batch
from .report import render_report


ROOT = Path(__file__).resolve().parents[1]
DEMO_NOW = "2026-10-30T10:00:00+08:00"


def _reject_constant(value):
    raise ValueError("JSON 不支持特殊数字：" + value)


def _read_json(path):
    try:
        with path.open(encoding="utf-8-sig") as handle:
            return json.load(handle, parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("无法读取 JSON 文件 {}：{}".format(path, exc)) from exc


def _notices_from_input(value):
    if isinstance(value, dict) and "notices" in value:
        value = value["notices"]
    if not isinstance(value, list):
        raise ValueError('输入必须是通知数组，或包含数组的 {"notices": [...]} 对象')
    return value


def _same_path(first, second):
    if first.resolve() == second.resolve():
        return True
    return first.exists() and second.exists() and os.path.samefile(str(first), str(second))


def _check_destinations(destinations, inputs):
    for destination in destinations:
        for source in inputs:
            if _same_path(destination, source):
                raise ValueError("输出不得覆盖输入、档案或规则文件：{}".format(destination))
    if len(destinations) == 2 and _same_path(destinations[0], destinations[1]):
        raise ValueError("--output 和 --report 不能指向同一文件")


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=str(path.parent), prefix=".notice-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(str(temporary), str(path))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _parse_now(value):
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("--now 必须是 ISO 日期时间，例如 2026-10-30T10:00:00+08:00") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone(timedelta(hours=8)))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="校园通知规则分类核心；只处理本地 JSON，不采集或发送消息。")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--input", type=Path, help="通知数组或 notices 对象的 JSON 文件")
    source_group.add_argument("--demo", action="store_true", help="运行内置虚构示例，默认使用固定演示时间")
    parser.add_argument("--profile", type=Path, help="学生档案 JSON 文件")
    parser.add_argument("--now", help="计算时刻（ISO；无时区时按 +08:00）")
    parser.add_argument("--rules", type=Path, help="替换默认规则的 JSON 文件")
    parser.add_argument("--output", type=Path, help="JSON 输出路径；省略则输出到标准输出")
    parser.add_argument("--report", type=Path, help="同时保存中文 Markdown 报告")
    args = parser.parse_args(argv)
    try:
        input_path = ROOT / "examples" / "notices.json" if args.demo else args.input
        profile_path = args.profile
        if args.demo and profile_path is None:
            profile_path = ROOT / "examples" / "profile.json"
        rules_path = args.rules if args.rules is not None else ROOT / "campus_notice" / "rules.json"
        inputs = [path for path in (input_path, profile_path, rules_path) if path is not None]
        destinations = [path for path in (args.output, args.report) if path is not None]
        _check_destinations(destinations, inputs)
        notices = _notices_from_input(_read_json(input_path))
        profile = _read_json(profile_path) if profile_path is not None else None
        if profile_path is not None and not isinstance(profile, dict):
            raise ValueError("学生档案必须是 JSON 对象")
        current = _parse_now(args.now or DEMO_NOW) if args.demo or args.now else None
        result = analyze_batch(notices, profile, now=current,
                               rules_path=str(args.rules) if args.rules is not None else None)
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        report = render_report(result, fictional=args.demo) if args.report is not None else None
        if args.output is not None:
            _atomic_write(args.output, serialized)
        if args.report is not None:
            _atomic_write(args.report, report)
        if args.output is None:
            sys.stdout.write(serialized)
        if result["errors"]:
            print("处理完成，但有 {} 条输入错误；有效结果已保留，详见 errors。".format(len(result["errors"])), file=sys.stderr)
            return 1
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
