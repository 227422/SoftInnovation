"""Behavior tests: loss of evidence, unsafe files and silent extraction loss are regressions."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import zipfile

import pytest

def extract_document(*args, **kwargs):
    from campus_backend.documents.service import extract_document as extract
    return extract(*args, **kwargs)


def make_artifact(stage, notice_id, content_version, payload):
    return {'schema_version': '1.0', 'stage': stage, 'notice_id': notice_id,
            'content_version': content_version, 'run_id': 'fixture',
            'created_at': '2026-10-31T00:00:00+00:00',
            'producer': {'name': 'test', 'version': '1.0'},
            'status': 'complete', 'errors': [], 'input_refs': [], 'payload': payload}


def raw(html='', assets=None, **extra):
    return make_artifact('raw', 'notice-1', 'version-1', {
        'title': '学生通知', 'source_id': 'test', 'source_name': '学校官网',
        'school_id': 'csu', 'school': '中南大学', 'source_url': 'https://www.csu.edu.cn/n/1',
        'published_at': '2026-10-31', 'html': html, 'body_status': 'complete',
        'assets': assets or [], 'custom_evidence': {'preserve': True}, **extra,
    })


def asset(root, name, data, media_type='application/octet-stream'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'asset_id': name, 'path': name, 'sha256': sha256(data).hexdigest(),
            'filename': name, 'url': 'https://www.csu.edu.cn/' + name,
            'media_type': media_type, 'status': 'downloaded'}


def test_html_is_plain_text_preserving_metadata_and_evidence(tmp_path):
    source = raw('<style>.hidden{}</style><script>alert(1)</script><p>报名时间</p><p>明日截止<img src="notice.png" alt="通知图"></p><a href="form.docx">报名表</a>')
    before = deepcopy(source)
    doc = extract_document(source, tmp_path)
    assert source == before
    assert doc['stage'] == 'document'
    assert doc['notice_id'] == 'notice-1' and doc['content_version'] == 'version-1'
    assert doc['payload']['custom_evidence'] == {'preserve': True}
    assert '报名时间' in doc['payload']['content']
    assert 'alert' not in doc['payload']['content'] and '<' not in doc['payload']['content']
    assert 'html' not in doc['payload']
    assert doc['payload']['html_evidence']['images'][0]['url'] == 'https://www.csu.edu.cn/n/notice.png'
    assert doc['payload']['html_evidence']['links'][0]['url'] == 'https://www.csu.edu.cn/n/form.docx'
    assert doc['payload']['body_status'] == 'partial'  # referenced files were not acquired


def test_partial_attachment_never_discards_successful_body(tmp_path):
    broken = asset(tmp_path, 'broken.pdf', b'not a pdf', 'application/pdf')
    result = extract_document(raw('<p>报名截止：11月1日。</p>', [broken]), tmp_path)
    assert '报名截止' in result['payload']['content']
    assert result['payload']['body_status'] == 'partial'
    assert result['status'] == 'partial'
    assert result['errors'][0]['asset_id'] == 'broken.pdf'
    assert result['payload']['assets'] == [broken]


@pytest.mark.parametrize('name,data,code', [
    ('unknown.bin', b'xx', 'unsupported_type'),
    ('broken.docx', b'not zip', 'corrupt_document'),
])
def test_clear_failure_does_not_claim_empty_complete(tmp_path, name, data, code):
    result = extract_document(raw(assets=[asset(tmp_path, name, data)]), tmp_path)
    assert result['payload']['content'] == ''
    assert result['payload']['body_status'] == 'title_only'
    assert result['status'] == 'failed'
    assert result['errors'][0]['code'] == code


def test_paths_and_hash_are_verified_before_opening(tmp_path):
    outside = tmp_path.parent / 'secret.txt'
    outside.write_text('DO NOT READ')
    unsafe = {'asset_id': 'bad', 'path': '../secret.txt', 'status': 'downloaded'}
    mismatch = asset(tmp_path, 'notice.txt', b'valid')
    mismatch['sha256'] = '0' * 64
    linked = tmp_path / 'link.txt'
    linked.symlink_to(outside)
    result = extract_document(raw(assets=[unsafe, mismatch, {'asset_id':'link', 'path':'link.txt', 'status':'downloaded'}]), tmp_path)
    assert 'DO NOT READ' not in result['payload']['content']
    assert [e['code'] for e in result['errors']] == ['unsafe_path', 'checksum_mismatch', 'unsafe_path']


def test_docx_xlsx_text_and_locations(tmp_path):
    from docx import Document
    from openpyxl import Workbook
    doc = Document()
    doc.add_paragraph('创新创业竞赛')
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '报名截止'
    table.cell(0, 1).text = '2026年11月5日'
    doc.save(tmp_path / 'body.docx')
    book = Workbook()
    book.active.title = '报名名单'
    book.active.append(['姓名', '学院'])
    book.active.append(['张三', '计算机学院'])
    book.save(tmp_path / 'list.xlsx')
    files = [asset(tmp_path, n, (tmp_path / n).read_bytes()) for n in ('body.docx', 'list.xlsx')]
    result = extract_document(raw(assets=files), tmp_path)
    assert result['status'] == 'complete'
    assert all(t in result['payload']['content'] for t in ['创新创业竞赛', '2026年11月5日', '张三', '计算机学院'])
    assert any('报名名单' in s['location'] for s in result['payload']['segments'])


def test_zip_bomb_and_size_limit(tmp_path, monkeypatch):
    from campus_backend.documents import extractors
    with zipfile.ZipFile(tmp_path / 'bomb.docx', 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('word/document.xml', 'a' * 200_000)
    files = [asset(tmp_path, 'bomb.docx', (tmp_path / 'bomb.docx').read_bytes())]
    result = extract_document(raw(assets=files), tmp_path)
    assert result['errors'][0]['code'] == 'archive_limit'
    monkeypatch.setattr(extractors, 'MAX_ASSET_BYTES', 8)
    large = asset(tmp_path, 'large.pdf', b'x' * 9)
    result = extract_document(raw(assets=[large]), tmp_path)
    assert result['errors'][0]['code'] == 'size_limit'


def test_image_ocr_port_and_missing_ocr_are_explicit(tmp_path):
    from PIL import Image
    from campus_backend.documents.ocr import UnavailableOCR
    Image.new('RGB', (100, 50), 'white').save(tmp_path / 'notice.png')
    item = asset(tmp_path, 'notice.png', (tmp_path / 'notice.png').read_bytes(), 'image/png')
    class KnownOCR:
        def recognize(self, path, *, timeout):
            return '通知：明天交报名表。'
    result = extract_document(raw(assets=[item]), tmp_path, ocr=KnownOCR())
    assert '明天交报名表' in result['payload']['content']
    assert result['payload']['segments'][0]['method'] == 'ocr'
    missing = extract_document(raw(assets=[item]), tmp_path, ocr=UnavailableOCR())
    assert missing['errors'][0]['code'] == 'ocr_unavailable'


def test_cli_replays_json(tmp_path):
    source = tmp_path / 'raw.json'
    target = tmp_path / 'document.json'
    source.write_text(json.dumps(raw('<p>公开通知正文</p>'), ensure_ascii=False))
    result = subprocess.run([sys.executable, '-m', 'campus_backend.documents.cli', str(source), '--assets-root', str(tmp_path), '--output', str(target)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text())['payload']['content'] == '公开通知正文'


def text_pdf():
    from io import BytesIO
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 18 Tf 50 700 Td (Competition deadline 2026-11-05) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_native_text_and_scanned_page_preserve_page_numbers(tmp_path):
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    image = Image.new('RGB', (800, 500), 'white')
    scanned = BytesIO()
    image.save(scanned, format='PDF')
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(text_pdf())))
    writer.append(PdfReader(BytesIO(scanned.getvalue())))
    output = BytesIO()
    writer.write(output)
    item = asset(tmp_path, 'mixed.pdf', output.getvalue(), 'application/pdf')
    class OCR:
        def recognize(self, path, *, timeout):
            return '第二页：中文报名说明'
    result = extract_document(raw(assets=[item]), tmp_path, ocr=OCR())
    assert result['status'] == 'complete'
    assert result['payload']['segments'][0]['page'] == 1
    assert result['payload']['segments'][1]['page'] == 2
    assert 'Competition deadline' in result['payload']['content']
    assert '中文报名说明' in result['payload']['content']


def test_pdf_text_survives_missing_ocr_on_other_page(tmp_path):
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from campus_backend.documents.ocr import UnavailableOCR
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(text_pdf())))
    writer.add_blank_page(width=500, height=700)
    output = BytesIO()
    writer.write(output)
    result = extract_document(raw(assets=[asset(tmp_path, 'mixed.pdf', output.getvalue())]), tmp_path, ocr=UnavailableOCR())
    assert result['status'] == 'partial'
    assert 'Competition deadline' in result['payload']['content']
    assert result['errors'][0]['code'] == 'ocr_unavailable'
    assert result['errors'][0]['page'] == 2


@pytest.mark.parametrize('mode, expected', [
    ('bundled', 'etc/fonts/fonts.conf'), ('explicit', 'custom.conf'), ('absent', None),
])
def test_scan_renderer_uses_its_installed_fontconfig_when_unconfigured(tmp_path, monkeypatch, mode, expected):
    import os
    import shutil
    from campus_backend.documents.service import _scan_page

    install = tmp_path / 'poppler'
    renderer = install / 'bin' / 'pdftoppm'
    renderer.parent.mkdir(parents=True)
    renderer.write_text(
        f'#!{sys.executable}\n'
        'import json, os, pathlib, sys\n'
        'pathlib.Path(sys.argv[-1]).with_suffix(".png").write_text('
        'json.dumps([os.environ.get("FONTCONFIG_FILE"), os.environ["TEST_RENDERER_ENV"]]))\n'
    )
    renderer.chmod(0o755)
    shortcut = tmp_path / 'pdftoppm'
    shortcut.symlink_to(renderer)
    monkeypatch.setattr(shutil, 'which', lambda command: str(shortcut) if command == 'pdftoppm' else None)
    monkeypatch.delenv('FONTCONFIG_FILE', raising=False)
    monkeypatch.setenv('TEST_RENDERER_ENV', 'preserved')
    if mode != 'absent':
        config = install / 'etc/fonts/fonts.conf'
        config.parent.mkdir(parents=True)
        config.touch()
    if mode == 'explicit':
        monkeypatch.setenv('FONTCONFIG_FILE', str(install / 'custom.conf'))

    result = _scan_page(tmp_path / 'example.pdf', 1, tmp_path, 2)

    assert json.loads(result.read_text()) == [str(install / expected) if expected else None, 'preserved']
    assert os.environ.get('FONTCONFIG_FILE') == (str(install / 'custom.conf') if mode == 'explicit' else None)


def test_xls_text_extraction(tmp_path):
    import xlwt
    book = xlwt.Workbook()
    sheet = book.add_sheet('旧格式')
    sheet.write(0, 0, '竞赛报名')
    sheet.write(0, 1, '2026年11月5日')
    book.save(str(tmp_path / 'legacy.xls'))
    result = extract_document(raw(assets=[asset(tmp_path, 'legacy.xls', (tmp_path / 'legacy.xls').read_bytes())]), tmp_path)
    assert result['status'] == 'complete'
    assert '竞赛报名' in result['payload']['content']


def test_xlsx_named_xls_keeps_office_archive_limits(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / 'limited.xls'
    book = Workbook()
    book.active.append(['报名名单'])
    book.save(path)
    with zipfile.ZipFile(path, 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/media/compressed.bin', b'x' * 200_000)

    result = extract_document(raw('<p>已有正文</p>', [asset(tmp_path, path.name, path.read_bytes())]), tmp_path)

    assert result['payload']['content'] == '已有正文'
    assert [error['code'] for error in result['errors']] == ['archive_limit']


def test_body_asset_not_extracted_twice(tmp_path):
    html = '<p>唯一正文</p>'
    item = asset(tmp_path, 'body', html.encode(), 'text/html')
    item['filename'] = 'body.html'
    result = extract_document(raw(html, [item], body_asset_id='body'), tmp_path)
    assert result['payload']['content'] == '唯一正文'
    assert result['payload']['segments'][0]['asset_id'] == 'body'


def test_page_limit_and_parser_timeout_are_explicit(tmp_path, monkeypatch):
    from io import BytesIO
    from pypdf import PdfWriter
    from campus_backend.documents import extractors
    writer = PdfWriter()
    for _ in range(151):
        writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    result = extract_document(raw(assets=[asset(tmp_path, 'many.pdf', output.getvalue())]), tmp_path)
    assert result['errors'][0]['code'] == 'page_limit'
    monkeypatch.setattr(extractors, 'PARSE_TIMEOUT', 0.00001)
    result = extract_document(raw('<p>保留正文</p>', [asset(tmp_path, 'text.pdf', text_pdf())]), tmp_path)
    assert result['errors'][0]['code'] == 'parse_timeout'
    assert '保留正文' in result['payload']['content']


@pytest.mark.parametrize('queued_work_seconds, expected_status', [(0, 'complete'), (0.6, 'partial')])
def test_concurrent_image_documents_share_ocr_budget_between_queue_and_recognition(
    tmp_path, monkeypatch, queued_work_seconds, expected_status,
):
    from concurrent.futures import ThreadPoolExecutor
    from io import BytesIO
    from threading import Barrier, Event
    import time
    from PIL import Image
    from campus_backend.documents import service

    image = BytesIO()
    Image.new('RGB', (50, 50), 'white').save(image, format='PNG')
    documents = [
        raw('<p>已有正文</p>', [asset(tmp_path, name, image.getvalue())])
        for name in ('first.png', 'second.png', 'queued.png')
    ]
    slots_filled = Barrier(3)
    release_slots = Event()
    queued_recognition_started = Event()

    class ContendedOCR:
        def recognize(self, path, *, timeout):
            if path.name != 'queued.png':
                slots_filled.wait(timeout=3)
                release_slots.wait(timeout=3)
            else:
                queued_recognition_started.set()
                time.sleep(queued_work_seconds)
            return f'图片文字：{path.stem}'

    monkeypatch.setattr(service, 'OCR_TIMEOUT', 1)
    adapter = ContendedOCR()
    with ThreadPoolExecutor(max_workers=3) as pool:
        running = [pool.submit(extract_document, doc, tmp_path, ocr=adapter) for doc in documents[:2]]
        try:
            slots_filled.wait(timeout=3)
            queued = pool.submit(extract_document, documents[2], tmp_path, ocr=adapter)
            with pytest.raises(TimeoutError):
                queued.result(timeout=0.65)
        finally:
            release_slots.set()
        assert [future.result(timeout=3)['status'] for future in running] == ['complete', 'complete']
        result = queued.result(timeout=3)

    assert queued_recognition_started.is_set()
    assert result['status'] == expected_status
    if expected_status == 'complete':
        assert result['errors'] == []
        assert result['payload']['content'] == '已有正文\n\n图片文字：queued'
    else:
        assert [error['code'] for error in result['errors']] == ['ocr_timeout']
        assert result['payload']['content'] == '已有正文'


def test_ocr_timeout_is_bounded_even_for_optional_adapter(tmp_path, monkeypatch):
    import time
    from PIL import Image
    from campus_backend.documents import service
    Image.new('RGB', (50, 50), 'white').save(tmp_path / 'small.png')
    class SlowOCR:
        def recognize(self, path, *, timeout):
            time.sleep(0.2)
            return 'late'
    monkeypatch.setattr(service, 'OCR_TIMEOUT', 0.02)
    start = time.monotonic()
    result = extract_document(raw('<p>已有正文</p>', [asset(tmp_path, 'small.png', (tmp_path / 'small.png').read_bytes())]), tmp_path, ocr=SlowOCR())
    assert time.monotonic() - start < 0.18
    assert result['errors'][0]['code'] == 'ocr_timeout'
    assert result['payload']['content'] == '已有正文'


def test_title_only_restricted_is_successful_processing_not_full_body(tmp_path):
    result = extract_document(raw(body_status='title_only', restriction_reason='school_login'), tmp_path)
    assert result['status'] == 'complete'
    assert result['payload']['body_status'] == 'title_only'
    assert result['payload']['restriction_reason'] == 'school_login'


def test_pdf_one_damaged_page_does_not_discard_other_pages(tmp_path):
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, NumberObject
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(text_pdf())))
    page = writer.add_blank_page(width=100, height=100)
    page[NameObject('/Contents')] = NumberObject(42)
    output = BytesIO()
    writer.write(output)
    result = extract_document(raw(assets=[asset(tmp_path, 'damaged-page.pdf', output.getvalue())]), tmp_path)
    assert 'Competition deadline' in result['payload']['content']
    assert result['status'] == 'partial'
    assert result['errors'][0]['code'] == 'page_failed'
    assert result['errors'][0]['page'] == 2


def test_docx_embedded_image_gets_ocr_and_preserves_body(tmp_path):
    from docx import Document
    from PIL import Image
    Image.new('RGB', (100, 100), 'white').save(tmp_path / 'embedded.png')
    document = Document()
    document.add_paragraph('附件中的正文')
    document.add_picture(str(tmp_path / 'embedded.png'))
    document.save(tmp_path / 'with-image.docx')
    class OCR:
        def recognize(self, path, *, timeout):
            return '内嵌图：报名截止11月5日'
    result = extract_document(raw(assets=[asset(tmp_path, 'with-image.docx', (tmp_path / 'with-image.docx').read_bytes())]), tmp_path, ocr=OCR())
    assert '附件中的正文' in result['payload']['content']
    assert '报名截止11月5日' in result['payload']['content']
    assert any('embedded:' in s['location'] for s in result['payload']['segments'])


def test_body_original_integrity_checked_without_duplicate_extraction(tmp_path):
    item = asset(tmp_path, 'body.html', b'<p>body</p>', 'text/html')
    item['sha256'] = '0' * 64
    result = extract_document(raw('<p>已取得正文</p>', [item], body_asset_id='body.html'), tmp_path)
    assert result['payload']['content'] == '已取得正文'
    assert result['status'] == 'partial'
    assert result['errors'][0]['code'] == 'checksum_mismatch'


@pytest.mark.skipif(sys.platform != 'darwin', reason='legacy DOC conversion is macOS-only')
def test_legacy_doc_via_bounded_textutil(tmp_path):
    original = tmp_path / 'legacy.txt'
    original.write_text('旧版通知：报名截止为11月5日。')
    proc = subprocess.run(['textutil', '-convert', 'doc', '-output', str(tmp_path / 'legacy.doc'), str(original)], capture_output=True, timeout=15)
    assert proc.returncode == 0
    result = extract_document(raw(assets=[asset(tmp_path, 'legacy.doc', (tmp_path / 'legacy.doc').read_bytes())]), tmp_path)
    assert result['status'] == 'complete'
    assert '报名截止为11月5日' in result['payload']['content']


def test_image_pixel_limit_and_workbook_row_limit(tmp_path, monkeypatch):
    from PIL import Image
    from openpyxl import Workbook
    from campus_backend.documents import extractors
    monkeypatch.setattr(extractors, 'MAX_IMAGE_PIXELS', 100)
    Image.new('RGB', (11, 10), 'white').save(tmp_path / 'huge.png')
    result = extract_document(raw(assets=[asset(tmp_path, 'huge.png', (tmp_path / 'huge.png').read_bytes())]), tmp_path)
    assert result['errors'][0]['code'] == 'image_limit'
    monkeypatch.setattr(extractors, 'MAX_ROWS', 1)
    book = Workbook()
    book.active.append(['first'])
    book.active.append(['second'])
    book.save(tmp_path / 'rows.xlsx')
    result = extract_document(raw(assets=[asset(tmp_path, 'rows.xlsx', (tmp_path / 'rows.xlsx').read_bytes())]), tmp_path)
    assert result['errors'][0]['code'] == 'table_limit'


def test_jpeg_exceeding_pillow_bomb_limit_reports_image_limit(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from campus_backend.documents import extractors

    photo = BytesIO()
    Image.new('RGB', (15, 15), 'white').save(photo, format='JPEG')
    monkeypatch.setattr(extractors, 'MAX_IMAGE_PIXELS', 100)
    item = asset(tmp_path, 'oversize.jpg', photo.getvalue(), 'image/jpeg')

    result = extract_document(raw('<p>已有正文</p>', [item]), tmp_path)

    assert result['status'] == 'partial'
    assert result['payload']['content'] == '已有正文'
    assert [error['code'] for error in result['errors']] == ['image_limit']


def test_pdf_image_body_is_not_lost_when_same_page_has_text_header(tmp_path):
    from io import BytesIO
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    scan = BytesIO()
    Image.new('RGB', (800, 500), 'white').save(scan, format='PDF')
    writer = PdfWriter()
    page = writer.add_page(PdfReader(BytesIO(scan.getvalue())).pages[0])
    page.merge_page(PdfReader(BytesIO(text_pdf())).pages[0])
    output = BytesIO()
    writer.write(output)
    class OCR:
        def recognize(self, path, *, timeout):
            return '扫描正文：报名表需要学院盖章。'
    result = extract_document(raw(assets=[asset(tmp_path, 'header-plus-scan.pdf', output.getvalue())]), tmp_path, ocr=OCR())
    assert 'Competition deadline' in result['payload']['content']
    assert '报名表需要学院盖章' in result['payload']['content']


def test_xlsx_embedded_picture_is_not_silently_lost(tmp_path):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as SheetImage
    from PIL import Image
    Image.new('RGB', (100, 100), 'white').save(tmp_path / 'sheet-image.png')
    book = Workbook()
    book.active.append(['表格已有正文'])
    book.active.add_image(SheetImage(tmp_path / 'sheet-image.png'), 'A2')
    book.save(tmp_path / 'with-picture.xlsx')
    class OCR:
        def recognize(self, path, *, timeout):
            return '内嵌图片中的报名条件'
    result = extract_document(raw(assets=[asset(tmp_path, 'with-picture.xlsx', (tmp_path / 'with-picture.xlsx').read_bytes())]), tmp_path, ocr=OCR())
    assert '表格已有正文' in result['payload']['content']
    assert '内嵌图片中的报名条件' in result['payload']['content']


def test_text_limit_applies_to_segments_as_well_as_combined_body(tmp_path, monkeypatch):
    from campus_backend.documents import extractors
    monkeypatch.setattr(extractors, 'MAX_TEXT_CHARS', 20)
    files = [asset(tmp_path, 'first.txt', b'123456789012345'), asset(tmp_path, 'second.txt', b'abcdefghijklmno')]
    result = extract_document(raw(assets=files), tmp_path)
    assert result['status'] == 'partial'
    assert result['errors'][-1]['code'] == 'text_limit'
    assert len(result['payload']['content']) <= 20
    assert sum(len(s['text']) for s in result['payload']['segments']) <= 20
    assert result['payload']['content'] == '\n\n'.join(s['text'] for s in result['payload']['segments'])


def test_embedded_images_stop_when_document_budget_expires(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from docx import Document
    from campus_backend.documents import service
    document = Document()
    document.add_paragraph('已取得成功正文')
    for i, color in enumerate(('red', 'blue')):
        path = tmp_path / f'image-{i}.png'
        Image.new('RGB', (80, 80), color).save(path)
        document.add_picture(str(path))
    document.save(tmp_path / 'pictures.docx')
    clock = [0.0]
    monkeypatch.setattr(service, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(service, 'DOCUMENT_TIMEOUT', 1)
    class OCR:
        def recognize(self, path, *, timeout):
            clock[0] = 2.0
            return '第一幅图片已成功识别'
    result = extract_document(raw(assets=[asset(tmp_path, 'pictures.docx', (tmp_path / 'pictures.docx').read_bytes())]), tmp_path, ocr=OCR())
    assert '已取得成功正文' in result['payload']['content']
    assert '第一幅图片已成功识别' in result['payload']['content']
    assert any(e['code'] == 'document_timeout' for e in result['errors'])


@pytest.mark.parametrize('kind,filename,media,expected', [
    ('xlsx', '名单.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '张三'),
    pytest.param('xlsx', '错名名单.xls', 'application/vnd.ms-excel', '张三', id='xlsx_named_xls'),
    ('docx', '通知.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '创新创业竞赛'),
    ('xls', '旧名单.xls', 'application/vnd.ms-excel', '张三'),
    ('pdf', '通知.pdf', 'application/pdf', 'Competition deadline 2026-11-05'),
])
def test_real_asset_store_extensionless_paths_are_readable(tmp_path, kind, filename, media, expected):
    """Production AssetStore uses SHA256 paths; the filename remains metadata only."""
    from io import BytesIO
    from campus_backend.core.artifacts import AssetStore
    stream = BytesIO()
    if kind == 'xlsx':
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['姓名', '学院'])
        book.active.append(['张三', '计算机学院'])
        book.save(stream)
    elif kind == 'docx':
        from docx import Document
        document = Document()
        document.add_paragraph('创新创业竞赛')
        document.save(stream)
    elif kind == 'xls':
        import xlwt
        book = xlwt.Workbook()
        sheet = book.add_sheet('报名')
        sheet.write(0, 0, '张三')
        book.save(stream)
    else:
        stream.write(text_pdf())
    assets_root = tmp_path / 'assets'
    item = AssetStore(assets_root).put(stream.getvalue(), filename=filename, media_type=media)
    assert Path(item['path']).suffix == ''
    result = extract_document(raw(assets=[item]), assets_root)
    assert result['status'] == 'complete', result['errors']
    assert expected in result['payload']['content']
    assert result['payload']['assets'] == [item]


@pytest.mark.parametrize('mode', ['RGBA', 'P'])
def test_transparent_ocr_input_uses_white_background_without_changing_original(tmp_path, mode):
    from PIL import Image
    image = Image.new('RGBA', (20, 20), (0, 0, 0, 0))
    image.putpixel((10, 10), (0, 0, 0, 255))
    if mode == 'P': image = image.convert('P')
    path = tmp_path / 'transparent.png'
    image.save(path)
    original = path.read_bytes()
    seen = []
    class OCR:
        def recognize(self, candidate, *, timeout):
            seen.append(candidate)
            with Image.open(candidate) as prepared:
                assert prepared.mode == 'RGB'
                assert prepared.getpixel((0, 0)) == (255, 255, 255)
                assert prepared.getpixel((10, 10)) == (0, 0, 0)
            return '透明图片中的黑色文字'
    result = extract_document(raw(assets=[asset(tmp_path, path.name, original)]), tmp_path, ocr=OCR())
    assert result['status'] == 'complete'
    assert '透明图片中的黑色文字' in result['payload']['content']
    assert path.read_bytes() == original
    assert seen and seen[0] != path
    assert not seen[0].exists()


def test_empty_ocr_is_still_a_gap_after_transparency_preprocessing(tmp_path):
    from PIL import Image
    path = tmp_path / 'empty.png'
    Image.new('RGBA', (20, 20), (0, 0, 0, 0)).save(path)
    class OCR:
        def recognize(self, candidate, *, timeout): return ''
    result = extract_document(raw('<p>已有正文</p>', [asset(tmp_path, path.name, path.read_bytes())]), tmp_path, ocr=OCR())
    assert result['status'] == 'partial'
    assert result['payload']['content'] == '已有正文'
    assert [error['code'] for error in result['errors']] == ['ocr_empty']


def test_xlsx_keeps_empty_columns_and_expands_only_explicit_merge(tmp_path):
    from openpyxl import Workbook
    from campus_backend.documents.extractors import _parse
    book=Workbook();sheet=book.active;sheet.title='安排'
    sheet.append(['学院','班级','人数','机房'])
    sheet.append([None,'特殊考生',3,'404'])
    sheet.append([None,None,4,'405'])
    sheet.append([None,None,5,'406'])
    sheet.merge_cells('B2:B3')
    path=tmp_path/'schedule.xlsx';book.save(path)
    rows=_parse(path,'xlsx')['segments']
    assert rows[1]['text']=='\t特殊考生\t3\t404'
    assert rows[2]['text']=='\t特殊考生\t4\t405'
    assert rows[2]['table_merges']==['B2:B3']
    assert rows[3]['text']=='\t\t5\t406'
    assert 'table_merges' not in rows[3]


def test_docx_table_does_not_shift_values_past_empty_leading_cells(tmp_path):
    from docx import Document
    from campus_backend.documents.extractors import _parse
    book=Document();table=book.add_table(rows=1,cols=3)
    table.cell(0,1).text='B班';table.cell(0,2).text='404'
    path=tmp_path/'table.docx';book.save(path)
    row=_parse(path,'docx')['segments'][0]
    assert row['text']=='\tB班\t404'


def test_xlsx_merged_area_is_bounded_before_materializing_cells(tmp_path, monkeypatch):
    from openpyxl import Workbook
    from campus_backend.documents import extractors
    from campus_backend.documents.ports import ExtractionError
    book=Workbook();sheet=book.active;sheet['A1']='表';sheet.merge_cells('A1:J20')
    path=tmp_path/'wide.xlsx';book.save(path)
    monkeypatch.setattr(extractors,'MAX_CELLS',30)
    with pytest.raises(ExtractionError,match='合并'):
        extractors._parse(path,'xlsx')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-16-be'])
@pytest.mark.parametrize('member', ['xl/worksheets/sheet1.xml', 'xl/sharedStrings.xml'])
def test_xlsx_rejects_entity_declarations_in_any_encoding_before_office_reader(tmp_path, monkeypatch, encoding, member):
    import zipfile
    from openpyxl import Workbook
    from campus_backend.documents.extractors import _parse
    from campus_backend.documents.ports import ExtractionError
    path = tmp_path / 'input.xlsx'; Workbook().save(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    xml_encoding = 'utf-16' if encoding == 'utf-16-be' else encoding
    entries[member] = (f'<?xml version="1.0" encoding="{xml_encoding}"?>'
        '<!DOCTYPE worksheet [<!ENTITY r "A1:B2">]>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData/><mergeCells><mergeCell ref="&r;"/></mergeCells></worksheet>').encode(encoding)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in entries.items(): archive.writestr(name, content)
    def forbidden(*args, **kwargs):
        pytest.fail('Office reader was called before the XML safety check')
    monkeypatch.setattr('openpyxl.load_workbook', forbidden)
    with pytest.raises(ExtractionError) as error:
        _parse(path, 'xlsx')
    assert error.value.code == 'unsafe_archive'
