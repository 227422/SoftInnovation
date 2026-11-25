"""Read and validate administrator-owned source configuration."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_REGISTRY=Path(__file__).parent/'data/runtime_registry.json'


def load_registry(path=None):
    registry=json.loads(Path(path or DEFAULT_REGISTRY).read_text(encoding='utf-8'))
    if registry.get('schema_version')!='1.0' or not isinstance(registry.get('sources'),list):
        raise ValueError('来源清单版本或格式不支持')
    seen=set()
    for source in registry['sources']:
        source_id=source['source_id']
        if source_id in seen:
            raise ValueError('来源编号重复')
        seen.add(source_id)
        parsed=urlsplit(source['url'])
        if parsed.scheme not in ('https','http') or parsed.hostname not in source['allowed_hosts']:
            raise ValueError(f'来源链接与允许域名不一致：{source_id}')
        if source.get('article_url_pattern'):
            pattern=re.compile(source['article_url_pattern'])
            samples=source.get('sample_urls',[])
            if samples and not any(pattern.search(url) for url in samples):
                raise ValueError(f'文章规则不能匹配核验样本：{source_id}')
    return registry


def public_source(row):
    fields=('source_id','school_id','unit_id','name','url','channel_description','status','state',
            'content_access','last_attempt_at','last_success_at','next_check_at','last_error',
            'checks','history_status','history_mode','history_note','audited_at','notes')
    return {key:row.get(key) for key in fields}
