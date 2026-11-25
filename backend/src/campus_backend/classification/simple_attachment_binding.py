"""Bind numbered references using only quoted attachment lists and read titles."""
import re
import unicodedata
from collections import defaultdict

from .product_context import _without_issue_signature
from .rule_labels import RuleEvidence

_NUMBER = r'(?:\d+|[一二三四五六七八九十]+)'
_REFERENCE = re.compile(r'(?:详?见|查看)附件\s*(' + _NUMBER + ')')
_LIST_START = re.compile(r'^附件\s*[:：]\s*(.*)$')
_NAMED_ENTRY = re.compile(r'^附件\s*(' + _NUMBER + r')\s*[:：.．、]\s*(.+)$')
_ENTRY = re.compile(r'^(' + _NUMBER + r')\s*[:：.．、]\s*(.+)$')


def _number(text):
    if text.isdecimal():
        return int(text)
    digits = {char: index for index, char in enumerate('一二三四五六七八九', 1)}
    if text in digits:
        return digits[text]
    if re.fullmatch(r'[一二三四五六七八九]?十[一二三四五六七八九]?', text):
        tens, units = text.split('十')
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return None


def _key(text):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).strip('《》')
    return re.sub(r'\.(?:pdf|docx?|xlsx?|pptx?)$', '', text, flags=re.I).rstrip('。；;')


def _list_entries(document):
    sources = defaultdict(list)
    for segment in document.segments:
        if segment.kind == 'body' or segment.asset_id in document.primary_asset_ids:
            sources[(segment.kind, segment.asset_id)].append(segment)
    for segments in sources.values():
        active, number, lines, refs = False, None, [], []
        for segment in segments:
            text = _without_issue_signature(segment.text) if segment is segments[-1] else segment.text
            for raw_line in text.splitlines():
                line = unicodedata.normalize('NFKC', raw_line).strip()
                start = _LIST_START.fullmatch(line)
                named = _NAMED_ENTRY.fullmatch(line)
                if start:
                    active = True
                    line = start[1]
                entry = named or (_ENTRY.fullmatch(line) if active else None)
                if entry:
                    if number is not None:
                        yield number, _key(''.join(lines)), tuple(refs)
                    number, lines = _number(entry[1]), [entry[2]]
                    refs = [RuleEvidence(segment_id=segment.id, quote=raw_line.strip())]
                    active = True
                elif active and number is not None:
                    if not line or re.match(r'^[一二三四五六七八九十]+[、.]', line):
                        yield number, _key(''.join(lines)), tuple(refs)
                        active, number, lines, refs = False, None, [], []
                    else:
                        lines.append(line)
                        refs.append(RuleEvidence(segment_id=segment.id, quote=raw_line.strip()))
        if number is not None:
            yield number, _key(''.join(lines)), tuple(refs)


def _first_titles(document):
    verified = {(asset.asset_id, asset.asset_hash) for asset in document.assets if asset.asset_hash}
    seen = set()
    for segment in document.segments:
        if (segment.kind != 'attachment' or segment.asset_id in document.primary_asset_ids
                or segment.asset_id in seen or (segment.asset_id, segment.asset_hash) not in verified):
            continue
        seen.add(segment.asset_id)
        # Repeated merged spreadsheet cells are one heading, not several titles.
        first_line = segment.text.splitlines()[0].strip()
        cells = {_key(cell) for cell in first_line.split('\t') if cell.strip()}
        if len(cells) == 1:
            yield next(iter(cells)), segment.asset_id, RuleEvidence(segment_id=segment.id, quote=first_line)


def _title_matches(document, expected, actual, asset_id):
    if expected == actual:
        return True
    year = re.match(r'((?:19|20)\d{2})年', expected)
    if not year or expected[year.end():] != actual:
        return False
    # An omitted header year is admissible only when the read attachment itself
    # explicitly proves the same sole calendar year. Cohort years do not count.
    years = {found for segment in document.segments if segment.asset_id == asset_id
             for found in re.findall(r'(?<!\d)((?:19|20)\d{2})\s*年', segment.text)}
    return years == {year[1]}


def compatible_audience(pointer, schedule):
    """Allow finer table groups, but never bind explicitly contradictory ones."""
    def compatible(left, right):
        if any(getattr(left, field) and getattr(right, field)
               and getattr(left, field) != getattr(right, field)
               for field in ('campus', 'college', 'class_name')):
            return False
        a, b = left.audience or '', right.audience or ''
        types = lambda text: set(re.findall(r'本科|专科|研究生|硕士|博士', text))
        ta, tb = types(a), types(b)
        graduate = {'研究生', '硕士', '博士'}
        if ta & {'硕士', '博士'} and tb & {'硕士', '博士'} and not ta & tb & {'硕士', '博士'}:
            return False
        if ta and tb and not (ta & tb or ta <= graduate and tb <= graduate):
            return False
        # An explicitly excluded cohort is not an affirmative year constraint.
        ya = set(re.findall(r'(?<!非)(?<!\d)(\d{4})[级届]', a))
        yb = set(re.findall(r'(?<!非)(?<!\d)(\d{4})[级届]', b))
        if ya and yb and not ya & yb:
            return False
        if any(re.search(f'非{year}[级届]', b) for year in ya) or any(re.search(f'非{year}[级届]', a) for year in yb):
            return False
        return True
    return (not pointer.audience_groups or not schedule.audience_groups or any(
        compatible(left, right) for left in pointer.audience_groups for right in schedule.audience_groups))


def audience_covered(pointer, schedules):
    """The union of bound rows must cover every explicit pointer alternative."""
    return all(any(compatible_audience(pointer.model_copy(update={'audience_groups': (group,)}), row)
                   for row in schedules) for group in pointer.audience_groups)


def bind_numbered_attachment(document, evidence):
    """Return (numbered, asset_id, proof); ambiguity never falls back to guessing."""
    numbers = set()
    for ref in evidence:
        text = unicodedata.normalize('NFKC', ref.quote)
        for match in _REFERENCE.finditer(text):
            # A multi-attachment pointer needs a separate set-valued resolver.
            if re.match(r'\s*[-—–至、,，和及.]\s*(?:附件)?' + _NUMBER, text[match.end():]):
                return True, None, ()
            number = _number(match[1])
            if number is None:
                return True, None, ()
            numbers.add(number)
    if not numbers:
        return False, None, ()
    if len(numbers) != 1:
        return True, None, ()
    number = next(iter(numbers))
    entries = [(key, refs) for item, key, refs in _list_entries(document) if item == number]
    if len({key for key, _ in entries}) != 1:
        return True, None, ()
    title = entries[0][0]
    matches = [(asset_id, ref) for key, asset_id, ref in _first_titles(document)
               if _title_matches(document, title, key, asset_id)]
    if len(matches) != 1:
        return True, None, ()
    asset_id, heading = matches[0]
    proof = tuple(dict.fromkeys(ref for _, refs in entries for ref in refs)) + (heading,)
    return True, asset_id, proof
