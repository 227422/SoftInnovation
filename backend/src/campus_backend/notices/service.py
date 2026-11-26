"""Personalized, time-sensitive read models built from independent stored stages."""
from copy import deepcopy
from datetime import datetime, timezone

from campus_backend.classification.service import personalize
from campus_backend.classification.lifecycle import deadline_moment
from campus_backend.core.artifacts import make_artifact
from campus_backend.core.errors import AppError
from campus_backend.sources.service import public_source


def profile_input(profile):
    if profile is None:
        return {'school':'中南大学'}, 'csu', 0
    return {'school':profile.school_name,'college':profile.college_name,'major':profile.major_name,'grade':profile.grade},profile.school_id,profile.version


def _personal(row,profile,now):
    document=deepcopy(row['document'])
    if document is None:
        payload=row['raw']['payload']
        document=make_artifact('document',row['notice_id'],row['latest_version'],
                              {k:v for k,v in payload.items() if k not in ('html','assets')} | {'content':'','body_status':'title_only'},
                              status='title_only',now=now)
    if row.get('admitted_at'):
        document['payload']['first_seen_at']=row['admitted_at']
    result=personalize(document,profile,now=now,analysis=row.get('analysis'))
    if row['current_version'] and row['current_version']!=row['latest_version']:
        result['uncertainties'].append('官网原件已变化，当前仍为上一成功版本；最新内容处理中，请核对官方原文')
        result['routing']['notify_eligible']=False
        result['importance']['tentative']=True
        result['lifecycle']['validity']={'status':'unknown','reason':'当前展示内容不是最新原件的完整处理结果','evidence':None}
    validity=result['lifecycle']['validity']
    retryable={'ocr_unavailable','ocr_timeout','ocr_failed','ocr_empty','document_timeout','asset_unavailable','extraction_failed','network_error','rate_limited','http_error'}
    result.update({'content_version':document['content_version'],'latest_version':row['latest_version'],
        'last_updated_at':row['last_success_at'],'fetch_status':row['fetch_status'],'fetch_error':row['fetch_error'],
        'tags':{'importance':result['importance'],'category':result['classification']['category_label'],
                'validity':validity,'urgency':result['urgency']},
        'processing':row['current_version'] != row['latest_version'] or row['fetch_status'] in ('processing','processing_error','stale')
                     or any(error.get('code') in retryable for error in document.get('errors',[]))})
    return result,document


def _time(value,default):
    try:
        moment=datetime.fromisoformat(value)
        return moment.replace(tzinfo=timezone.utc).timestamp() if moment.tzinfo is None else moment.timestamp()
    except (TypeError,ValueError):
        return default


# ---------------------------------------------------------------- 分类归到三个模块
# 后端只做两件事：抓取、归到三档。其余判断一律不参与排序与过滤。
MODULE_OF = {
    'research_innovation': 'research_innovation',
    'financial_aid': 'financial_aid',
}


def module_of(raw_category):
    """八类归三档；只有科研与奖助单独成模块，其余都进日常。"""
    return MODULE_OF.get(raw_category or '', 'daily')


def sort_key(result):
    """只按发布时间倒序；没有发布时间就用入库时间兜底。"""
    published = _time(result.get('published_at'), 0)
    if published <= 0:
        published = _time(result.get('last_updated_at'), 0)
    return (-published, result['notice_id'])


def list_notices(store,profile,*,now,offset=0,limit=50,only_ids=None):
    match,school_id,profile_version=profile_input(profile)
    results=[]
    last_updated=None
    for row in store.list(school_id):
        if only_ids is not None and row['notice_id'] not in only_ids:
            continue
        result,_=_personal(row,match,now)
        results.append(result)
        if row['last_success_at'] and (last_updated is None or row['last_success_at']>last_updated):
            last_updated=row['last_success_at']
    results.sort(key=sort_key)
    for index,result in enumerate(results):
        result['rank']=index+1
    return {'items':results[offset:offset+limit],'total':len(results),'offset':offset,'limit':limit,
            'profile_version':profile_version,'evaluated_at':now.isoformat(),'last_updated_at':last_updated,
            'coverage_url':'/v1/sources','collection_status_url':'/v1/collection/status'}


def get_notice(store,sources,profile,notice_id,*,now):
    match,school_id,version=profile_input(profile)
    row=store.get(notice_id)
    if row is None or row['school_id']!=school_id:
        raise AppError(404,'notice_not_found','未找到该通知')
    result,document=_personal(row,match,now)
    payload=document['payload']
    result.update({'content':payload.get('content',''), 'segments':payload.get('segments',[]),
                   'assets':[{k:v for k,v in asset.items() if k in ('asset_id','filename','media_type','url','status','error','role')}
                             for asset in payload.get('assets',[])],
                   'sources':[public_source(source) for source_id in row['source_ids'] if (source:=sources.get(source_id))],
                   'access_reason':payload.get('access_reason') or next((e.get('message') for e in document.get('errors',[]) if e.get('message')),None),
                   'processing_errors':document.get('errors',[]),'profile_version':version,'evaluated_at':now.isoformat()})
    return result


# ---------------------------------------------------------------- 对外只给界面要用的字段

def public_item(result):
    """列表卡片只需要：标题、时间（截止）、来源、发布时间、分类、关注状态。"""
    classification = result.get('classification') or {}
    raw_category = classification.get('primary_category')
    return {
        'notice_id': result['notice_id'],
        'title': result.get('title'),
        'source': result.get('source'),
        'source_url': result.get('source_url'),
        'published_at': result.get('published_at'),
        'category': module_of(raw_category),
        'raw_category': raw_category,
        'deadline': (result.get('deadline') or {}).get('value'),
        'body_status': result.get('body_status'),
        'follow': result.get('follow'),
    }


def public_page(page):
    return {
        'items': [public_item(item) for item in page['items']],
        'total': page['total'],
        'offset': page['offset'],
        'limit': page['limit'],
        'last_updated_at': page.get('last_updated_at'),
    }


def public_detail(result):
    """详情在此之上再加：正文、官方原文、附件、来源栏目。"""
    data = public_item(result)
    data['content'] = result.get('content') or ''
    data['access_reason'] = result.get('access_reason')
    data['sources'] = [{'name': source.get('name'), 'url': source.get('url')}
                       for source in result.get('sources', [])]
    data['assets'] = [{key: asset.get(key) for key in ('filename', 'url', 'media_type', 'status')}
                      for asset in result.get('assets', [])
                      if asset.get('role') != 'original_html']
    return data
