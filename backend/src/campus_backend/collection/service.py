"""Fetch and normalize a public article; all persistence is injected by the worker."""
import hashlib
import json
import mimetypes
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlencode, urljoin, urlsplit

from campus_backend.core.artifacts import make_artifact
from .html import _clean_title, decode_html, oa_pdf_page, parse_detail, ParseError
from .http import canonical_url, FetchError

_HTML_PREFIX = re.compile(br'\s*<(?:!doctype|html|head|body|div|h1|p|script|meta)(?:\s|>)', re.I)
_MAX_ATTACHMENTS = 30
_MAX_ASSET_BYTES = 32 * 1024 * 1024


def _is_html(response):
    return 'html' in response['media_type'] or bool(_HTML_PREFIX.match(response['data'][:200]))


def notice_id(url, school_id='csu'):
    return hashlib.sha256(f'{school_id}:{canonical_url(url)}'.encode()).hexdigest()[:40]


def job_id(kind, source_id, url):
    return f'{kind}:{source_id}:{hashlib.sha256(url.encode()).hexdigest()[:40]}'


def title_only(source, item, *, code, message, now):
    payload = {'title':item['title'],'source_id':source['source_id'],'source_name':source['name'],
               'school_id':source.get('school_id','csu'),'school':source.get('school','中南大学'),
               'source_url':item['url'],'published_at':item.get('published_at'), 'html':'','assets':[],
               'body_status':'title_only','access_reason':message,'access_code':code}
    version = hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return make_artifact('raw',notice_id(item['url']),version,payload,status='title_only',
                         errors=[{'code':code,'message':message}],now=now)


class CollectionService:
    def __init__(self, http, assets):
        self.http,self.assets=http,assets

    def _oa_attachments(self, page_url, document_id, allowed_hosts):
        endpoint = urljoin(page_url, '/con/xnbg/getFjList')
        response = self.http.post_form(endpoint, allowed_hosts, {'JLNM': document_id, 'WJFL': '11'},
                                       max_bytes=256 * 1024, referer=page_url)
        try:
            rows = json.loads(response['data'])
        except (ValueError, RecursionError):
            raise FetchError('attachment_metadata_invalid', 'OA附件清单不是可识别的JSON') from None
        if not isinstance(rows, list):
            raise FetchError('attachment_metadata_invalid', 'OA附件清单未返回数组')
        endpoint = urljoin(page_url, '/con/xnbg/downLoadFj')
        links = []
        # The main PDF takes one download slot. Keep one extra entry so the
        # common loop reports truncation without making another request.
        for row in rows[:_MAX_ATTACHMENTS]:
            asset_id = row.get('NBBM') if isinstance(row, dict) else None
            filename = row.get('FJMC') if isinstance(row, dict) else None
            if (not isinstance(asset_id, str) or not re.fullmatch(r'[0-9A-Fa-f]{32}', asset_id)
                    or not isinstance(filename, str) or not filename.strip() or len(filename) > 512
                    or filename in ('.', '..') or re.search(r'[/\\\x00-\x1f\x7f]', filename)):
                raise FetchError('attachment_metadata_invalid', 'OA附件清单含有无效的编号或文件名')
            try:
                query = urlencode({'NBBM': asset_id, 'fullfilename': filename})
            except UnicodeError:
                raise FetchError('attachment_metadata_invalid', 'OA附件文件名编码无效') from None
            links.append({'url': f'{endpoint}?{query}', 'filename': filename, 'role': 'attachment'})
        return links

    def article(self, source, item, *, now):
        origin=source.get('discovery_url') if source.get('direct_article') else source.get('url')
        if not origin or urlsplit(origin).hostname not in source['allowed_hosts']:
            origin=source['url']
        response=self.http.get(item['url'],source['allowed_hosts'],max_bytes=_MAX_ASSET_BYTES,referer=origin)
        data=response['data']
        is_html=_is_html(response)
        assets=[]
        errors=[]
        html=''
        title=item['title']
        published_at=item.get('published_at')
        body_asset_id=None
        oa_pdf_id=None
        allowed_hosts=source['allowed_hosts']
        if is_html:
            detail=parse_detail(decode_html(response),source,response['url'])
            html=detail['html']
            # 列表页的链接文字里常带正文摘要，详情页解析出的标题更可信。
            title=detail.get('title') or title
            published_at=detail.get('published_at') or published_at
            original=self.assets.put(data,filename='original.html',media_type='text/html',url=item['url'])
            original['role']='original_html'
            assets.append(original)
            body_asset_id=original['asset_id']
            links=detail['assets']
            oa_pdf_id=detail.get('oa_pdf_id')
            if oa_pdf_id:
                requested_id=oa_pdf_page(item['url'])
                if requested_id is not None and requested_id != oa_pdf_id:
                    raise ParseError('OA公告跳转到不同文档')
                title=detail['title']
                # All OA document requests stay on this public host even when
                # a source also permits links to other registered hosts.
                allowed_hosts=[host for host in allowed_hosts if host.lower() == urlsplit(response['url']).hostname]
                try:
                    links += self._oa_attachments(response['url'], oa_pdf_id, allowed_hosts)
                except FetchError as exc:
                    errors.append({'code':exc.code,'message':exc.message,
                                   'url':urljoin(response['url'], '/con/xnbg/getFjList')})
        else:
            links=[{'url':item['url'],'filename':unquote(PurePosixPath(urlsplit(item['url']).path).name),'role':'attachment'}]
        for index,link in enumerate(links):
            if link['role']=='pdf_fallback_image' and any(a.get('filename')=='embedded.pdf' and a.get('status')=='complete' for a in assets):
                continue
            if index>=_MAX_ATTACHMENTS:
                errors.append({'code':'attachment_limit','message':'附件超过单篇30份处理上限，保留原文入口待处理'})
                break
            try:
                attachment=response if not is_html and index==0 else self.http.get(link['url'],allowed_hosts,max_bytes=_MAX_ASSET_BYTES,referer=response['url'])
                filename=link['filename'] or 'attachment'
                disposition=attachment['headers'].get('content-disposition','')
                if 'filename=' in disposition:
                    filename=unquote(disposition.split('filename=',1)[1].split(';',1)[0].strip('"\''))
                content_type=attachment['media_type']
                if _is_html(attachment):
                    text=decode_html(attachment)
                    if '验证码' in text or '统一身份认证' in text or 'type="password"' in text:
                        raise FetchError('access_restricted','附件仍要求验证码或登录，保留官方入口')
                    raise FetchError('attachment_unavailable','附件返回网页或中转页，未冒充文件')
                if link['role']=='original_pdf':
                    if not attachment['data'].startswith(b'%PDF-'):
                        raise FetchError('attachment_unavailable','OA正文入口未返回PDF原件')
                    filename,content_type='original.pdf','application/pdf'
                if not PurePosixPath(filename).suffix:
                    filename += mimetypes.guess_extension(content_type) or ''
                asset=self.assets.put(attachment['data'],filename=filename,media_type=content_type,url=link['url'])
                asset['role']=link['role']
                assets.append(asset)
            except FetchError as exc:
                assets.append(dict(link,status='failed',error={'code':exc.code,'message':exc.message}))
                errors.append({'code':exc.code,'message':exc.message,'url':link['url']})
        title=_clean_title(title) or title
        title=_clean_title(title) or title
        payload={'title':title,'source_id':source['source_id'],'source_name':source['name'],
                 'school_id':source.get('school_id','csu'),'school':source.get('school','中南大学'),
                 'source_url':item['url'],'published_at':published_at,'html':html,'assets':assets,
                 'body_asset_id':body_asset_id,'body_status':'partial' if errors else 'full',
                 'access_reason':None, 'channel_description':source.get('channel_description','')}
        # Ignore whole-page counters and navigation; retain meaningful body and attachment changes.
        semantic={'title':payload['title'],'html':html,'published_at':published_at,
                  'assets':[{k:a.get(k) for k in ('sha256','url','status','error')}
                            for a in assets if a.get('role')!='original_html']}
        if oa_pdf_id:
            semantic['errors']=[error['code'] for error in errors]
        version=hashlib.sha256(json.dumps(semantic,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return make_artifact('raw',notice_id(item['url']),version,payload,
                             status='partial' if errors else 'complete',errors=errors,now=now)
