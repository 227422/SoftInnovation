from datetime import datetime, timedelta, timezone

import pytest


def stores(tmp_path):
    from campus_backend.core.config import Settings
    from campus_backend.core.db import build_engine, make_session_factory
    from campus_backend.database import initialize_database
    from campus_backend.collection.persistence.repository import SQLAlchemyJobStore
    from campus_backend.sources.persistence.repository import SQLAlchemySourceStore
    from campus_backend.notices.persistence.repository import SQLAlchemyNoticeStore
    settings = Settings(database_url=f'sqlite:///{tmp_path / "storage.db"}')
    initialize_database(settings, seed=False)
    factory = make_session_factory(build_engine(settings.database_url))
    return SQLAlchemyJobStore(factory), SQLAlchemySourceStore(factory), SQLAlchemyNoticeStore(factory)


def test_job_lease_retry_and_late_worker_cannot_commit(tmp_path):
    jobs, _, _ = stores(tmp_path)
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    jobs.enqueue('check:s1', 'source', 's1', {'url': 'https://example.com'}, now)
    job = jobs.claim(now, lease_seconds=10)
    assert job['id'] == 'check:s1'
    assert jobs.claim(now) is None
    replacement = jobs.claim(now + timedelta(seconds=11))
    assert replacement['lease_token'] != job['lease_token']
    assert jobs.finish(job, now + timedelta(seconds=12)) is False
    assert jobs.retry(replacement, now + timedelta(seconds=13), delay=30, error='offline')
    assert jobs.claim(now + timedelta(seconds=42)) is None
    assert jobs.claim(now + timedelta(seconds=43))['attempts'] == 3


def test_versions_preserve_success_and_ignore_old_processing(tmp_path):
    from campus_backend.core.artifacts import make_artifact
    jobs, sources, notices = stores(tmp_path)
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    sources.sync([{'source_id':'s1','school_id':'csu','name':'官网','url':'https://csu.edu.cn/a','status':'enabled','allowed_hosts':['csu.edu.cn']}], now)
    payload = {'title':'测试','source_id':'s1','school_id':'csu','source_url':'https://csu.edu.cn/n','body_status':'full','html':'<p>原文</p>'}
    raw = make_artifact('raw','n1','v1',payload)
    assert notices.save_raw(raw, now)
    assert not notices.save_raw(raw, now)
    document = make_artifact('document','n1','v1',{'title':'测试','content':'原文','body_status':'full'})
    analysis = make_artifact('analysis','n1','v1',{})
    assert notices.publish(document, analysis, now)
    notices.save_raw(make_artifact('raw','n1','v2',payload | {'html':'<p>新版</p>'}),now)
    assert notices.get('n1')['document']['payload']['content'] == '原文'
    assert not notices.publish(document, analysis, now)
    notices.record_failure('n1','network_error','稍后重试',now)
    assert notices.get('n1')['document']['payload']['content'] == '原文'
    assert notices.get('n1')['fetch_status'] == 'network_error'
    assert jobs.counts()['pending'] == 2


def test_unchanged_success_recovers_state_and_partial_does_not_replace_full(tmp_path):
    from campus_backend.core.artifacts import make_artifact
    _,sources,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    source={'source_id':'s','school_id':'csu','name':'官网','url':'https://csu.edu.cn','status':'enabled','allowed_hosts':['csu.edu.cn']}
    sources.sync([source],now)
    payload={'title':'学生通知','source_id':'s','school_id':'csu','source_url':'https://csu.edu.cn/n','body_status':'full'}
    raw=make_artifact('raw','n','v1',payload)
    notices.save_raw(raw,now)
    notices.publish(make_artifact('document','n','v1',{'title':'学生通知','content':'完整正文附件','body_status':'full'}),make_artifact('analysis','n','v1',{}),now)
    notices.record_failure('n','network_error','断网',now)
    later=now+timedelta(seconds=30)
    notices.save_raw(raw,later)
    assert notices.get('n')['fetch_status']=='full'
    assert notices.get('n')['fetch_error'] is None
    assert notices.get('n')['last_success_at']==later.isoformat()
    notices.save_raw(make_artifact('raw','n','v2',payload|{'body_status':'partial'}),later)
    assert not notices.publish(make_artifact('document','n','v2',{'title':'学生通知','content':'只得到部分正文','body_status':'partial'}),make_artifact('analysis','n','v2',{}),later)
    assert notices.get('n')['document']['payload']['content']=='完整正文附件'


def test_old_response_from_different_source_cannot_regress_version(tmp_path):
    from campus_backend.core.artifacts import make_artifact
    _,_,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    payload={'title':'通知','source_id':'a','source_url':'https://csu.edu.cn/n','school_id':'csu','body_status':'full'}
    newer=make_artifact('raw','n','new',payload,now=now+timedelta(seconds=1))
    older=make_artifact('raw','n','old',payload|{'source_id':'b'},now=now)
    assert notices.save_raw(newer,now+timedelta(seconds=2))
    assert not notices.save_raw(older,now+timedelta(seconds=3))
    assert notices.get('n')['latest_version']=='new'
    assert set(notices.get('n')['source_ids'])=={'a','b'}


def test_old_failure_cannot_replace_new_pending_raw_or_status(tmp_path):
    from campus_backend.core.artifacts import make_artifact
    _,_,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    payload={'title':'通知','source_id':'a','source_url':'https://csu.edu.cn/n','school_id':'csu','body_status':'full','html':'<p>新正文</p>'}
    notices.save_raw(make_artifact('raw','n','good',payload,now=now+timedelta(seconds=1)),now+timedelta(seconds=2))
    older=make_artifact('raw','n','failed',payload|{'body_status':'title_only','html':''},now=now)
    assert not notices.save_raw(older,now+timedelta(seconds=3))
    assert not notices.record_failure('n','network_error','旧请求失败',now+timedelta(seconds=3),fetch_started_at=now)
    assert notices.get('n')['latest_version']=='good'
    assert notices.get('n')['fetch_error'] is None


def test_partial_refresh_does_not_drop_successful_fragments(tmp_path):
    from campus_backend.core.artifacts import make_artifact
    _,_,notices=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    p={'title':'通知','source_id':'a','source_url':'https://csu.edu.cn/n','school_id':'csu','body_status':'partial'}
    for version,content,segments in [('v1','正文\n附件A',[{'text':'正文','asset_id':'h'},{'text':'附件A','asset_id':'a'}]),('v2','正文\n附件B',[{'text':'正文','asset_id':'h'},{'text':'附件B','asset_id':'b'}])]:
        notices.save_raw(make_artifact('raw','n',version,p,now=now),now)
        notices.publish(make_artifact('document','n',version,p|{'content':content,'segments':segments},now=now),make_artifact('analysis','n',version,{},now=now),now)
    assert '附件A' in notices.get('n')['document']['payload']['content']
    assert notices.get('n')['fetch_status']=='stale'


def test_history_jobs_get_a_turn_even_when_new_details_keep_arriving(tmp_path):
    jobs,_,_=stores(tmp_path)
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    jobs.enqueue('history','history','s',{},now)
    jobs.enqueue('detail','detail','s',{},now+timedelta(seconds=301))
    assert jobs.claim(now+timedelta(seconds=301))['id']=='history'


def test_host_backoff_is_persistent_and_cannot_be_shortened(tmp_path):
    jobs,_,_=stores(tmp_path)
    jobs.set_host_backoff('csu.edu.cn',500,'rate_limited')
    jobs.set_host_backoff('csu.edu.cn',400,'network_error')
    reopened,_,_=stores(tmp_path)
    assert reopened.get_host_backoff('csu.edu.cn')=={'until':500,'code':'rate_limited'}
