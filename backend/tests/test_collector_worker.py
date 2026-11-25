from datetime import datetime, timedelta, timezone
import httpx
import pytest
from test_collector_storage import stores


def test_worker_recovers_after_thirty_seconds_and_keeps_old_content(tmp_path):
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.core.artifacts import AssetStore
    jobs,sources,notices=stores(tmp_path)
    current=[datetime(2026,10,31,tzinfo=timezone.utc)]
    state={'offline':True,'body':'本科生竞赛报名截止2026年11月5日。比赛结束时间2026年11月10日。'}
    source={'source_id':'s1','school_id':'csu','school':'中南大学','name':'本科生院','url':'https://csu.edu.cn/list.htm',
            'allowed_hosts':['csu.edu.cn'],'status':'enabled','article_url_pattern':r'/info/\d+/\d+\.htm'}
    sources.sync([source],current[0])
    def handler(req):
        if state['offline']: raise httpx.ConnectError('offline')
        if req.url.path=='/list.htm': return httpx.Response(200,text='<li><a href="/info/1/2.htm">本科生竞赛报名通知</a>2026-10-30</li>')
        return httpx.Response(200,text='<h1>本科生竞赛报名通知</h1><div id="vsb_content">'+state['body']+'</div>')
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),
                           PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0,clock=lambda:current[0].timestamp()),clock=lambda:current[0])
    worker.tick(max_jobs=20)
    assert sources.get('s1')['state']=='network_error'
    assert sources.get('s1')['last_success_at'] is None
    state['offline']=False
    current[0]+=timedelta(seconds=29)
    assert worker.tick(max_jobs=20)['processed']==0
    current[0]+=timedelta(seconds=1)
    worker.tick(max_jobs=20)
    assert sources.get('s1')['state']=='ready'
    found=notices.list()[0]
    assert '本科生竞赛' in found['document']['payload']['content']
    saved=found['current_version']
    state['offline']=True
    current[0]+=timedelta(seconds=1200)
    worker.tick(max_jobs=20)
    assert notices.get(found['notice_id'])['current_version']==saved
    state['offline']=False
    state['body']='本科生竞赛报名延期至2026年11月8日。比赛结束时间2026年11月10日。'
    current[0]+=timedelta(seconds=30)
    worker.tick(max_jobs=20)
    assert notices.get(found['notice_id'])['current_version']!=saved


def test_history_pages_persist_for_restart_without_thirty_day_cutoff(tmp_path):
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.core.artifacts import AssetStore
    jobs,sources,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    source={'source_id':'s1','school_id':'csu','name':'政策','url':'https://csu.edu.cn/list.htm','status':'enabled','allowed_hosts':['csu.edu.cn']}
    sources.sync([source],now)
    def handler(req):
        if req.url.path=='/list.htm': return httpx.Response(200,text='<a href="/info/1/1.htm">2020学生政策</a><a href="/list/1.htm">下页</a>')
        if req.url.path=='/list/1.htm': return httpx.Response(200,text='<a href="/info/1/2.htm">2019学生政策</a>')
        return httpx.Response(200,text='<div id="vsb_content">本科生管理办法，自2019年9月1日起施行。</div>')
    http=PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0)
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),http,clock=lambda:now)
    worker.tick(max_jobs=1)
    assert jobs.counts()['pending']>=2
    restarted=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),http,clock=lambda:now)
    restarted.tick(max_jobs=20)
    assert len(notices.list())==2
    assert sources.get('s1')['history_status']=='complete'
    later=now+timedelta(seconds=1200)
    calls=[]
    def changed(req):
        calls.append(req.url.path)
        if req.url.path=='/info/1/2.htm': return httpx.Response(200,text='<div id="vsb_content">本科生管理办法，现行有效。最新修订版本。</div>')
        return handler(req)
    restarted.http=PublicHTTPClient(transport=httpx.MockTransport(changed),min_interval=0)
    restarted.collection.http=restarted.http
    restarted.clock=lambda:later
    restarted.tick(max_jobs=20)
    assert '/info/1/2.htm' in calls
    assert sources.get('s1')['history_status']=='complete'


@pytest.mark.parametrize('error_code', ['ocr_unavailable', 'ocr_timeout', 'ocr_failed'])
def test_transient_ocr_failure_is_retried_without_source_change(tmp_path,monkeypatch,error_code):
    from campus_backend.core.artifacts import AssetStore,make_artifact
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.collection.http import PublicHTTPClient
    jobs,sources,notices=stores(tmp_path)
    now=[datetime(2026,10,31,tzinfo=timezone.utc)]
    sources.sync([{'source_id':'s','school_id':'csu','name':'公告','url':'https://csu.edu.cn','status':'enabled','allowed_hosts':['csu.edu.cn']}],now[0])
    raw=make_artifact('raw','n','v',{'title':'本科生竞赛通知','source_id':'s','school_id':'csu','source_url':'https://csu.edu.cn/n','body_status':'full','published_at':'2026-10-31'},now=now[0])
    notices.save_raw(raw,now[0])
    count=[0]
    def extract(raw,*args,**kwargs):
        count[0]+=1
        bad=count[0]==1
        return make_artifact('document','n','v',raw['payload']|{'body_status':'title_only' if bad else 'complete','content':'' if bad else '本科生竞赛报名截止2026年11月5日。'},status='failed' if bad else 'complete',errors=[{'code':error_code,'message':'暂不可用'}] if bad else [],now=now[0])
    monkeypatch.setattr('campus_backend.collection.worker.extract_document',extract)
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),PublicHTTPClient(transport=httpx.MockTransport(lambda r:httpx.Response(200)),min_interval=0),clock=lambda:now[0])
    worker.tick(schedule=False,max_jobs=10)
    assert jobs.counts()['pending']==1
    now[0]+=timedelta(seconds=60)
    worker.tick(schedule=False,max_jobs=10)
    assert '本科生竞赛' in notices.get('n')['document']['payload']['content']
    assert jobs.counts()['pending']==0


def test_unexpected_one_job_error_does_not_stop_other_sources(tmp_path,monkeypatch):
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.core.artifacts import AssetStore
    jobs,sources,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    sources.sync([{'source_id':key,'school_id':'csu','name':'公告','url':'https://csu.edu.cn/'+key,'status':'enabled','allowed_hosts':['csu.edu.cn']} for key in ('a','b')],now)
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),PublicHTTPClient(transport=httpx.MockTransport(lambda r:httpx.Response(200)),min_interval=0),clock=lambda:now)
    def process(source,job):
        if source['source_id']=='a': raise RuntimeError('unexpected internal detail')
    monkeypatch.setattr(worker,'_list',process)
    stats=worker.tick(max_jobs=2)
    assert stats['processed']==1 and stats['failed']==1
    assert jobs.counts()['pending']==1 and jobs.counts()['done']==1


def test_direct_article_cannot_claim_success_before_fetch(tmp_path):
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.core.artifacts import AssetStore
    jobs,sources,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    sources.sync([{'source_id':'s','school_id':'csu','name':'学生手册','url':'https://csu.edu.cn/manual.pdf','status':'enabled','allowed_hosts':['csu.edu.cn'],'direct_article':True}],now)
    def offline(req): raise httpx.ConnectError('offline')
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),PublicHTTPClient(transport=httpx.MockTransport(offline),min_interval=0),clock=lambda:now)
    worker.tick(max_jobs=10)
    assert sources.get('s')['last_success_at'] is None
    assert sources.get('s')['state']=='network_error'


def test_history_unknown_is_not_reported_complete(tmp_path):
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.core.artifacts import AssetStore
    jobs,sources,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    sources.sync([{'source_id':'s','school_id':'csu','name':'首页','url':'https://csu.edu.cn/index.htm','status':'enabled','allowed_hosts':['csu.edu.cn'],'history_mode':'unknown'}],now)
    http=PublicHTTPClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,text='<a href="/info/1/2.htm">学生通知标题</a>')),min_interval=0)
    worker=CollectorWorker(sources,jobs,notices,AssetStore(tmp_path/'assets'),http,clock=lambda:now)
    worker.tick(max_jobs=1)
    assert sources.get('s')['history_status']=='unknown'


def test_empty_ocr_keeps_partial_without_automatic_loop_and_can_reprocess(tmp_path, monkeypatch):
    from campus_backend.core.artifacts import AssetStore, make_artifact
    from campus_backend.collection.worker import CollectorWorker
    from campus_backend.collection.http import PublicHTTPClient
    jobs, sources, notices = stores(tmp_path)
    now = [datetime(2026, 10, 31, tzinfo=timezone.utc)]
    sources.sync([{'source_id': 's', 'school_id': 'csu', 'name': '公告', 'url': 'https://csu.edu.cn',
                   'status': 'enabled', 'allowed_hosts': ['csu.edu.cn']}], now[0])
    raw = make_artifact('raw', 'n', 'v1', {'title': '本科生竞赛通知', 'source_id': 's', 'school_id': 'csu',
                        'source_url': 'https://csu.edu.cn/n', 'body_status': 'full', 'published_at': '2026-10-31'}, now=now[0])
    notices.save_raw(raw, now[0])
    count = [0]
    empty = [True]
    def extract(source, *args, **kwargs):
        count[0] += 1
        return make_artifact('document', 'n', source['content_version'], source['payload'] | {
            'body_status': 'partial' if empty[0] else 'complete',
            'content': '本科生竞赛报名截止2026年11月5日。' + ('' if empty[0] else '图片附加条件。')},
            status='partial' if empty[0] else 'complete',
            errors=[{'code': 'ocr_empty', 'message': '未识别出文字'}] if empty[0] else [], now=now[0])
    monkeypatch.setattr('campus_backend.collection.worker.extract_document', extract)
    worker = CollectorWorker(sources, jobs, notices, AssetStore(tmp_path / 'assets'),
        PublicHTTPClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)), min_interval=0), clock=lambda: now[0])
    worker.tick(schedule=False, max_jobs=10)
    saved = notices.get('n')['document']
    assert saved['status'] == 'partial'
    assert saved['errors'][0]['code'] == 'ocr_empty'
    assert '本科生竞赛' in saved['payload']['content']
    assert jobs.counts().get('pending', 0) == 0
    now[0] += timedelta(seconds=1200)
    notices.save_raw(raw, now[0])
    worker.tick(schedule=False, max_jobs=10)
    assert count[0] == 1
    # Explicit reprocess after an extractor change is still supported.
    empty[0] = False
    jobs.enqueue('document:n:v1', 'document', 's', {'notice_id': 'n', 'content_version': 'v1'}, now[0], repeat=True)
    worker.tick(schedule=False, max_jobs=10)
    assert count[0] == 2
    assert notices.get('n')['document']['status'] == 'complete'
    # A changed original version is a new independent processing job.
    changed = make_artifact('raw', 'n', 'v2', raw['payload'], now=now[0])
    notices.save_raw(changed, now[0])
    worker.tick(schedule=False, max_jobs=10)
    assert count[0] == 3
    assert notices.get('n')['current_version'] == 'v2'
