"""Pure document parsing, run in a disposable child with a wall-clock deadline."""
from __future__ import annotations

import base64
from contextlib import ExitStack
import json
import posixpath
from pathlib import Path
import subprocess
import sys
import zipfile
from xml.etree import ElementTree
from xml.parsers import expat

from .ports import ExtractionError

MAX_ASSET_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_ARCHIVE_FILES = 1500
MAX_ARCHIVE_RATIO = 200
MAX_PAGES = 150
MAX_IMAGE_PIXELS = 30_000_000
MAX_TEXT_CHARS = 2_000_000
MAX_SHEETS = 100
MAX_ROWS = 50_000
MAX_CELLS = 250_000
PARSE_TIMEOUT = 30


def kind_for(path: Path, media_type: str = '') -> str:
    ext = path.suffix.lower()
    kinds = {'.pdf':'pdf', '.docx':'docx', '.xlsx':'xlsx', '.xls':'xls', '.doc':'doc',
             '.png':'image', '.jpg':'image', '.jpeg':'image', '.tif':'image', '.tiff':'image',
             '.bmp':'image', '.webp':'image', '.gif':'image', '.txt':'text', '.csv':'text', '.html':'html', '.htm':'html'}
    if ext in kinds:
        return kinds[ext]
    media = media_type.split(';')[0].strip().lower()
    return {'application/pdf':'pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'docx',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':'xlsx',
            'application/vnd.ms-excel':'xls', 'application/msword':'doc',
            'text/plain':'text', 'text/html':'html'}.get(media, 'image' if media.startswith('image/') and media != 'image/svg+xml' else 'unsupported')


def check_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES or sum(i.file_size for i in entries) > MAX_ARCHIVE_BYTES:
                raise ExtractionError('archive_limit', 'Office压缩文件超过解压资源上限')
            for info in entries:
                if info.file_size > MAX_ARCHIVE_BYTES or info.file_size / max(info.compress_size, 1) > MAX_ARCHIVE_RATIO:
                    raise ExtractionError('archive_limit', 'Office压缩文件压缩比超过上限')
                if info.flag_bits & 1:
                    raise ExtractionError('encrypted_document', '加密的Office文件无法提取')
                if info.filename.startswith(('/', '\\')) or '..' in Path(info.filename.replace('\\', '/')).parts:
                    raise ExtractionError('unsafe_archive', 'Office文件包含越界路径')
    except zipfile.BadZipFile as exc:
        raise ExtractionError('corrupt_document', 'Office文件不是有效压缩文档') from exc


def parse_isolated(path: Path, kind: str, *, timeout: float | None = None) -> dict:
    limits = {k: v for k, v in globals().items() if k.startswith('MAX_')}
    try:
        proc = subprocess.run([sys.executable, '-m', 'campus_backend.documents.extractors', str(path), kind, json.dumps(limits)],
                              capture_output=True, text=True, timeout=min(PARSE_TIMEOUT, timeout) if timeout is not None else PARSE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError('parse_timeout', '文件提取超时，原件保留供重试') from exc
    if proc.returncode:
        raise ExtractionError('corrupt_document', '文件解析进程失败')
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        raise ExtractionError('corrupt_document', '文件解析未返回有效结果') from exc
    if 'error' in result:
        raise ExtractionError(result['error']['code'], result['error']['message'])
    return result


def _segment(text, *, page=None, location='', method='text', table=False):
    # Tabs are structural columns. Whitespace stripping must not move a value.
    value = str(text).strip('\r\n') if table else str(text).strip()
    return {'text': value, 'page': page, 'location': location, 'method': method}


def _xlsx_merged_ranges(path):
    """Read explicit OOXML merges without loading the workbook into memory."""
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rel = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    with zipfile.ZipFile(path) as archive:
        checked = set()
        def safe_member(name):
            if name in checked:
                return
            if archive.namelist().count(name) != 1:
                raise ExtractionError('corrupt_document', '电子表格XML成员不唯一')
            def reject_declaration(*_args):
                raise ExtractionError('unsafe_archive', '电子表格XML包含不支持的实体声明')
            # Parse declarations in their declared encoding. Byte substring checks
            # miss UTF-16; the handlers reject a DTD before expanding any entity.
            parser = expat.ParserCreate()
            parser.StartDoctypeDeclHandler = reject_declaration
            parser.EntityDeclHandler = reject_declaration
            parser.ExternalEntityRefHandler = reject_declaration
            try:
                with archive.open(name) as stream:
                    while block := stream.read(65536):
                        parser.Parse(block, False)
                    parser.Parse(b'', True)
            except (expat.ExpatError, ValueError) as exc:
                raise ExtractionError('corrupt_document', '电子表格XML格式无效') from exc
            checked.add(name)
        def metadata(name):
            safe_member(name)
            if archive.getinfo(name).file_size > 1024 * 1024:
                raise ExtractionError('archive_limit', '电子表格元数据超过上限')
            return ElementTree.fromstring(archive.read(name))
        # openpyxl also reads shared strings, styles and relationships; validate
        # those members before handing the archive to any Office reader.
        for info in archive.infolist():
            if info.filename.endswith(('.xml', '.rels')):
                safe_member(info.filename)
        relationships = {item.attrib['Id']: item.attrib for item in metadata('xl/_rels/workbook.xml.rels')}
        result = {}
        for sheet in metadata('xl/workbook.xml').iter(ns + 'sheet'):
            relation = relationships[sheet.attrib[rel]]
            if not relation.get('Type', '').endswith('/worksheet'):
                continue
            target = relation['Target']
            member = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if relation.get('TargetMode') == 'External' or not member.startswith('xl/'):
                raise ExtractionError('unsafe_archive', '工作表引用不在文档内')
            safe_member(member)
            ranges = []
            with archive.open(member) as stream:
                for _, element in ElementTree.iterparse(stream, events=('end',)):
                    if element.tag == ns + 'mergeCell':
                        ranges.append(element.attrib['ref'])
                    element.clear()
            result[sheet.attrib['name']] = ranges
        return result


def _merge_layout(ranges, remaining):
    """Map merged cells only, rejecting oversized or overlapping rectangles."""
    from openpyxl.utils.cell import range_boundaries
    layout, count = {}, 0
    for label in ranges:
        c1, r1, c2, r2 = range_boundaries(label)
        if not all((c1, r1, c2, r2)) or c2 < c1 or r2 < r1:
            raise ExtractionError('corrupt_document', '表格合并范围无效')
        count += (r2 - r1 + 1) * (c2 - c1 + 1)
        if count > remaining or r2 > MAX_ROWS:
            raise ExtractionError('table_limit', '表格合并单元格超过上限')
        for row in range(r1, r2 + 1):
            columns = layout.setdefault(row, {})
            for column in range(c1, c2 + 1):
                if column in columns:
                    raise ExtractionError('corrupt_document', '表格合并范围重叠')
                columns[column] = (r1, c1, label)
    return layout, count


def _has_images(resources, seen=None):
    """Inspect image resources without decoding potentially huge image streams."""
    seen = set() if seen is None else seen
    if resources is None:
        return False
    resources = resources.get_object()
    objects = resources.get('/XObject')
    if not objects:
        return False
    for reference in objects.get_object().values():
        value = reference.get_object()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        if value.get('/Subtype') == '/Image':
            return True
        if value.get('/Subtype') == '/Form' and _has_images(value.get('/Resources'), seen):
            return True
    return False


def _parse(path: Path, kind: str) -> dict:
    if kind == 'xls' and zipfile.is_zipfile(path):
        # Some sites label OOXML workbooks as .xls. Confirm workbook entries first.
        check_archive(path)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if {'[Content_Types].xml', 'xl/workbook.xml'} <= names:
                kind = 'xlsx'
    elif kind in ('docx', 'xlsx'):
        check_archive(path)
    segments, scan_pages, errors, embedded_images = [], [], [], []
    if kind == 'pdf':
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject, StreamObject
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ExtractionError('encrypted_document', '加密PDF无法提取')
        if len(reader.pages) > MAX_PAGES:
            raise ExtractionError('page_limit', 'PDF页数超过上限')
        for number, page in enumerate(reader.pages, 1):
            try:
                contents = page.get('/Contents')
                if contents is not None and not isinstance(contents.get_object(), (StreamObject, ArrayObject)):
                    raise ValueError('invalid page content stream')
                text = (page.extract_text() or '').strip()
                if text:
                    segments.append(_segment(text, page=number, location=f'page:{number}'))
                if not text or _has_images(page.get('/Resources')):
                    scan_pages.append(number)
            except Exception:
                errors.append({'code':'page_failed', 'message':'PDF单页损坏，其他页面仍保留', 'page':number})
    elif kind == 'docx':
        from docx import Document
        document = Document(path)
        for i, paragraph in enumerate(document.paragraphs, 1):
            if paragraph.text.strip():
                segments.append(_segment(paragraph.text, location=f'paragraph:{i}'))
        for i, table in enumerate(document.tables, 1):
            for j, row in enumerate(table.rows, 1):
                segments.append(_segment('\t'.join(cell.text for cell in row.cells), location=f'table:{i}/row:{j}', table=True))
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.filename.startswith('word/media/') and not info.is_dir():
                    embedded_images.append({'name': info.filename, 'data': base64.b64encode(archive.read(info)).decode('ascii')})
    elif kind in ('xlsx', 'xls'):
        # Read-only XLSX iterates lazily: keep the binary stream open until book.close.
        # A stream also avoids openpyxl's filename-extension check for SHA256 assets.
        with ExitStack() as resources:
            cells, rows, merged_cells = 0, 0, 0
            if kind == 'xlsx':
                from openpyxl import load_workbook
                all_merges = _xlsx_merged_ranges(path)
                # Formula source is retained; external links and macros are never executed.
                source = resources.enter_context(path.open('rb'))
                book = load_workbook(source, read_only=True, data_only=False, keep_links=False)
                resources.callback(book.close)
                sheets = book.worksheets
            else:
                import xlrd
                book = xlrd.open_workbook(path, on_demand=True, formatting_info=True)
                resources.callback(book.release_resources)
                sheets = book.sheets()
            if len(sheets) > MAX_SHEETS:
                raise ExtractionError('sheet_limit', '工作表数量超过上限')
            for sheet in sheets:
                name = sheet.title if kind == 'xlsx' else sheet.name
                if kind == 'xlsx':
                    ranges = all_merges.get(name, [])
                else:
                    from openpyxl.utils.cell import get_column_letter
                    ranges = [f'{get_column_letter(c1 + 1)}{r1 + 1}:{get_column_letter(c2)}{r2}'
                              for r1, r2, c1, c2 in sheet.merged_cells]
                layout, merge_count = _merge_layout(ranges, MAX_CELLS - merged_cells)
                merged_cells += merge_count
                anchors = {}
                iterator = sheet.iter_rows(values_only=True) if kind == 'xlsx' else (sheet.row_values(i) for i in range(sheet.nrows))
                for i, values in enumerate(iterator, 1):
                    values = list(values)
                    merged = layout.get(i, {})
                    if merged:
                        values.extend([None] * max(0, max(merged) - len(values)))
                    for column, (anchor_row, anchor_col, _label) in merged.items():
                        if (i, column) == (anchor_row, anchor_col):
                            anchors[(i, column)] = values[column - 1]
                        else:
                            values[column - 1] = anchors.get((anchor_row, anchor_col))
                    rows += 1
                    cells += len(values)
                    if rows > MAX_ROWS or cells > MAX_CELLS:
                        raise ExtractionError('table_limit', '表格行数或单元格数超过上限')
                    text = '\t'.join('' if value is None else str(value) for value in values)
                    if text.strip():
                        segment = _segment(text, location=f'sheet:{name}/row:{i}', table=True)
                        if merged:
                            segment['table_merges'] = sorted({item[2] for item in merged.values()})
                        segments.append(segment)
            if kind == 'xlsx':
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        if info.filename.startswith('xl/media/') and not info.is_dir():
                            embedded_images.append({'name': info.filename, 'data': base64.b64encode(archive.read(info)).decode('ascii')})
                        if info.filename.startswith('xl/charts/') and info.filename.endswith('.xml'):
                            errors.append({'code':'unsupported_component', 'message':'电子表格包含尚未渲染提取的图表，原件已保留'})
    elif kind == 'image':
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        try:
            with Image.open(path) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ExtractionError('image_limit', '图片像素数超过上限')
                if getattr(image, 'n_frames', 1) > 1:
                    raise ExtractionError('unsupported_type', '多帧图片需转换为单页图片或PDF')
                image.verify()
        except Image.DecompressionBombError as exc:
            raise ExtractionError('image_limit', '图片像素数超过上限') from exc
        return {'segments': [], 'scan_pages': [], 'image': True}
    elif kind == 'text':
        data = path.read_bytes()
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gb18030')
        segments.append(_segment(text, location='file'))
    elif kind == 'doc':
        import shutil
        if sys.platform != 'darwin' or not shutil.which('textutil'):
            raise ExtractionError('unsupported_type', '旧DOC需要macOS textutil；当前环境不支持')
        try:
            proc = subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(path)], capture_output=True, timeout=20, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError('parse_timeout', '旧DOC转换超时') from exc
        if proc.returncode:
            raise ExtractionError('corrupt_document', '旧DOC转换失败')
        segments.append(_segment(proc.stdout.decode('utf-8'), location='file'))
    else:
        raise ExtractionError('unsupported_type', '当前文件类型不支持提取')
    if sum(len(s['text']) for s in segments) > MAX_TEXT_CHARS:
        raise ExtractionError('text_limit', '文档文本量超过上限')
    return {'segments': segments, 'scan_pages': scan_pages, 'image': False, 'errors': errors, 'embedded_images': embedded_images}


def main():
    path, kind = Path(sys.argv[1]), sys.argv[2]
    globals().update(json.loads(sys.argv[3]))
    try:
        result = _parse(path, kind)
    except ExtractionError as exc:
        result = {'error': {'code': exc.code, 'message': str(exc)}}
    except Exception:
        result = {'error': {'code': 'corrupt_document', 'message': '文件损坏或格式不兼容'}}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
