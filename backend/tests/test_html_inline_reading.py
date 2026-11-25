"""HTML markup must not split dates or invent joins across real paragraphs."""
from copy import deepcopy

import pytest

from campus_backend.core.artifacts import AssetStore, make_artifact
from campus_backend.documents.service import clean_html, extract_document


@pytest.mark.parametrize(('html', 'expected'), [
    (
        '<p>报名截至<span>10月1</span><em>0</em><a href="#deadline">日</a>17:00。</p>',
        '报名截至10月10日17:00。',
    ),
    (
        '<p><span>公示时间为</span><strong>2026年10月21日</strong>至'
        '<em>10月27日</em>。公示期间若有<a>异议</a>，请书面反映。</p>',
        '公示时间为2026年10月21日至10月27日。公示期间若有异议，请书面反映。',
    ),
    (
        '<p>请于 <span>10月10日</span>  <strong>17:00</strong> 提交&nbsp;材料。</p>',
        '请于 10月10日  17:00 提交\xa0材料。',
    ),
    (
        '<p>10月<span>1</span> <em>0</em>日</p>',
        '10月1 0日',
    ),
])
def test_inline_markup_preserves_contiguous_text_and_existing_spaces(html, expected):
    text, _ = clean_html(html, 'https://example.edu/notice')
    assert text == expected


def test_block_elements_and_breaks_keep_paragraph_boundaries():
    html = ('<article><h2>考试<span>安排</span></h2>'
            '<div>第一段<p>10月1</p><p>0日</p>末段<br>下一行</div>'
            '<ul><li>第一项</li><li>第二项</li></ul></article>')
    text, _ = clean_html(html, 'https://example.edu/notice')
    assert text.splitlines() == ['考试安排', '第一段', '10月1', '0日', '末段', '下一行', '第一项', '第二项']
    assert '10月10日' not in text


def test_table_cells_do_not_become_a_concatenated_date():
    text, _ = clean_html('<table><tr><td>10月1</td><td>0日</td></tr></table>',
                         'https://example.edu/notice')
    assert text.splitlines() == ['10月1', '0日']


def test_inline_link_text_preserves_words_without_losing_url_or_image_evidence():
    html = ('<script>ignore()</script><style>.hidden{}</style>'
            '<p>请下载<a href="form.docx">报<span>名</span>表</a>。'
            '<img src="notice.png" alt="通知图"></p>')
    text, evidence = clean_html(html, 'https://example.edu/n/1')
    assert text == '请下载报名表。'
    assert evidence == {
        'links': [{'url': 'https://example.edu/n/form.docx', 'text': '报名表'}],
        'images': [{'url': 'https://example.edu/n/notice.png', 'alt': '通知图'}],
    }


def test_document_body_and_html_attachment_use_new_reading_version(tmp_path):
    item = AssetStore(tmp_path).put('<p>公示至<span>10月2</span><em>7</em>日。</p>'.encode(),
                                   filename='attached.html', media_type='text/html')
    raw = make_artifact('raw', 'inline-notice', 'source-version', {
        'title': '内联文字测试', 'source_url': 'https://example.edu/notice',
        'html': '<p>报名至<span>10月1</span><em>0</em>日。</p>',
        'body_status': 'complete', 'assets': [item],
    })
    before = deepcopy(raw)
    document = extract_document(raw, tmp_path)
    assert [segment['text'] for segment in document['payload']['segments']] == [
        '报名至10月10日。', '公示至10月27日。',
    ]
    assert document['producer'] == {'name': 'campus-documents', 'version': '1.2'}
    assert document['payload']['extraction']['version'] == '1.2'
    assert raw == before
