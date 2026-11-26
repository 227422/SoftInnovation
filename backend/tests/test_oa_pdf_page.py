"""Replay the observed CSU OA PDFPage shell and its public file endpoints."""

from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from campus_backend.collection.html import ParseError
from campus_backend.collection.http import FetchError
from campus_backend.collection.service import CollectionService
from campus_backend.core.artifacts import AssetStore


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
ID = 'ED314A8F9609408091B4DDB22ECD5E81'
OTHER_ID = 'A2009C1CE526489DB274D63D9F424CE7'
ORIGIN = 'https://oa.csu.edu.cn'
PAGE = f'{ORIGIN}/con/PDFPage?YWMC=ZNDX_ZHBG_GGTZ&JLNM={ID}'
BODY_PATH = f'/con/xnbg/loadContentPdf/{ID}'
LIST_PATH = '/con/xnbg/getFjList'
ATTACHMENT_PATH = '/con/xnbg/downLoadFj'
PDF = b'%PDF-1.7\nmock PDF response'
ATTACHMENT = b'%PDF-1.5\nmock attachment response'
SOURCE = {
    'source_id': 'undergrad', 'name': '本科生院', 'school_id': 'csu',
    'url': 'https://bksy.csu.edu.cn/tztg/jyjgyxjglbgs.htm',
    'allowed_hosts': ['bksy.csu.edu.cn', 'oa.csu.edu.cn', 'example.edu'],
    'body_selector': '#vsb_content',
}
ITEM = {'url': PAGE, 'title': '关于 2027届本科毕业生图…', 'published_at': '2026-10-27'}

# Verbatim DOM from the archived public notice, with surrounding chrome and script shortened.
SHELL = f"""
<!doctype html><html><title>中南大学门户网站</title><body>
<header>内容导航</header>
<div class="item mtable col-lg-12">
    <div class="mtable-t">
        <div class="tdate">
            发布日期：2026-10-28
            <span>
                <a id="download" href="{BODY_PATH}">下载</a>&nbsp;&nbsp;
                <a href="#" onclick="print_1()">打印</a>
            </span>
        </div>
        <span>校内通知</span>
        &nbsp;>&nbsp;关于 2027届本科毕业生图像采集的通知
    </div>
    <div class="mtable-c"><div id="pdf" class="mtable-pdf">
        <!-- src="/con/js/pdf/web/viewer1.html?file=/con/xnbg/loadContentPdf/{OTHER_ID}/" -->
        <iframe class="noprint" src="/con/js/pdf/web/viewer1.html?file={BODY_PATH}" name="if1" id="if1"></iframe>
    </div></div>
    <div class="mtable-c"><div class="mtable-info">
        <div class="col-lg-2">附件信息</div>
        <div class="col-lg-9" id="files"></div>
    </div></div>
</div>
<footer>中南大学版权所有@<span id="year">2022</span></footer>
</body></html>
<script>loadpdf('pdf', '{BODY_PATH}'); showAccessoryList('{ID}');</script>
"""


class ShellHTTP:
    def __init__(self, *, shell=SHELL, metadata=b'[]', body=PDF, attachment=ATTACHMENT, body_type='application/pdf'):
        self.shell, self.metadata, self.body, self.attachment = shell, metadata, body, attachment
        self.body_type = body_type
        self.downloads = []
        self.posts = []

    @staticmethod
    def response(url, data, media_type):
        if isinstance(data, FetchError):
            raise data
        return {'url': url, 'data': data, 'media_type': media_type, 'headers': {}}

    def get(self, url, allowed_hosts, *, max_bytes, referer):
        self.downloads.append((url, referer, allowed_hosts))
        path = urlsplit(url).path
        if path == '/con/PDFPage':
            return self.response(url, self.shell.encode(), 'text/html')
        if path == BODY_PATH:
            return self.response(url, self.body, self.body_type)
        if path == ATTACHMENT_PATH:
            return self.response(url, self.attachment, 'application/pdf')
        raise AssertionError(f'unexpected fetch {url}')

    def post_form(self, url, allowed_hosts, data, *, max_bytes, referer):
        self.posts.append((url, data, referer, allowed_hosts, max_bytes))
        return self.response(url, self.metadata, 'text/html')


def read_page(tmp_path, http):
    return CollectionService(http, AssetStore(tmp_path)).article(SOURCE, ITEM, now=NOW)


def test_observed_shell_yields_full_title_and_pdf_without_navigation(tmp_path):
    filename = '报名须知 A&B.pdf'
    metadata = json.dumps([{'NBBM': OTHER_ID, 'FJMC': filename}], ensure_ascii=False).encode()
    http = ShellHTTP(metadata=metadata)
    raw = read_page(tmp_path, http)
    payload = raw['payload']
    assert payload['title'] == '关于 2027届本科毕业生图像采集的通知'
    assert payload['published_at'] == '2026-10-28'
    assert payload['html'] == ''
    assert raw['status'] == 'complete'
    assert payload['body_status'] == 'full'
    shell, body, attachment = payload['assets']
    assert shell['role'] == 'original_html'
    assert payload['body_asset_id'] == shell['asset_id']
    assert body['role'] == 'original_pdf'
    assert attachment['role'] == 'attachment'
    assert AssetStore(tmp_path).read(body) == PDF
    assert AssetStore(tmp_path).read(attachment) == ATTACHMENT
    assert parse_qs(urlsplit(attachment['url']).query) == {'NBBM': [OTHER_ID], 'fullfilename': [filename]}
    assert http.posts == [(ORIGIN + LIST_PATH, {'JLNM': ID, 'WJFL': '11'}, PAGE, ['oa.csu.edu.cn'], 256 * 1024)]
    assert [urlsplit(url).path for url, _, _ in http.downloads] == ['/con/PDFPage', BODY_PATH, ATTACHMENT_PATH]


def test_empty_attachment_array_is_complete(tmp_path):
    raw = read_page(tmp_path, ShellHTTP())
    assert raw['errors'] == []
    assert raw['payload']['body_status'] == 'full'
    assert [a['role'] for a in raw['payload']['assets']] == ['original_html', 'original_pdf']


@pytest.mark.parametrize('metadata', [
    b'{}', b'not-json', b'<html>login</html>',
    b'[{"NBBM":"/another/url","FJMC":"x.pdf"}]',
    b'[{"NBBM":"0","FJMC":"../x.pdf"}]', b'[{"NBBM":"0","FJMC":4}]',
    FetchError('network_error', '暂时无法查询附件'),
])
def test_invalid_attachment_metadata_preserves_body_and_marks_incomplete(tmp_path, metadata):
    http = ShellHTTP(metadata=metadata)
    raw = read_page(tmp_path, http)
    assert raw['status'] == 'partial'
    assert raw['payload']['body_status'] == 'partial'
    assert raw['errors']
    assert [a['role'] for a in raw['payload']['assets']] == ['original_html', 'original_pdf']
    assert len(http.downloads) == 2


def test_attachment_download_failure_preserves_body(tmp_path):
    metadata = json.dumps([{'NBBM': OTHER_ID, 'FJMC': '材料.pdf'}], ensure_ascii=False).encode()
    raw = read_page(tmp_path, ShellHTTP(
        metadata=metadata, attachment=FetchError('http_error', '附件暂不可用')))
    assert raw['status'] == 'partial'
    assert raw['errors'][0]['code'] == 'http_error'
    assert raw['payload']['assets'][-1]['status'] == 'failed'
    assert raw['payload']['assets'][1]['status'] == 'complete'


def test_attachment_count_is_bounded_and_incomplete(tmp_path):
    metadata = json.dumps([{'NBBM': f'{n:032X}', 'FJMC': f'{n}.pdf'} for n in range(35)]).encode()
    http = ShellHTTP(metadata=metadata)
    raw = read_page(tmp_path, http)
    assert raw['status'] == 'partial'
    assert 'attachment_limit' in {error['code'] for error in raw['errors']}
    assert len(http.downloads) <= 31


@pytest.mark.parametrize(('shell',), [
    (SHELL.replace(BODY_PATH, f'https://example.edu{BODY_PATH}'),),
    (SHELL.replace(BODY_PATH, f'/con/xnbg/loadContentPdf/{OTHER_ID}'),),
    (SHELL.replace(f'href="{BODY_PATH}"', f'href="https://example.edu{BODY_PATH}"'),),
    (SHELL.replace(f'href="{BODY_PATH}"', 'href="#"').replace(f'file={BODY_PATH}', 'file=#'),),
    (SHELL.replace(f'file={BODY_PATH}', f'file={BODY_PATH}&amp;file='),),
])
def test_only_matching_same_origin_live_dom_can_authorize_pdf_fetch(tmp_path, shell):
    http = ShellHTTP(shell=shell)
    with pytest.raises(ParseError):
        read_page(tmp_path, http)
    assert len(http.downloads) == 1
    assert http.posts == []


def test_oa_shell_redirect_to_a_different_document_is_rejected(tmp_path):
    class RedirectedShell(ShellHTTP):
        def get(self, url, *args, **kwargs):
            response = super().get(url, *args, **kwargs)
            if url == PAGE:
                return response | {
                    'url': PAGE.replace(ID, OTHER_ID),
                    'data': self.shell.replace(ID, OTHER_ID).encode(),
                }
            return response

    http = RedirectedShell()
    with pytest.raises(ParseError):
        read_page(tmp_path, http)
    assert len(http.downloads) == 1
    assert http.posts == []


@pytest.mark.parametrize(('body_type', 'body'), [
    ('text/html', b'<html>login</html>'),
    ('application/pdf', b'<html>login</html>'),
    ('application/pdf', b'non-PDF'),
])
def test_only_pdf_bytes_can_be_saved_as_main_document(tmp_path, body_type, body):
    raw = read_page(tmp_path, ShellHTTP(body_type=body_type, body=body))
    assert raw['status'] == 'partial'
    assert raw['payload']['assets'][1]['role'] == 'original_pdf'
    assert raw['payload']['assets'][1]['status'] == 'failed'
    assert len(raw['errors']) == 1
