from datetime import datetime, timezone
from fastapi.testclient import TestClient


def seed_notice(app, *, school_id='csu', notice_id='test-notice', content='中南大学本科生竞赛，报名截止2026年11月5日。比赛结束时间2026年11月10日。'):
    from campus_backend.core.artifacts import make_artifact
    from campus_backend.notices.persistence.repository import SQLAlchemyNoticeStore
    from campus_backend.sources.persistence.repository import SQLAlchemySourceStore
    from campus_backend.classification.service import analyze_document
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    app.state.clock=lambda:now
    sources=SQLAlchemySourceStore(app.state.session_factory)
    sources.sync([{'source_id':'s1','school_id':school_id,'name':'测试官方栏目','url':'https://csu.edu.cn/notice.htm',
                   'allowed_hosts':['csu.edu.cn'],'status':'enabled','channel_description':'发布学生学习与竞赛事项'}],now)
    payload={'title':'本科生竞赛报名通知','source_id':'s1','source_name':'学校','school_id':school_id,'school':'中南大学',
             'source_url':'https://csu.edu.cn/info/1/2.htm','published_at':'2026-10-30','body_status':'full','content':content}
    store=SQLAlchemyNoticeStore(app.state.session_factory)
    store.save_raw(make_artifact('raw',notice_id,'v1',payload,now=now),now)
    doc=make_artifact('document',notice_id,'v1',payload,now=now)
    store.publish(doc,analyze_document(doc,now=now),now)
    return store


def register(client,email='notice@example.com'):
    response=client.post('/v1/auth/register',json={'email':email,'password':'long secure password 123'})
    assert response.status_code==201,response.text


def test_notice_list_detail_and_source_contract(app,client):
    seed_notice(app)
    assert client.get('/v1/me/notices').status_code==401
    register(client)
    result=client.get('/v1/me/notices')
    assert result.status_code==200,result.text
    data=result.json()
    assert data['total']==1
    assert data['items'][0]['category'] in ('research_innovation','financial_aid','daily')
    detail=client.get('/v1/me/notices/test-notice').json()
    assert '本科生竞赛' in detail['content']
    assert detail['sources'][0]['name']
    assert detail['body_status']=='full'
    assert 'raw' not in detail and 'html' not in detail


def test_api_does_not_hide_old_notices(app,client):
    """推送只按时间排序，不再按发布时长隐藏。"""
    seed_notice(app)
    register(client)
    # 26 天后：已远超旧的隐藏边界，但会话仍在有效期内。
    app.state.clock=lambda:datetime(2026,11,25,tzinfo=timezone.utc)
    assert client.get('/v1/me/notices').json()['total']==1


def test_account_cannot_read_another_school_or_override_identity(app,client):
    seed_notice(app,school_id='other-school')
    register(client)
    assert client.get('/v1/me/notices',params={'school_id':'other-school','user_id':'other'}).json()['total']==0
    assert client.get('/v1/me/notices/test-notice').status_code==404


def test_feed_sorts_by_published_at_desc():
    from campus_backend.notices.service import sort_key
    older={'published_at':'2026-10-01','notice_id':'a'}
    newer={'published_at':'2026-10-30','notice_id':'b'}
    assert sort_key(newer)<sort_key(older)


def test_feed_falls_back_to_last_updated_when_unpublished():
    from campus_backend.notices.service import sort_key
    undated={'published_at':None,'last_updated_at':'2026-11-02T00:00:00+00:00','notice_id':'c'}
    older={'published_at':'2026-10-30','notice_id':'d'}
    assert sort_key(undated)<sort_key(older)
