"""Produce a versioned, replayable document without discarding successful evidence."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from campus_backend.core.artifacts import make_artifact, validate_artifact
from . import extractors
from .ocr import default_ocr
from .ports import ExtractionError

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_ASSETS = 100
MAX_TOTAL_BYTES = 100 * 1024 * 1024
DOCUMENT_TIMEOUT = 300
OCR_TIMEOUT = 60
_OCR_SLOTS = threading.BoundedSemaphore(2)
_HTML_BLOCK_TAGS = {
    'address', 'article', 'aside', 'blockquote', 'caption', 'dd', 'details',
    'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr', 'li', 'main',
    'nav', 'ol', 'p', 'pre', 'section', 'summary', 'table', 'tbody',
    'td', 'tfoot', 'th', 'thead', 'title', 'tr', 'ul',
}


def _safe_url(base, value):
    url = urljoin(base, value or '')
    return url if urlparse(url).scheme.lower() in ('http', 'https') else None


def clean_html(html: str, source_url: str) -> tuple[str, dict]:
    if len(html.encode('utf-8')) > MAX_HTML_BYTES:
        raise ExtractionError('size_limit', 'HTML正文超过大小上限')
    soup = BeautifulSoup(html, 'html.parser', preserve_whitespace_tags=_HTML_BLOCK_TAGS | {
        'html', 'body', 'span', 'a', 'b', 'em', 'i', 'strong', 'u', 'small',
        'sub', 'sup', 'label', 'font', 'code', 'textarea',
    })
    for node in soup(['script', 'style', 'noscript', 'iframe', 'object', 'embed', 'template', 'svg', 'form']):
        node.decompose()
    images, links = [], []
    for node in soup.find_all('img'):
        url = _safe_url(source_url, node.get('src'))
        if url:
            images.append({'url': url, 'alt': node.get('alt', '')})
    for node in soup.find_all('a'):
        url = _safe_url(source_url, node.get('href'))
        if url:
            links.append({'url': url, 'text': node.get_text().strip()})
    # A text node boundary can be only an inline style change within a date or word.
    # Add separators for structural boundaries instead, without inventing spaces or digits.
    for node in soup.find_all('br'):
        node.replace_with('\n')
    for node in soup.find_all(_HTML_BLOCK_TAGS):
        node.insert_before('\n')
        node.insert_after('\n')
    lines = [line.strip() for line in soup.get_text().splitlines() if line.strip()]
    return '\n'.join(lines), {'images': images, 'links': links}


def _checked_asset(item, root):
    value = item.get('path')
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ExtractionError('unsafe_path', '原件路径必须相对原件目录')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ExtractionError('unsafe_path', '原件路径越出允许目录')
    if not path.is_file():
        raise ExtractionError('asset_unavailable', '原件未下载或已丢失')
    size = path.stat().st_size
    if size > extractors.MAX_ASSET_BYTES:
        raise ExtractionError('size_limit', '原件超过大小上限')
    if item.get('sha256') and sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise ExtractionError('checksum_mismatch', '原件校验值与清单不一致')
    return path, size


def _recognize(provider, path, timeout):
    """Share one deadline across the queue and recognition, even for optional adapters."""
    deadline = time.monotonic() + timeout
    if timeout <= 0 or not _OCR_SLOTS.acquire(timeout=timeout):
        raise ExtractionError('ocr_timeout', 'OCR处理时限已到或识别资源繁忙')
    result = queue.Queue(maxsize=1)

    def run():
        try:
            with _ocr_input(path) as prepared:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExtractionError('ocr_timeout', 'OCR超过处理时限')
                text = provider.recognize(prepared, timeout=remaining)
            result.put((True, text))
        except Exception as exc:
            result.put((False, exc))
        finally:
            _OCR_SLOTS.release()

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        _OCR_SLOTS.release()
        raise
    try:
        success, value = result.get(timeout=max(0.0, deadline - time.monotonic()))
    except queue.Empty as exc:
        raise ExtractionError('ocr_timeout', 'OCR超过处理时限') from exc
    if not success:
        if isinstance(value, ExtractionError):
            raise value
        raise ExtractionError('ocr_failed', 'OCR适配器识别失败') from value
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError('ocr_empty', 'OCR未识别出文字')
    if len(value) > extractors.MAX_TEXT_CHARS:
        raise ExtractionError('text_limit', 'OCR文本量超过上限')
    return value.strip()


@contextmanager
def _ocr_input(path):
    """Composite transparent text on paper white; never mutate the source asset."""
    from PIL import Image
    with Image.open(path) as source:
        if source.width * source.height > extractors.MAX_IMAGE_PIXELS:
            raise ExtractionError('image_limit', '图片像素超过处理上限')
        if 'A' not in source.getbands() and 'transparency' not in source.info:
            yield path
            return
        rgba = source.convert('RGBA')
        if rgba.getchannel('A').getextrema() == (255, 255):
            yield path
            return
        with tempfile.TemporaryDirectory(prefix='campus-ocr-input-') as directory:
            prepared = Path(directory) / 'white.png'
            background = Image.new('RGBA', source.size, 'white')
            background.alpha_composite(rgba)
            background.convert('RGB').save(prepared)
            yield prepared


def _scan_page(pdf, page, directory, timeout):
    tool = shutil.which('pdftoppm')
    output = directory / f'page-{page}'
    if not tool:
        # 没装 Poppler 时用 PyMuPDF 渲染，省掉一个系统依赖。
        try:
            import pymupdf
        except ImportError as exc:
            raise ExtractionError('ocr_unavailable', '扫描PDF需要pdftoppm或PyMuPDF转换工具') from exc
        try:
            with pymupdf.open(str(pdf)) as document:
                pixmap = document.load_page(page - 1).get_pixmap(dpi=200)
                image = output.with_suffix('.png')
                pixmap.save(str(image))
        except Exception as exc:
            raise ExtractionError('ocr_failed', 'PDF页面无法转换为图片') from exc
        if not image.is_file():
            raise ExtractionError('ocr_failed', 'PDF页面无法转换为图片')
        return image
    env = None
    if 'FONTCONFIG_FILE' not in os.environ:
        # Relocated Poppler installs may have a config outside fontconfig's default path.
        config = Path(tool).resolve().parent.parent / 'etc' / 'fonts' / 'fonts.conf'
        if config.is_file():
            env = {**os.environ, 'FONTCONFIG_FILE': str(config)}
    try:
        proc = subprocess.run([tool, '-f', str(page), '-l', str(page), '-scale-to', '2400', '-singlefile', '-png', str(pdf), str(output)],
                              capture_output=True, timeout=timeout, check=False, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError('ocr_timeout', 'PDF页面转换超时') from exc
    image = output.with_suffix('.png')
    if proc.returncode or not image.is_file():
        raise ExtractionError('ocr_failed', 'PDF页面无法转换为图片')
    return image


def extract_document(raw: dict, assets_root: Path, *, ocr=None, now=None) -> dict:
    validate_artifact(raw, expected_stage='raw')
    root = Path(assets_root).resolve()
    payload = deepcopy(raw['payload'])
    html = payload.pop('html', '') or ''
    errors = deepcopy(raw.get('errors', []))
    segments = []
    started = time.monotonic()
    provider = ocr if ocr is not None else default_ocr(root / '.ocr-cache')
    evidence = {'images': [], 'links': []}

    def error(code, message, asset_id=None, page=None):
        value = {'code': code, 'message': message}
        if asset_id is not None:
            value['asset_id'] = asset_id
        if page is not None:
            value['page'] = page
        errors.append(value)

    used_chars = 0

    def append_segment(segment):
        nonlocal used_chars
        gap = 2 if segments else 0
        available = max(0, extractors.MAX_TEXT_CHARS - used_chars - gap)
        text = segment['text']
        if len(text) > available:
            if not any(e['code'] == 'text_limit' for e in errors):
                error('text_limit', '通知文本总量超过上限，正文已截断', segment.get('asset_id'))
            text = text[:available]
        if text:
            segments.append({**segment, 'text': text})
            used_chars += gap + len(text)

    def remaining():
        return max(0.0, min(OCR_TIMEOUT, DOCUMENT_TIMEOUT - (time.monotonic() - started)))

    try:
        text, evidence = clean_html(html, payload.get('source_url', ''))
        if text:
            append_segment({'text': text, 'asset_id': payload.get('body_asset_id'), 'page': None, 'location': 'html:body', 'method': 'html_text'})
    except ExtractionError as exc:
        error(exc.code, str(exc))
    assets = payload.get('assets', [])
    total_bytes = 0
    for index, item in enumerate(assets):
        asset_id = item.get('asset_id', str(index))
        if used_chars >= extractors.MAX_TEXT_CHARS:
            if not any(e['code'] == 'text_limit' for e in errors):
                error('text_limit', '文本上限已到，剩余原件保留供独立读取', asset_id)
            break
        if index >= MAX_ASSETS:
            error('asset_limit', '原件数量超过单条通知上限', asset_id)
            break
        if time.monotonic() - started >= DOCUMENT_TIMEOUT:
            error('document_timeout', '单条通知处理超时，剩余原件可独立重试', asset_id)
            break
        try:
            if item.get('status') not in (None, 'downloaded', 'complete', 'available', 'success'):
                raise ExtractionError('asset_unavailable', '附件未成功下载')
            path, size = _checked_asset(item, root)
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ExtractionError('size_limit', '通知原件总大小超过上限')
            if asset_id == payload.get('body_asset_id'):
                continue
            # Content-addressed paths often have no suffix; filename supplies the format hint.
            hint = Path(item.get('filename') or str(path))
            kind = extractors.kind_for(hint, item.get('media_type', ''))
            if kind == 'html':
                text, _ = clean_html(path.read_text(encoding='utf-8'), item.get('url', payload.get('source_url', '')))
                result = {'segments': [{'text': text, 'page': None, 'location': 'html:body', 'method': 'html_text'}], 'scan_pages': [], 'image': False}
            else:
                result = extractors.parse_isolated(path, kind, timeout=DOCUMENT_TIMEOUT - (time.monotonic() - started))
            for segment in result['segments']:
                if segment['text'].strip():
                    append_segment({**segment, 'asset_id': asset_id})
            for parse_error in result.get('errors', []):
                error(parse_error['code'], parse_error['message'], asset_id, parse_error.get('page'))
            if result.get('embedded_images'):
                with tempfile.TemporaryDirectory(prefix='.embedded-', dir=root) as directory:
                    for embedded_index, embedded in enumerate(result['embedded_images']):
                        if remaining() <= 0:
                            error('document_timeout', '处理时限已到，剩余内嵌图片保留供重试', asset_id)
                            break
                        if embedded_index >= MAX_ASSETS:
                            error('asset_limit', '内嵌图片数量超过上限', asset_id)
                            break
                        try:
                            image_path = Path(directory) / ('image' + Path(embedded['name']).suffix)
                            image_path.write_bytes(base64.b64decode(embedded['data']))
                            extractors.parse_isolated(image_path, 'image', timeout=remaining())
                            text = _recognize(provider, image_path, remaining())
                            append_segment({'text': text, 'asset_id': asset_id, 'page': None, 'location': 'embedded:' + embedded['name'], 'method': 'ocr'})
                        except ExtractionError as exc:
                            error(exc.code, str(exc), asset_id)
            if result.get('image'):
                text = _recognize(provider, path, remaining())
                append_segment({'text': text, 'asset_id': asset_id, 'page': 1, 'location': 'image', 'method': 'ocr'})
            if result['scan_pages']:
                with tempfile.TemporaryDirectory(prefix='.ocr-', dir=root) as directory:
                    for page in result['scan_pages']:
                        if remaining() <= 0:
                            error('document_timeout', '处理时限已到，剩余PDF页保留供重试', asset_id, page)
                            break
                        try:
                            image = _scan_page(path, page, Path(directory), remaining())
                            text = _recognize(provider, image, remaining())
                            append_segment({'text': text, 'asset_id': asset_id, 'page': page, 'location': f'page:{page}', 'method': 'ocr'})
                        except ExtractionError as exc:
                            error(exc.code, str(exc), asset_id, page)
            if not result['segments'] and not result['scan_pages'] and not result.get('image') and not result.get('embedded_images') and not result.get('errors'):
                raise ExtractionError('empty_document', '原件没有可提取文字')
        except ExtractionError as exc:
            error(exc.code, str(exc), asset_id)
        except Exception:
            error('extraction_failed', '原件处理失败，已保留其他成功正文', asset_id)
    known_urls = {item.get('url') for item in assets}
    references = [item['url'] for item in evidence['images']]
    references += [item['url'] for item in evidence['links'] if Path(urlparse(item['url']).path).suffix.lower() in ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar')]
    for url in dict.fromkeys(references):
        if url not in known_urls:
            error('asset_not_collected', '正文引用的图片或附件尚未取得：' + url)
    # Return pages in reading order even when native text and OCR are mixed.
    order = {item.get('asset_id', str(i)): i for i, item in enumerate(assets)}
    segments.sort(key=lambda s: (-1 if s['location'] == 'html:body' else order.get(s['asset_id'], len(assets)), s.get('page') or 0))
    content = '\n\n'.join(segment['text'] for segment in segments)
    input_body_status = payload.get('body_status')
    incomplete = bool(errors) or input_body_status in ('partial', 'title_only', 'restricted', 'login_required', 'unavailable')
    if not content and not errors and input_body_status not in ('title_only', 'restricted', 'login_required', 'unavailable'):
        error('empty_body', '正文和附件均未取得可读文字')
    payload.update(content=content, segments=segments, html_evidence=evidence,
                   body_status=('partial' if incomplete else 'complete') if content else 'title_only',
                   extraction={'name': 'campus-documents', 'version': '1.2', 'original_body_status': input_body_status})
    status = ('partial' if content else 'failed') if errors else 'complete'
    return make_artifact('document', raw['notice_id'], raw['content_version'], payload,
                         status=status, errors=errors,
                         input_refs=[{'stage': 'raw', 'notice_id': raw['notice_id'], 'content_version': raw['content_version'], 'run_id': raw['run_id']}],
                         producer={'name': 'campus-documents', 'version': '1.2'}, now=now)
