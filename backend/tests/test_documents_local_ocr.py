"""Real local Chinese OCR, skipped on machines lacking macOS Vision."""
from hashlib import sha256
from pathlib import Path
import shutil
import sys

import pytest

from campus_backend.core.artifacts import make_artifact
from campus_backend.documents.ocr import MacVisionOCR
from campus_backend.documents.service import extract_document


@pytest.mark.skipif(sys.platform != 'darwin' or not shutil.which('swiftc') or not shutil.which('pdftoppm'), reason='requires macOS Vision, Swift and Poppler')
@pytest.mark.parametrize('filename,media', [('chinese-notice.png', 'image/png'), ('chinese-scanned.pdf', 'application/pdf')])
def test_real_chinese_local_ocr(filename, media, tmp_path):
    fixtures = Path(__file__).resolve().parent / 'fixtures/ocr'
    before = {str(path.relative_to(fixtures)): sha256(path.read_bytes()).hexdigest()
              for path in fixtures.rglob('*') if path.is_file()}
    root = tmp_path / 'assets'
    root.mkdir()
    shutil.copyfile(fixtures / filename, root / filename)
    item = {'asset_id': filename, 'path': filename, 'filename': filename, 'media_type': media,
            'sha256': sha256((root / filename).read_bytes()).hexdigest(), 'status': 'complete'}
    source = make_artifact('raw', 'local-synthetic-fixture', '1', {
        'title': '本地中文OCR测试素材（非官网事实）', 'html': '', 'body_status': 'complete', 'assets': [item],
    })
    result = extract_document(source, root, ocr=MacVisionOCR(tmp_path / 'ocr-cache'))
    after = {str(path.relative_to(fixtures)): sha256(path.read_bytes()).hexdigest()
             for path in fixtures.rglob('*') if path.is_file()}
    assert after == before, 'OCR验证不得在只读素材目录写入缓存或修改原件'
    assert result['status'] == 'complete', result['errors']
    text = result['payload']['content']
    assert '中南大学学生竞赛通知' in text
    assert '报名截止：2026年11月5日' in text
    assert '请提交报名表和学生证。' in text
    assert result['payload']['segments'][0]['method'] == 'ocr'
