"""Local date windows and table rows with explicit source scope."""

import re
import unicodedata
from datetime import date, time
from dataclasses import dataclass

from .product_labels import (
    AbsoluteEndpoint, AudienceGroup, MonthDayEndpoint, PendingEndpoint, ProductScope,
    RelativeEndpoint, Requirement, WindowLabel, WindowValue, endpoints_reversed,
)
from .rule_labels import RuleEvidence
from .rule_baseline import extract_local_scope

_CLOCK_VALUE = r'(?P<hour>\d{1,2})\s*(?:[:：]\s*(?P<minute>\d{2})|[时点](?:\s*(?P<zh_minute>\d{1,2})分?)?)'
_CLOCK = r'(?:\s*(?:[（(]?(?:周|星期)[一二三四五六日天][）)]?)?\s*[（(]?\s*(?P<period>上午|下午|晚上|中午)?\s*' + _CLOCK_VALUE + r')?'
_CALENDAR = re.compile(
    r'(?:(?P<year>\d{4})\s*[年/-]\s*)?(?P<month>\d{1,2})\s*[月/-]\s*'
    r'(?P<day>\d{1,2})\s*(?:[日号]|(?=\s*\d{1,2}[:：])|(?<=[0-9]-[0-9][0-9]))' + _CLOCK
)
_CLOCK_ONLY = re.compile(r'\s*' + _CLOCK_VALUE)
_DAY_ONLY = re.compile(r'(?P<end_day>\d{1,2})\s*[日号]' + _CLOCK)
_LINK = re.compile(r'\s*(?:至|到|[-—–－~～])\s*')
_RELATIVE = re.compile(r'(?P<anchor>拍摄(?:完成|结束)?|考试(?:结束)?|活动(?:结束)?|报名(?:结束)?|发布)(?:后\s*(?P<approx>约)?\s*(?P<days>\d+)\s*(?:天|日)|(?P<before>约\s*\d+\s*(?:天|日)后))')
_PENDING = re.compile(r'另行通知|待通知|待公布')
_TENTATIVE = re.compile(r'暂定|拟定|初定')
_CANCELLED = re.compile(r'(?:活动|比赛|考试)(?:已|确定)?取消$')
_ENDED = re.compile(r'(?:比赛|竞赛|活动|大赛|赛事).{0,40}(?:已(?:经)?结束|圆满结束|落下帷幕|落幕)')
_CAMPUS = re.compile(r'[\u4e00-\u9fa5]{1,8}校区')
_PHASE = re.compile(r'初赛|复赛|决赛|补考|补拍|答辩|面试|初审|公示')
_OBJECTION_CONDITION = re.compile(r'实名|署名|书面')
_SLOT = re.compile(r'^(第[一二三四五六七八九十0-9]+场)\s*[:：]')
_HEADER = {
    '校区': 'campus', '学院': 'college', '院系': 'college', '学院名称': 'college', '上课院系': 'college',
    '采集时间段': 'time', '班级': 'class_name', '专业班级': 'class_name',
    '日期': 'calendar', '时间': 'time', '考试时间': 'time', '拍摄时间': 'time',
    '采集时间': 'time', '考试日期': 'calendar', '拍摄日期': 'calendar', '场次': 'phase',
}
_ACTIONS = (
    ('internal_reporting', r'学院.{0,24}(?:报送|上报)|单位.{0,24}(?:报送|上报)'),
    ('objection', r'异议|申诉|复核'),
    ('policy_effective', r'施行|生效'),
    ('policy_expiry', r'有效期|有效至'),
    ('submission', r'核对照片|提交|报送|递交'),
    ('registration', r'报名|参赛登记'),
    ('application', r'申请|申报'),
    ('event', r'公示|拍摄|(?:图像)?采集时间|图像采集|考试|考核|答辩|面试|比赛|竞赛|活动|讲座|举行|举办'),
)
_ACTION = tuple((code, re.compile(pattern)) for code, pattern in _ACTIONS)


def _parts(text):
    return [(match[0].strip(), match) for match in _CALENDAR.finditer(text)]


def _clock(hour, minute, period):
    hour = int(hour)
    if period in ('下午', '晚上', '中午') and 1 <= hour < 12:
        hour += 12
    return time(hour, int(minute or 0)).isoformat(timespec='minutes')


def _endpoint(match, shared_year=None):
    month, day = int(match['month']), int(match['day'])
    clock = _clock(match['hour'], match['minute'] or match['zh_minute'], match['period']) if match['hour'] else None
    year = int(match['year']) if match['year'] else shared_year
    if year:
        return AbsoluteEndpoint(date=date(year, month, day).isoformat(), time=clock)
    return MonthDayEndpoint(month_day=f'{month:02}-{day:02}', time=clock)


def _endpoints(text):
    text = unicodedata.normalize('NFKC', text)
    parts = _parts(text)
    if not parts:
        return None, None
    match = parts[0][1]
    start = _endpoint(match)
    tail = text[match.end():]
    link = _LINK.match(tail)
    if not link:
        return start, None
    tail = tail[link.end():]
    other = _CALENDAR.match(tail)
    if other:
        shared_year = int(match['year']) if match['year'] else None
        if not other['year'] and (int(other['month']), int(other['day'])) < (int(match['month']), int(match['day'])):
            shared_year = None
        return start, _endpoint(other, shared_year)
    day_only = _DAY_ONLY.match(tail)
    if day_only:
        day = int(day_only['end_day'])
        if day < int(match['day']):
            return start, PendingEndpoint(reason='unresolved')
        clock = _clock(day_only['hour'], day_only['minute'] or day_only['zh_minute'], day_only['period']) if day_only['hour'] else None
        if isinstance(start, AbsoluteEndpoint):
            end = AbsoluteEndpoint(date=date(int(start.date[:4]), int(match['month']), day).isoformat(), time=clock)
        else:
            end = MonthDayEndpoint(month_day=f'{int(match["month"]):02}-{day:02}', time=clock)
        return start, end
    clock = _CLOCK_ONLY.match(tail)
    if clock:
        parsed = _clock(clock['hour'], clock['minute'] or clock['zh_minute'], match['period'])
        return start, start.model_copy(update={'time': parsed})
    return start, None


def calendar_endpoints(text):
    """Parse a calendar date and its contiguous range without selecting a purpose."""
    return _endpoints(text)


def _code(text, context=''):
    for source in (text, context):
        for code, pattern in _ACTION:
            if pattern.search(source):
                return code
    return None


def _product_scope(text, *, action=None):
    local = extract_local_scope(text)
    phase = _PHASE.search(text)
    campus = _CAMPUS.search(text)
    groups = ()
    if local.audience or campus:
        groups = (AudienceGroup(audience=local.audience, campus=campus[0] if campus else None),)
    return ProductScope(action=action, track=local.track, phase=phase[0] if phase else None, audience_groups=groups)


def prose_window(text, evidence, title, context=None):
    if re.match(r'发布时间|发布日期|发文日期|原定|原为', text):
        return None
    ended = _ENDED.search(text)
    code = 'event' if ended else _code(text, context or '')
    if not code and (_PENDING.search(text) or _TENTATIVE.search(text)):
        code = _code(title)
    if not code:
        return None
    relative = _RELATIVE.search(text)
    state = 'ended' if ended else 'tentative' if _TENTATIVE.search(text) else 'announced'
    if relative and not _CALENDAR.search(text):
        if re.search(r'核对|校对|确认', text):
            code = 'submission'
        days = relative['days'] or re.search(r'\d+', relative['before'])[0]
        start = RelativeEndpoint(anchor=relative['anchor'], days=int(days),
                                 approximate=bool(relative['approx'] or relative['before']))
        end = None
    else:
        try:
            start, end = _endpoints(text)
        except ValueError:
            return None
    if not start:
        if _PENDING.search(text):
            start = PendingEndpoint(reason='to_be_announced')
        elif code == 'event' and _CANCELLED.search(text):
            state = 'cancelled'
        elif code == 'event' and _ENDED.search(text):
            state = 'ended'
        else:
            return None
    if end is None and start is not None and (
        code in ('policy_expiry', 'internal_reporting') or state == 'ended' or re.search(r'截止|截至|之前|日[时分0-9:：]*前', text)
    ):
        start, end = None, start
    elif end is None and code == 'objection' and not re.search(r'开始|起', text):
        start, end = None, start
    terms = tuple(dict.fromkeys(_OBJECTION_CONDITION.findall(text))) if code == 'objection' else ()
    requirement = Requirement(operator='text' if len(terms) == 1 else 'all', items=terms) if terms else None
    is_student = code not in ('internal_reporting', 'policy_expiry', 'policy_effective')
    return WindowLabel(code=code, scope=_product_scope(text), evidence=(evidence,),
                       presentation='detail' if code == 'internal_reporting' else 'display',
                       value=WindowValue(start=start, end=end, state='conflicting' if endpoints_reversed(start, end) else state, student_action=is_student,
                                         requirement=requirement))



def prose_windows(text, evidence, title, context=None):
    """Bind each independently dated action before falling back to a single clause."""
    parts = [(m[0].strip(), _code(m[0])) for m in re.finditer(r'[^，,]+', text)]
    dated = [part for part, code in parts if code and _CALENDAR.search(part)]
    if len(dated) > 1 and len({_code(part) for part in dated}) > 1:
        return tuple(window for part in dated
                     if (window := prose_window(part, evidence, title, context)))
    window = prose_window(text, evidence, title, context)
    return (window,) if window else ()


def _cells(line):
    if '\t' in line:
        return tuple(cell.strip() for cell in line.split('\t'))
    if line.strip().startswith('|'):
        return tuple(cell.strip() for cell in line.strip().strip('|').split('|'))
    return ()


@dataclass(frozen=True)
class TableContext:
    columns: tuple[str, ...]
    evidence: RuleEvidence
    code: str
    slot: WindowLabel | None = None


def _horizontal_merged_text(line, ranges):
    cells = [(index, cell.strip()) for index, cell in enumerate(line.split('\t'), 1) if cell.strip()]
    if len(cells) < 2 or len({cell for _, cell in cells}) != 1:
        return None
    def column(letters):
        value = 0
        for letter in letters:
            value = value * 26 + ord(letter) - ord('A') + 1
        return value
    for span in ranges:
        match = re.fullmatch(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', span)
        if (match and match[2] == match[4] and column(match[1]) == cells[0][0]
                and column(match[3]) == cells[-1][0] and len(cells) == cells[-1][0] - cells[0][0] + 1):
            return cells[0][1]
    return None


def table_slot(line, evidence, title, *, allow_unheaded=False, merged_ranges=()):
    if '\t' in line and merged_ranges:
        line = _horizontal_merged_text(line, merged_ranges) or line
    phase = _SLOT.match(line)
    if _code(title) != 'event':
        return None
    if not phase:
        normalized = unicodedata.normalize('NFKC', line).strip()
        if (not allow_unheaded or '\t' in line or not _CALENDAR.match(normalized)
                or _code(line) not in (None, 'event') or re.search(r'出生|填写示例|样例', line)):
            return None
    try:
        start, end = _endpoints(line)
    except ValueError:
        start, end = None, None
    if not phase and (start is None or end is None or not getattr(start, 'time', None) or not getattr(end, 'time', None)):
        return None
    if start is None:
        start = PendingEndpoint(reason='to_be_announced' if _PENDING.search(line) else 'unresolved')
    return WindowLabel(code='event', scope=ProductScope(phase=phase[1] if phase else None), evidence=(evidence,),
                       value=WindowValue(start=start, end=end, state='conflicting' if endpoints_reversed(start, end) else 'announced'))


def table_row(line, evidence, title, context, slot=None):
    cells = _cells(line)
    if not cells:
        return None, None
    first = next((cell for cell in cells if cell), '')
    if re.match(r'^(?:备注|说明|注)\s*[:：]', first):
        return None, None
    columns = tuple(_HEADER.get(cell, '') for cell in cells)
    if ('time' in columns or (slot and 'class_name' in columns)) and sum(bool(col) for col in columns) >= 2:
        code = _code(line, title)
        return (TableContext(columns, evidence, code, slot), None) if code else (None, None)
    if not context or len(cells) > len(context.columns) or any(context.columns[len(cells):]):
        return None, None
    fields = dict(zip(context.columns, cells))
    try:
        start, end = _endpoints(' '.join((fields.get('calendar', ''), fields.get('time', ''))))
    except ValueError:
        return None, None
    if not start and context.slot:
        start, end = context.slot.value.start, context.slot.value.end
    if not start:
        return context, None
    classes = tuple(item.strip() for item in re.split(r'[、，,]', fields.get('class_name', '')) if item.strip())
    campus, college = fields.get('campus') or None, fields.get('college') or None
    groups = tuple(AudienceGroup(campus=campus, college=college, class_name=class_name)
                   for class_name in classes or (None,) if campus or college or class_name)
    if not groups:
        return context, None
    phase = fields.get('phase') or (context.slot.scope.phase if context.slot else None)
    refs = (context.evidence, evidence)
    if context.slot:
        refs = (*context.slot.evidence, *refs)
    return context, WindowLabel(code=context.code, scope=ProductScope(phase=phase, audience_groups=groups),
                                evidence=refs, value=WindowValue(start=start, end=end,
                                    state='conflicting' if endpoints_reversed(start, end) else 'announced'))
