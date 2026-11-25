"""Audited selectors plus conservative university CMS extraction; empty is not success."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from bs4 import BeautifulSoup
from .http import canonical_url

DATE = re.compile(r'(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?')
DEFAULT_ARTICLE = r'/info/\d+/\d+\.htm|/content(?:\.jsp|/)|/[^/?]+/\d{4}/\d{2}/\d{2}/|/news/\d+'
ASSET_SUFFIX = re.compile(r'\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g|webp|bmp|tiff?|gif|txt|csv)(?:[?#]|$)',re.I)
_OA_PDF_PATH = '/con/xnbg/loadContentPdf/'
_OA_VIEWER_PATH = '/con/js/pdf/web/viewer1.html'
_OA_ID = re.compile(r'[0-9A-Fa-f]{32}')


class ParseError(Exception):
    def __init__(self, message, code='parse_error'):
        super().__init__(message)
        self.code, self.message = code, message


def decode_html(response):
    data = response['data']
    match = re.search(br'charset\s*=\s*["\']?([\w-]+)',data[:4096],re.I)
    encodings = [match[1].decode('ascii') if match else None, response.get('encoding'), 'utf-8', 'gb18030']
    for encoding in encodings:
        if encoding:
            try:
                return data.decode(encoding)
            except (UnicodeError,LookupError):
                continue
    return data.decode('utf-8',errors='replace')


def _date(text):
    from datetime import date
    match = DATE.search(text)
    if match:
        try:
            return date(*(int(v) for v in match.groups())).isoformat()
        except ValueError:
            pass
    return None


def _guard(soup):
    text = soup.get_text(' ',strip=True)
    page_title = soup.title.get_text(strip=True) if soup.title else ''
    if soup.select_one('input[type=password]') or '统一身份认证' in page_title or any(t in text[:700] for t in ('请输入验证码','系统访问提示','访问过于频繁')):
        raise ParseError('页面要求登录/验证或返回访问提示，未取得通知正文','access_restricted')


def parse_list(html, source, page_url):
    soup = BeautifulSoup(html,'html.parser')
    _guard(soup)
    if source.get('direct_article'):
        title = soup.select_one('h1') or soup.title
        return {'items':[{'title':title.get_text(' ',strip=True) if title else source['name'],'url':page_url,'published_at':None}], 'next_urls':[]}
    pattern = re.compile(source.get('article_url_pattern') or DEFAULT_ARTICLE,re.I)
    items, seen = [], set()
    filtered=0
    allowed = set(source.get('allowed_hosts',[])) | set(source.get('title_only_hosts',[]))
    for anchor in soup.select(source.get('article_selector') or 'a[href]'):
        if anchor.name != 'a':
            anchor = anchor.select_one('a[href]')
        if not anchor or not anchor.get('href'):
            continue
        url = canonical_url(urljoin(page_url,anchor['href']))
        if not pattern.search(url) or url in seen or urlsplit(url).scheme not in ('http','https'):
            continue
        if allowed and urlsplit(url).hostname not in allowed:
            continue
        node = anchor.select_one(source['title_selector']) if source.get('title_selector') else None
        title = (node.get_text(' ',strip=True) if node else anchor.get('title') or anchor.get_text(' ',strip=True)).strip()
        if len(title)<3 or title in ('点击查看','查看详情','阅读全文','更多内容'):
            continue
        if source.get('title_include_pattern') and not re.search(source['title_include_pattern'],title):
            filtered+=1
            continue
        parent = anchor
        row_text = ''
        for _ in range(3):
            if not parent:
                break
            row_text = parent.get_text(' ',strip=True)
            if _date(row_text) or len(row_text)>1000:
                break
            parent = parent.parent
        seen.add(url)
        items.append({'title':title,'url':url,'published_at':_date(row_text)})
    next_urls=[]
    links = soup.select(source['pagination_selector']) if source.get('pagination_selector') else soup.select('a[href]')
    for anchor in links:
        text = re.sub(r'\s','',anchor.get_text())
        if text in ('下页','下一页','下一页>','下页>','Next','next','>','›','»'):
            href=anchor.get('href','')
            if href and not href.startswith(('#','javascript:')):
                url=canonical_url(urljoin(page_url,href))
                if url!=canonical_url(page_url) and urlsplit(url).hostname==urlsplit(page_url).hostname:
                    next_urls.append(url)
    if source.get('pagination_template'):
        total=re.search(r'''totalData\s*:\s*['"]?(\d+)''',html)
        size=re.search(r'''showData\s*:\s*['"]?(\d+)''',html)
        current=re.search(r'''current\s*:\s*['"]?(\d+)''',html)
        if total and size and current and int(size[1])>0:
            page=int(current[1])
            if page*int(size[1])<int(total[1]):
                candidate=source['pagination_template'].replace('{page}',str(page+1))
                if urlsplit(candidate).hostname==urlsplit(page_url).hostname:
                    next_urls.append(candidate)
    if not items:
        if filtered:
            return {'items':[],'next_urls':list(dict.fromkeys(next_urls)),'empty_confirmed':True,'filtered_links':filtered}
        if re.search(r'暂无(?:相关)?(?:信息|内容|记录)|没有(?:相关)?(?:记录|信息)',soup.get_text()):
            return {'items':[],'next_urls':list(dict.fromkeys(next_urls)), 'empty_confirmed':True}
        raise ParseError('栏目未解析出通知，可能改版或读取不完整')
    return {'items':items,'next_urls':list(dict.fromkeys(next_urls))}


def oa_pdf_page(url):
    """Return the identity of a known public OA PDFPage, if applicable."""
    page = urlsplit(url)
    if page.hostname != 'oa.csu.edu.cn' or page.path != '/con/PDFPage':
        return None
    ids = parse_qs(page.query, keep_blank_values=True).get('JLNM', [])
    if len(ids) != 1 or not _OA_ID.fullmatch(ids[0]):
        raise ParseError('OA公告缺少可核验的文档编号')
    return ids[0]


def _oa_pdf_detail(soup, url, document_id):
    """Read public PDFPage locations from the live DOM, without running scripts."""
    page = urlsplit(url)
    expected_path = _OA_PDF_PATH + document_id
    title_node = soup.select_one('.mtable-t')
    if title_node is None:
        raise ParseError('OA公告未找到已知标题区域')

    def same_page_link(link, expected):
        try:
            parts = urlsplit(urljoin(url, link))
        except ValueError:
            return False
        return (parts.scheme, parts.netloc, parts.path) == (page.scheme, page.netloc, expected)

    candidates = []
    for anchor in title_node.select('a#download[href]'):
        candidates.append(anchor['href'])
    for iframe in soup.select('#pdf iframe[src]'):
        viewer = iframe['src']
        if not same_page_link(viewer, _OA_VIEWER_PATH):
            raise ParseError('OA预览链接与当前公告不匹配')
        sources = parse_qs(urlsplit(viewer).query, keep_blank_values=True).get('file', [])
        if len(sources) != 1:
            raise ParseError('OA预览链接缺少唯一正文')
        candidates.extend(sources)
    if not candidates or any(
        not same_page_link(link, expected_path) or urlsplit(link).query or urlsplit(link).fragment
        for link in candidates
    ):
        raise ParseError('OA正文PDF链接与当前公告不匹配')
    date_node = title_node.select_one('.tdate')
    published_at = _date(date_node.get_text(' ', strip=True)) if date_node else None
    if date_node:
        date_node.decompose()
    title = title_node.get_text(' ', strip=True).split('>', 1)[-1].strip()
    if not title:
        raise ParseError('OA公告标题为空')
    return {'html': '', 'published_at': published_at, 'title': title, 'oa_pdf_id': document_id,
            'assets': [{'url': urljoin(url, expected_path), 'filename': 'original.pdf', 'role': 'original_pdf'}]}


def _clean_title(raw, body_text=''):
    """站点常把标题重复两遍、或在 h1 里混进正文；这里只留真正的标题。"""
    text = re.sub(r'\s+', ' ', raw or '').strip()
    if not text:
        return None
    # 标题在同一节点里重复出现时（T T 正文…），取第一段。
    for size in range(8, len(text) // 2 + 1):
        head = text[:size].strip()
        if head and text[size:].lstrip().startswith(head):
            return head
    if len(text) > 80:
        cut = len(text)
        for mark in ('。', '！', '？'):
            pos = text.find(mark)
            if 0 < pos < cut:
                cut = pos
        text = text[:min(cut, 100)].strip()
    # 去掉网页标题后缀里的站名（"…-中南大学人文学院"）。
    for separator in (' - ', '-', '_', '|', '｜'):
        if separator in text:
            head, tail = text.rsplit(separator, 1)
            if head.strip() and len(tail) <= 20 and ('大学' in tail or '学院' in tail):
                text = head.strip()
                break
    return text or None


def parse_detail(html, source, url):
    soup = BeautifulSoup(html,'html.parser')
    _guard(soup)
    if document_id := oa_pdf_page(url):
        return _oa_pdf_detail(soup, url, document_id)
    selectors = [source['body_selector']] if source.get('body_selector') else [
        '#vsb_content','.v_news_content','[id^=vsb_content_]','#newscontent','.article-content',
        '.news-content','.news_content','.contenttext','.detail-content','article','main']
    body = None
    for selector in selectors:
        candidates=soup.select(selector)
        if candidates:
            body=max(candidates,key=lambda node:len(node.get_text()))
            break
    if body is None:
        raise ParseError('未找到已知正文区域，等待适配官网结构')
    page_text = soup.get_text(' ',strip=True)
    match = re.search(r'(?:发布时间|发布日期|发布于|日期|时间)\s*[:：]?\s*('+DATE.pattern+r')',page_text)
    published_at = _date(match.group()) if match else None
    if source.get('published_selector'):
        publication_node=soup.select_one(source['published_selector'])
        if publication_node:
            published_at=_date(publication_node.get_text(' ',strip=True)) or published_at
    embedded=[]
    for script in body.select('script'):
        text=script.string or script.get_text()
        for link in re.findall(r'''showVsbpdfIframe\(\s*['"]([^'"]+)['"]''',text):
            embedded.append({'url':canonical_url(urljoin(url,link)), 'filename':'embedded.pdf','role':'attachment'})
        match=re.search(r'vsb_pdf_image_data\s*=\s*(\[[^;]+?\])',text)
        if match:
            for link in re.findall(r'''['"]([^'"]+\.(?:jpg|png|jpeg)(?:\?[^'"]*)?)['"]''',match.group(1),re.I):
                embedded.append({'url':canonical_url(urljoin(url,link)), 'filename':urlsplit(link).path.rsplit('/',1)[-1], 'role':'pdf_fallback_image'})
    for node in body.select('iframe[src],embed[src],object[data]'):
        link=node.get('src') or node.get('data')
        if link and ASSET_SUFFIX.search(link):
            embedded.append({'url':canonical_url(urljoin(url,link)),'filename':urlsplit(link).path.rsplit('/',1)[-1],'role':'attachment'})
    for node in body.select('script,style,iframe,object,embed,form,input,button,nav'):
        node.decompose()
    assets=embedded
    for node in body.select('img[src], a[href]'):
        link=node.get('src') if node.name=='img' else node.get('href')
        if not link or link.startswith(('data:','javascript:','#')):
            continue
        full=canonical_url(urljoin(url,link))
        if node.name=='img' or ASSET_SUFFIX.search(full) or 'download.jsp' in full or 'wbfileid=' in full:
            assets.append({'url':full,'filename':node.get_text(' ',strip=True) or urlsplit(full).path.rsplit('/',1)[-1],
                           'role':'image' if node.name=='img' else 'attachment'})
    # VSB attachment lists sometimes sit immediately outside the article body.
    attachment_selector=source.get('asset_selector') or '.attach a[href], .附件 a[href], ul li a[href*="download.jsp"]'
    for node in soup.select(attachment_selector):
        assets.append({'url':canonical_url(urljoin(url,node['href'])),'filename':node.get_text(' ',strip=True),'role':'attachment'})
    assets=list({item['url']:item for item in assets}.values())
    if not body.get_text(strip=True) and not assets:
        raise ParseError('正文区域为空，未覆盖已有内容')
    title_node=soup.select_one('h1') or soup.select_one('.article-title') or soup.title
    return {'html':str(body),'published_at':published_at,'assets':assets,
            'title':_clean_title(title_node.get_text(' ',strip=True) if title_node else None,
                                 body.get_text(' ',strip=True))}
