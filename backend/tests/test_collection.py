from datetime import datetime, timezone
import httpx
import pytest


def test_list_parser_preserves_old_policy_and_pagination():
    from campus_backend.collection.html import parse_list, parse_detail
    source={'url':'https://cse.csu.edu.cn/index/tzgg.htm','article_url_pattern':r'/info/\d+/\d+\.htm','allowed_hosts':['cse.csu.edu.cn']}
    html='<ul><li><a href="../info/1040/1.htm">推免政策</a><span>2020-01-01</span></li><li><a href="../info/1040/2.htm">比赛报名</a>2026-10-30</li></ul><a href="tzgg/9.htm">下页</a>'
    result=parse_list(html, source, source['url'])
    assert len(result['items'])==2
    assert result['items'][0]['published_at']=='2020-01-01'
    assert result['next_urls']==['https://cse.csu.edu.cn/index/tzgg/9.htm']
    detail=parse_detail('<html><h1>比赛报名</h1><div id="vsb_content"><p>本科生报名。</p><img src="a.png"><a href="a.pdf">附件</a></div><footer>联系老师</footer></html>',source,'https://cse.csu.edu.cn/info/1040/2.htm')
    assert '联系老师' not in detail['html']
    assert len(detail['assets'])==2


def test_empty_parse_is_error_not_no_notices():
    from campus_backend.collection.html import parse_list, ParseError
    with pytest.raises(ParseError):
        parse_list('<h1>统一身份认证</h1><input type="password">',{'url':'https://csu.edu.cn/a'},'https://csu.edu.cn/a')
    with pytest.raises(ParseError):
        parse_list('<html><nav>学校首页</nav></html>',{'url':'https://csu.edu.cn/a'},'https://csu.edu.cn/a')


def test_http_limits_redirect_allowlist_and_retry_after():
    from campus_backend.collection.http import PublicHTTPClient, FetchError
    requests=[]
    def handler(req):
        requests.append(str(req.url))
        if req.url.path=='/redirect':
            return httpx.Response(302,headers={'location':'http://127.0.0.1/secret'})
        if req.url.path=='/limited':
            return httpx.Response(429,headers={'retry-after':'120'})
        return httpx.Response(200,content=b'x'*100)
    clock=[0.0]
    http=PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0,clock=lambda:clock[0])
    with pytest.raises(FetchError) as exc:
        http.get('https://csu.edu.cn/redirect',['csu.edu.cn'])
    assert exc.value.code=='blocked_url'
    assert len(requests)==1
    with pytest.raises(FetchError) as exc:
        http.get('https://csu.edu.cn/limited',['csu.edu.cn'])
    assert exc.value.retry_after==120
    clock[0]=121
    with pytest.raises(FetchError) as exc:
        http.get('https://csu.edu.cn/large',['csu.edu.cn'],max_bytes=20)
    assert exc.value.code=='too_large'


def test_network_failure_can_recover():
    from campus_backend.collection.http import PublicHTTPClient, FetchError
    calls=[]
    def handler(req):
        calls.append(1)
        if len(calls)==1: raise httpx.ConnectError('offline')
        return httpx.Response(200,text='可读取')
    clock=[0.0]
    http=PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0,clock=lambda:clock[0])
    with pytest.raises(FetchError) as exc:
        http.get('https://csu.edu.cn/a',['csu.edu.cn'])
    assert exc.value.code=='network_error'
    clock[0]=30
    assert http.get('https://csu.edu.cn/a',['csu.edu.cn'])['status']==200


def test_embedded_policy_pdf_is_extracted_without_executing_script():
    from campus_backend.collection.html import parse_detail
    html='''<div id="vsb_content"><script>var vsb_pdf_image_data = ["/__local/page1.jpg"];showVsbpdfIframe('/__local/policy.pdf','100%','800',vsb_pdf_image_data);</script></div>'''
    result=parse_detail(html,{},'https://math.csu.edu.cn/info/1/2.htm')
    assert any(a['url']=='https://math.csu.edu.cn/__local/policy.pdf' for a in result['assets'])
    assert 'showVsbpdfIframe' not in result['html']


def test_generic_pagination_selector_does_not_queue_articles_or_navigation():
    from campus_backend.collection.html import parse_list
    html='<a href="/info/1/2.htm">通知标题</a><a href="/about.htm">学院概况</a><a href="/list/2.htm">下页</a><a href="/list/1.htm">尾页</a>'
    source={'pagination_selector':'a[href]','pagination_link_texts':['下页','下一页','尾页'],'allowed_hosts':['csu.edu.cn']}
    assert parse_list(html,source,'https://csu.edu.cn/list.htm')['next_urls']==['https://csu.edu.cn/list/2.htm']


def test_retry_after_is_shared_by_all_requests_on_same_host():
    from campus_backend.collection.http import PublicHTTPClient,FetchError
    seen=[]
    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(429,headers={'retry-after':'1200'})
    client=PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0)
    for path in ('a','b'):
        with pytest.raises(FetchError):
            client.get('https://csu.edu.cn/'+path,['csu.edu.cn'])
    assert len(seen)==1


def test_official_pagination_template_and_outside_attachment_list():
    from campus_backend.collection.html import parse_list,parse_detail
    source={'url':'https://cxcygl.csu.edu.cn/article/lists/3','allowed_hosts':['cxcygl.csu.edu.cn'],
            'article_url_pattern':r'/article/detail/3/\d+',
            'pagination_template':'https://cxcygl.csu.edu.cn/article/lists/3/{page}',
            'body_selector':'.content_detail','asset_selector':'.upload_list a[href]'}
    html='<a href="/article/detail/3/173">学生创新班通知</a><script>$(".page").pagination({totalData:"48",showData:"8",current:"1"})</script>'
    assert parse_list(html,source,source['url'])['next_urls']==['https://cxcygl.csu.edu.cn/article/lists/3/2']
    detail=parse_detail('<div class="content_detail">学生提交材料</div><div class="upload_list"><a href="/cms/front/article/download?aid=173&id=145">报名表</a></div>',source,'https://cxcygl.csu.edu.cn/article/detail/3/173')
    assert len(detail['assets'])==1


def test_student_entry_filters_navigation_but_accepts_new_calendar_id():
    from campus_backend.collection.html import parse_list
    source={'allowed_hosts':['csu.edu.cn'],'article_url_pattern':r'/info/1050/\d+\.htm','title_include_pattern':'手册|校历|作息|班车'}
    html='<a href="/info/1050/9999.htm">2027学年校历</a><a href="/info/1050/9998.htm">采购公告</a>'
    result=parse_list(html,source,'https://csu.edu.cn/students.htm')
    assert [item['title'] for item in result['items']]==['2027学年校历']


def test_attachment_uses_its_official_article_referer(tmp_path):
    from campus_backend.collection.http import PublicHTTPClient
    from campus_backend.collection.service import CollectionService
    from campus_backend.core.artifacts import AssetStore
    page='https://yz.csu.edu.cn/info/1012/1539.htm'
    seen=[]
    def handler(req):
        seen.append((req.url.path,req.headers.get('referer')))
        if req.url.path.startswith('/info/'):
            return httpx.Response(200,text='<div id="vsb_content">报名材料<a href="/system/_content/download.jsp?wbfileid=1">附件.pdf</a></div>')
        if req.headers.get('referer')==page:
            return httpx.Response(200,content=b'%PDF-1.4 sample',headers={'content-type':'application/pdf'})
        return httpx.Response(200,text='<h1>附件下载</h1>请输入验证码')
    service=CollectionService(PublicHTTPClient(transport=httpx.MockTransport(handler),min_interval=0),AssetStore(tmp_path))
    source={'source_id':'s','name':'研究生院','school_id':'csu','url':'https://yz.csu.edu.cn/list.htm','allowed_hosts':['yz.csu.edu.cn']}
    raw=service.article(source,{'url':page,'title':'报名通知'},now=datetime.now(timezone.utc))
    assert raw['errors']==[]
    assert any(a['filename']=='附件.pdf' and a['status']=='complete' for a in raw['payload']['assets'])
