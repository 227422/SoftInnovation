"""按「通知公告优先」的口径精简来源注册表。

背景：原注册表 482 条，其中 22 条是同一页面的重复登记（最多一个 jsp 挂了 14 个栏目名），
另有 194 条 policy（规章制度/文件汇编）本就不产出通知。这里做三件事：

1. 按 URL 去重，保留名字最像通知栏目的一条；
2. 按名称与路径分成三档：notice（通知公告）、mixed（学生/教学相关的混合栏目）、archive（其余）；
3. 只把 notice + mixed 写回 runtime_registry.json，其余条目留在 archive 文件里备查。

写法上不改任何抓取规则（选择器、正则、翻页），只收窄「抓哪些页面」。

用法：
    python scripts/prune_sources.py --dry-run   # 只打印分布，不写文件
    python scripts/prune_sources.py             # 写回注册表并归档原文件
"""
import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DATA = Path(__file__).resolve().parent.parent / 'src/campus_backend/sources/data'
REGISTRY = DATA / 'runtime_registry.json'
ARCHIVE = DATA / 'runtime_registry.full.json'

NOTICE_WORDS = ('通知', '公告', '公示', '通报')
NOTICE_PATHS = ('tzgg', 'jwtz', 'jwgg', 'xgtz', 'ggtz', 'gsgg', 'tzgg', 'notice', 'gonggao', 'ggao')
# 学生真正会看的栏目：学工、团学、奖助、就业、创新创业、心理、党建。
STUDENT_WORDS = ('学生', '学工', '团学', '团委', '奖', '资助', '评优', '就业', '竞赛',
                 '创新', '实践', '心理', '党建')
# 制度文件、下载中心、新闻动态：都不产出可推送的通知。
POLICY_WORDS = ('制度', '规章', '文件', '下载', '表格', '手册', '指南', '方案', '办法',
                '流程', '信息公开', '目录', '章程', '清单')
NOISE_WORDS = ('新闻', '动态', '风采', '掠影', '图片', '视频', '校友', '工会', '离退休',
               '采购', '招标', '仪器', '实验室安全', '学报', '院友')


def canonical(url):
    parts = urlsplit(url)
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip("/").lower()}'


def tier_of(source):
    name = source.get('name', '')
    path = urlsplit(source['url']).path.lower()
    if source.get('kind') == 'policy':
        return 'archive'
    if any(word in name for word in NOTICE_WORDS) or any(word in path for word in NOTICE_PATHS):
        return 'notice'
    if any(word in name for word in POLICY_WORDS) or any(word in name for word in NOISE_WORDS):
        return 'archive'
    if any(word in name for word in STUDENT_WORDS):
        return 'student'
    # 招生信息、培养管理、学术/国际交流、教学管理这类栏目以固定介绍为主，先留档。
    return 'archive'


def name_rank(source):
    """同名页面里挑一条：先看是不是通知栏目，再看名字长短。"""
    name = source.get('name', '')
    return (0 if any(w in name for w in NOTICE_WORDS) else 1, len(name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    # 全量原表只保留一份；重复执行时始终以它为准，避免越剪越少。
    full = ARCHIVE if ARCHIVE.exists() else REGISTRY
    raw = json.loads(full.read_text(encoding='utf-8'))
    sources = raw['sources']

    by_url = {}
    for source in sources:
        key = canonical(source['url'])
        current = by_url.get(key)
        if current is None or name_rank(source) < name_rank(current):
            by_url[key] = source
    unique = list(by_url.values())

    tiers = {source['source_id']: tier_of(source) for source in unique}
    kept = [s for s in unique if tiers[s['source_id']] in ('notice', 'student')]
    dropped = [s for s in unique if tiers[s['source_id']] == 'archive']

    print('原始条目      ', len(sources))
    print('URL 去重后    ', len(unique), f'(合并 {len(sources) - len(unique)} 条重复登记)')
    print('保留 notice   ', sum(1 for s in unique if tiers[s['source_id']] == 'notice'))
    print('保留 student  ', sum(1 for s in unique if tiers[s['source_id']] == 'student'))
    print('归档 archive  ', len(dropped))
    print('保留合计      ', len(kept))
    print('站点数        ', len({urlsplit(s['url']).hostname for s in kept}))
    print('kind 分布     ', dict(Counter(s.get('kind') for s in kept)))
    if args.dry_run:
        print('\n--- notice 样例 ---')
        for s in [x for x in unique if tiers[x['source_id']] == 'notice'][:12]:
            print('  ', s['name'], '|', urlsplit(s['url']).path)
        print('--- student 样例 ---')
        for s in [x for x in unique if tiers[x['source_id']] == 'student'][:12]:
            print('  ', s['name'], '|', urlsplit(s['url']).path)
        print('--- archive 样例 ---')
        for s in dropped[:10]:
            print('  ', s['name'], '|', urlsplit(s['url']).path)
        return

    if full is REGISTRY:
        shutil.copy2(REGISTRY, ARCHIVE)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for source in kept:
        source['tier'] = tiers[source['source_id']]
        source['pruned_at'] = now
        source['status'] = 'enabled'
    payload = dict(raw)
    payload['sources'] = kept
    payload.setdefault('notes', {})
    payload['notes'] = {
        'pruned_at': now,
        'rule': 'URL 去重；只保留通知公告类（notice）与学生相关栏目（student）；'
                'policy、规章制度、下载中心、新闻动态、招生/培养/学术交流类归档',
        'archive': ARCHIVE.name,
        'original_count': len(sources),
    }
    REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n已写入', REGISTRY, '共', len(kept), '条；原表归档到', ARCHIVE.name)


if __name__ == '__main__':
    main()
