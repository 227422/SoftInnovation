"""Extract product tags from public notice text."""

import re
from collections import defaultdict
from dataclasses import replace

from campus_backend.documents.models import DocumentBundle
from .product_context import SourceClause, primary_clauses, reading_text
from .product_labels import PendingEndpoint, ProductScope, RelativeEndpoint, endpoints_reversed
from .rule_baseline import extract_local_scope
from .rule_labels import RuleEvidence, RuleGap
from .rule_windows import calendar_endpoints, table_row, table_slot
from .simple_audiences import collect_audiences, groups as audience_groups, target_groups
from .simple_labels import (
    SimpleAudienceLabel, SimpleBenefitLabel, SimpleDateLabel, SimpleDateValue, SimpleFact,
    SimpleRuleResult, SimpleStatusLabel,
)
from .simple_context import calendar_context, primary_view
from .simple_categories import classify_simple_notice
from .simple_table_scope import normalize_table_scope

_SENTENCE = re.compile(r'[^。；;！？!?]+')
_PHASE = re.compile(r'初赛|复赛|半决赛|决赛|补考|补拍|答辩|面试|初审|公示|第[一二三四五六七八九十\d]+场')
_ACTIONS = (
    ('policy_validity', r'施行|生效|有效期|有效至|长期有效|永久有效|失效|废止'),
    ('objection', r'异议|申诉|复核'),
    ('registration', r'报名|参赛登记|(?:社团|成员)?注册'),
    ('application', r'申请|申报'),
    ('submission', r'核对(?:照片|图像)|校对(?:照片|图像)|提交|递交|补交|报送'),
    ('event', r'名单公示|结果公示|公示|拍摄|(?:图像)?采集|考试|考核|答辩|面试|比赛|竞赛|'
              r'初赛|复赛|半决赛|决赛|初审|项目测试|心理测试|抽签|活动|讲座|举行|举办|开赛'),
)
_ACTIONS = tuple((code, re.compile(pattern)) for code, pattern in _ACTIONS)
_INTERNAL = re.compile(
    r'(?:各|有关|相关)?(?:学院|单位|部门|院系|负责老师|辅导员|教务处).{0,35}(?:报送|上报|汇总提交|统一提交)'
    r'|(?:报送|上报)(?:至|于)?'
)
_UNITS = re.compile(r'^(?:请)?(?:各|有关|相关)(?:单位|学院|院系|部门).{0,35}(?:提交|申报|报送|上报)')
_CALENDAR_DURATION = re.compile(r'(?:时间|时长)(?:为|是|:)?\s*[\d一二三四五六七八九十百]+\s*(?:分钟|小时)')
_TIME = re.compile(
    r'截止|截至|日期|时间|公示期|有效期|有效至|起止|开始|结束于|'
    r'\d{1,2}月\d{1,2}[日号]|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{4}年\d'
)
_HEADING = re.compile(r'^(?:[一二三四五六七八九十\d]+[.、]\s*)?[^:。]{1,24}(?:时间|日期|日程|安排|有效期)\s*:?$')
_PENDING = re.compile(r'待定|待通知|待公布|另行通知|另行公布|尚未确定|见附件|详见附件|以(?:后续|系统|准考证).{0,10}为准')
_SCHEDULE_POINTER = re.compile(r'(?:时间|日期|安排|日程|有效期)(?:请|具体|详)?(?:详?见|查看)附件')
_TENTATIVE = re.compile(r'暂定|拟定|初定|初步定')
_LONG_TERM = re.compile(r'长期有效|永久有效')
_CALENDAR_HINT = re.compile(r'\d{1,2}\s*月|(?<!\d)(?:19|20)\d{2}[-/.]\d')
_ENDED = re.compile(r'(?:已(?:经)?|圆满)(?:结束|闭幕|落幕)|落下帷幕|'
                    r'已(?:经)?于[\d年月日号时分点:：/\-—()（）周星期一二三四五六七八九十早晚上下午 ]{2,48}'
                    r'(?:正式|圆满)?(?:结束|闭幕|落幕)')
_CANCELLED = re.compile(r'(?:已(?:经)?|确定|现)?取消(?:举行|举办)?$')
_NEGATIVE_DATE = re.compile(r'不再接受(?:异议|申诉|复核)|不接受(?:异议|申诉|复核)|不是|不实|并非')
_REVISION = re.compile(r'(?:现)?(?:延长|延后|延期|推迟|顺延|改|调整)至')
_ORIGINAL = re.compile(r'原(?:为|定(?:为|于)?|先为)')
_POLICY_END = re.compile(r'有效(?:期)?至|失效|废止')
_DEADLINE = re.compile(r'截止|截至|最迟|之前|[日号分]前|\d{1,2}[:：]\d{2}前')
_WINDOW_START = re.compile(r'(?:开始|自|从).{0,25}(?:起|开始)|(?:日|时|分)起')
_RELATIVE = re.compile(
    r'(?P<anchor>拍摄(?:完成|结束)?|考试(?:结束)?|活动(?:结束)?|报名(?:结束)?|发布)'
    r'(?:后\s*(?P<approx>约)?\s*(?P<days>\d+)\s*(?:天|日)|约\s*(?P<later>\d+)\s*(?:天|日)后)'
)
_PUBLICITY_REFERENCE = re.compile(r'公示(?:期间|期内).{0,20}(?:异议|申诉|复核)')
_DAY_COUNT = r'(?:\d+|[一二三四五六七八九]?十[一二三四五六七八九]?|[一二三四五六七八九])'
_WITHIN_DAYS = re.compile(r'(?<![工作一二三四五六七八九十百千万零])(' + _DAY_COUNT + r')(?:天|日)(?:之)?内')
_PUBLICITY_DAYS = re.compile(r'公示(?:期|时间|期限)(?:为|是|:)?\s*(' + _DAY_COUNT + r')(?:天|日)')
_CLOCK_ONLY_WINDOW = re.compile(r'\s*(\d{1,2}:\d{2})\s*[-—–~至]\s*(\d{1,2}:\d{2})\s*')
_BENEFIT = re.compile(
    r'(?P<volunteer_hours>志愿(?:服务)?(?:时长|工时)(?:(?![、，,]).{0,8}小时)?)'
    r'|(?P<innovation_credit>创新(?:创业|实践)?学分)|(?P<course_credit>课程学分|实践学分|学分)'
    r'|(?P<sports_points>体育(?:积分|分))|(?P<second_classroom_points>第二课堂(?:积分|分数|学分))'
    r'|(?P<recommendation_points>(?:推免|保研)(?:加分|积分))'
    r'|(?P<comprehensive_points>(?:综测|综合测评)(?:加分|积分))'
    r'|(?P<financial_award>奖金|奖励金|奖学金|助学金|补助(?:金)?|补贴)'
    r'|(?P<certificate>(?:获奖|荣誉|参与|结业|培训)?证书)'
)
_GRANT = re.compile(
    r'(?:可(?:以)?|将|予以)?(?:获(?:得|取)?|取得|认定|计入|折算|发放|授予|给予|颁发|提供|'
    r'奖励(?:为)?|领取|兑换|享受|保留)|(?:可(?:以)?|将)计|计为|加计|累积|积累|设(?:有|立)?'
)
_NO_GRANT = re.compile(r'不予|不再|不(?:会|得|计|认|加|获|发|颁|享|提供|折算|设)|不能|不可|无法|无(?:额外|任何)?|没有|尚未|并非|不是')
_UNCERTAIN_CLAIM = re.compile(r'不实|不成立|仅供参考|尚未确定|是否.{0,12}(?:另行|待定)|有待确定')
_SUFFIX_GRANT = re.compile(r'^(?:按[^,，]{1,20})?(?:可(?:以)?|将|予以)?(?:认定|计入|折算|发放|发给|颁发|给予|授予)')
_MATERIAL = re.compile(r'提交|上传|携带|验核|出示|查验|附上|申请材料|复印件|扫描件|原件|证明|须持')
_PREEXISTING = re.compile(r'曾经?|历年|往年|往届|此前|以往|已(?:经)?(?:获得|取得)|原有|已有|持有')
_CURRICULUM = re.compile(r'最低|至少|不少于|至多|不超过|须修满|学分要求|共计|合计|总计|课程包|开设|设置|课程总')
_SCOPE_ACTION = re.compile(r'([\u3400-\u9fffA-Za-z0-9]{1,24}(?:项目|计划|专项|方案|班))(?=报名|申请|申报|提交|参加者|参与者|参赛者)')
_STATUS_PATTERNS = (
    ('result_publicity', re.compile(r'名单公示|结果公示|公示名单')),
    ('event_ended', _ENDED),
    ('policy_valid', re.compile(r'(?:现行|目前(?:仍然?)?|现|仍然?|继续|长期|永久)有效')),
    ('policy_expired', re.compile(r'已(?:经)?(?:废止|失效)')),
)
_STATUS_DISPUTED = re.compile(r'并非|不是|并未|并不|不实|否认|质疑|待核实|所谓|不再有效|[“”「」『』]')


def _refs(*collections):
    return tuple(dict.fromkeys(ref for collection in collections for ref in collection))


def _groups(text):
    """Keep scope parsing on the same audience-only vocabulary as target tags."""
    return audience_groups(text)


def _scope(text, context=''):
    local = extract_local_scope(text)
    phase = _PHASE.search(text) or _PHASE.search(context)
    if _ENDED.search(text):
        # PDF headings can be glued to the first paragraph. The announcement's
        # publicity phase does not govern the preceding event that ended.
        phase_text = re.split(r'通知|公告', text)[-1].split(_ENDED.search(text)[0], 1)[0]
        phase = _PHASE.search(phase_text)
    action = _SCOPE_ACTION.search(text)
    publication = re.search(r'(?:公布|发布).{0,12}名单|名单[^。；;]{0,45}(?:公布|发布|公示)', text)
    return ProductScope(action=action[1] if action else None, track=local.track or extract_local_scope(context).track,
                        phase='名单公布' if publication and (not phase or phase[0] != '公示') else phase[0] if phase else None,
                        audience_groups=_groups(text))


def _benefits(text, evidence, *, title=False):
    matches = list(_BENEFIT.finditer(text))
    active = False
    for index, match in enumerate(matches):
        before = text[matches[index - 1].end() if index else 0:match.start()]
        after = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        tail = re.split(r'[,，、]|但|也不', after, maxsplit=1)[0]
        local = re.split(r'[,，]|但', before)[-1]
        grants = list(_GRANT.finditer(local))
        denial = _NO_GRANT.search(local)
        material = _MATERIAL.search(before + match[0] + tail)
        valid_grant = bool(grants and not re.search(r'是否|能否', local))
        if grants and denial and not _NO_GRANT.search(local[grants[-1].start():]):
            # An earlier negative can state a failed condition. A negation
            # immediately before this grant still governs it.
            denial = _NO_GRANT.search(local[max(0, grants[-1].start() - 4):])
        if denial or _NO_GRANT.match(tail.strip()) or _UNCERTAIN_CLAIM.search(tail):
            active = False
            continue
        if (material and (not grants or material.start() <= before.rfind(local) + grants[-1].start())
                or _PREEXISTING.search(local) or re.match(r'\s*(?:的)?(?:原件|复印件|证明|扫描件)', tail)):
            active = False
            continue
        if match.lastgroup == 'course_credit' and _CURRICULUM.search(before + tail):
            active = False
            continue
        active = bool(valid_grant or _SUFFIX_GRANT.search(tail) or (
            active and re.fullmatch(r'[\d\u3400-\u9fff .~—-]{0,16}[、及与和或,，]+\s*', before)
        ))
        named_aid = (
            match.lastgroup == 'financial_award'
            and (title or re.match(r'^(?:本次|本年度)?(?:面向|开展|设立|评审|评选|申请|申报)', text))
            and re.search(r'评审|评选|申请|申报|评定|发放', text)
            and not material
        )
        if active or named_aid:
            yield SimpleBenefitLabel(code=match.lastgroup, scope=_scope(text), evidence=evidence)


def _denied_title_codes(clauses):
    codes = set()
    for clause in clauses:
        for part in re.split(r'[,，]', clause.text):
            denial = _NO_GRANT.search(part)
            if not denial or not re.fullmatch(r'(?:本次|本届|本年度|本项(?:目|活动|比赛))?', part[:denial.start()]):
                continue
            tail = re.split(r'但|而|同时', part[denial.start():], maxsplit=1)[0]
            codes.update(match.lastgroup for match in _BENEFIT.finditer(tail))
    return codes


def _purpose(text, *, in_title=False):
    if not in_title:
        text = re.sub(r'《[^》]*》', '', text)
    if re.search(r'(?:在线)?(?:校对|核对)(?:照片|图像)', text):
        return 'submission'
    if _CALENDAR_HINT.search(text) and _ENDED.search(text):
        return 'event'
    if re.search(r'公示(?:时间|日期|期限|期)(?:为|是|:|\d|[一二三四五六七八九十])', text):
        return 'objection' if re.search(r'异议|申诉|复核', text) else 'event'
    if re.search(r'(?:企业|公司|工商|营业执照).{0,25}(?:完成|办理)?注册', text) and not re.search(r'报名|参赛登记', text):
        return None
    student_reporting = bool(re.search(r'(?:请)?(?:学生|同学(?:们)?|参赛者|申请人)(?:请|须|需|应|于|在|自行|填报)', text))
    unit_subject = bool(re.search(r'^(?:\d+[.、])?(?:请)?(?:各|有关|相关|各二级)?(?:学院|单位|院系|部门)(?:请|应|须|需|于|在|汇总|统一)', text))
    if _UNITS.search(text) or (_INTERNAL.search(text) and (unit_subject or not student_reporting)):
        return 'internal_reporting'
    # Prior actions in a result announcement do not own the following event date.
    if re.search(r'(?:经过|经|完成).{0,30}(?:报名|申请|申报)[^。]*[,，]', text):
        tail = re.split(r'[,，]', text)[-1]
        if _CALENDAR_HINT.search(tail) and re.search(r'比赛|竞赛|活动|公示|考试|考核', tail):
            return 'event'
    return next((code for code, pattern in _ACTIONS if pattern.search(text)), None)


def _date_parts(text):
    parts = re.split(r'[,，\n]', text)
    # Text with its own purpose and its own time starts a new fact. Keep commas
    # inside a single fact so end markers, tentative wording and names survive.
    groups = []
    for part in parts:
        if groups and (not (_purpose(part) and (_TIME.search(part) or _PENDING.search(part)))
                       or not (_TIME.search(groups[-1]) or _PENDING.search(groups[-1]))):
            groups[-1] += ',' + part
        else:
            groups.append(part)
    return groups


def _date_value(text, code):
    pending = _PENDING.search(text)
    tentative = _TENTATIVE.search(text)
    long_term = code == 'policy_validity' and bool(_LONG_TERM.search(text))
    state = 'announced'
    try:
        start, end = calendar_endpoints(text)
    except ValueError:
        start, end = PendingEndpoint(reason='unresolved'), None
    relative = _RELATIVE.search(text)
    if not start and relative:
        start = RelativeEndpoint(anchor=relative['anchor'], days=int(relative['days'] or relative['later']),
                                 approximate=bool(relative['approx'] or relative['later']))
    if re.search(r'即日起|自(?:本通知|通知)(?:发布|公布)之日起', text):
        end = end or start
        start = RelativeEndpoint(anchor='通知发布', days=0, approximate=False)
    ended = code == 'event' and _ENDED.search(text)
    cancelled = code == 'event' and _CANCELLED.search(text)
    if not start and not long_term and not ended and not cancelled:
        if pending or tentative or _TIME.search(text):
            reason = 'to_be_announced' if pending and not re.search(r'附件|为准', pending[0]) else 'unresolved'
            start = PendingEndpoint(reason=reason)
        else:
            return None
    if end is None and start is not None and re.search(r'开始|日起', text):
        before, separator, after = text.partition(',')
        if separator and _DEADLINE.search(after) and (re.search(r'开始|日起', before) or _WINDOW_START.search(before)):
            try:
                end, _ = calendar_endpoints(after)
            except ValueError:
                end = PendingEndpoint(reason='unresolved')
    if end is None and start is not None and pending and _WINDOW_START.search(text[:pending.start()]) and (
            _DEADLINE.search(text) or code == 'policy_validity' and _POLICY_END.search(text)):
        end = PendingEndpoint(reason='to_be_announced')
    if end is None and start is not None and not long_term and (
        _DEADLINE.search(text) or (code == 'policy_validity' and _POLICY_END.search(text))
        or ended or (code == 'event' and re.search(r'结束|闭幕', text))
        or (code == 'objection' and not re.search(r'开始|日起', text))
    ):
        start, end = None, start
    if endpoints_reversed(start, end):
        state = 'conflicting'
    elif cancelled:
        state = 'cancelled'
    elif ended:
        state = 'ended'
    elif tentative:
        state = 'tentative'
    elif any(endpoint and endpoint.kind in ('month_day', 'pending') for endpoint in (start, end)):
        state = 'unknown'
    return SimpleDateValue(start=start, end=end, state=state, explicit_long_term=long_term)


def _is_time_heading(text):
    return bool(_HEADING.fullmatch(text) and not _CALENDAR_HINT.search(text))


def _day_count(text):
    if text.isdecimal():
        return int(text)
    digits = {char: index for index, char in enumerate('一二三四五六七八九', 1)}
    if '十' in text:
        tens, units = text.split('十')
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return digits[text]


def _date_labels(clause, title):
    text = clause.text
    section = clause.section
    evidence = clause.evidence
    if clause.heading_evidence and _is_time_heading(section):
        evidence = _refs((clause.heading_evidence,), evidence)
    if not text or _NEGATIVE_DATE.search(text) or re.match(r'^(?:发文|发布|成文)日期|^(?:发文|发布)时间', text):
        return
    phase_prefix = _PHASE.fullmatch(text.partition(':')[0].strip()) if ':' in text else None
    for part in _date_parts(text):
        publicity_marker = re.search(r'公示(?:时间|日期|期)(?:为|是|:)', part)
        if publicity_marker and all(word in part[:publicity_marker.start()] for word in ('姓名', '学号')):
            # A PDF roster has no sentence punctuation between its header,
            # student rows and footer. Its rows do not restrict the footer date.
            part = part[publicity_marker.start():]
        if _is_time_heading(part):
            continue
        duration = _WITHIN_DAYS.search(part)
        if duration and '公示' in title + text and _purpose(part) == 'objection':
            days = _day_count(duration[1])
            anchor_match = re.search(r'(收到(?:邮件|通知|结果)|(?:本通知)?发布|公示开始)后', part)
            anchor = anchor_match[1] if anchor_match else '公示开始'
            yield SimpleDateLabel(code='objection', scope=_scope(part, section), evidence=evidence,
                                  value=SimpleDateValue(
                                      start=RelativeEndpoint(anchor=anchor, days=0, approximate=False),
                                      end=RelativeEndpoint(anchor=anchor, days=days, approximate=False)))
            continue
        publicity_days = _PUBLICITY_DAYS.search(part)
        if publicity_days and not _CALENDAR_HINT.search(part):
            days = _day_count(publicity_days[1])
            yield SimpleDateLabel(code='event', scope=_scope(part, section), evidence=evidence,
                                  value=SimpleDateValue(
                                      start=RelativeEndpoint(anchor='公示开始', days=0, approximate=False),
                                      end=RelativeEndpoint(anchor='公示开始', days=days, approximate=False)))
            continue
        if not _CALENDAR_HINT.search(part) and not _RELATIVE.search(part):
            if _CALENDAR_DURATION.search(part):
                continue
            pending = _PENDING.search(part)
            if pending and '附件' in pending[0] and not _SCHEDULE_POINTER.search(part):
                continue
            if pending and re.search(r'赛题|地点|名单|材料|数额|金额', part) and not re.search(
                    r'时间|日期|日程|截止|起止|何时', part):
                continue
            if not pending and not _TENTATIVE.search(part) and not re.search(
                    r'截止|截至|起止|有效期|有效至', part):
                if not (_LONG_TERM.search(part) or _ENDED.search(part) or _CANCELLED.search(part)):
                    continue
        revision = _REVISION.search(part)
        original = _ORIGINAL.search(part)
        if original and not revision:
            continue
        parse_text = part[revision.end():] if revision else part
        code = _purpose(part) or (_purpose(section) if _is_time_heading(section) else None)
        if not code and (_PHASE.search(part) or (_PENDING.search(part) and _TIME.search(part))):
            code = 'event' if _PHASE.search(part) else _purpose(title, in_title=True)
        if code in (None, 'internal_reporting'):
            continue
        if code == 'policy_validity' and not (_TIME.search(parse_text) or _LONG_TERM.search(parse_text)
                                               or _PENDING.search(parse_text)):
            continue
        if (code in ('submission', 'objection') and not (_TIME.search(parse_text) or _RELATIVE.search(parse_text))
                and not re.search(r'(?:时间|日期|截止)(?:为|是|:)?', parse_text)):
            continue
        if re.search(r'复核方可|复核后(?:可|获)|审核通过', part) and not _TIME.search(parse_text):
            continue
        value = _date_value(parse_text, code)
        if value is None:
            continue
        if revision:
            action_window = code in ('registration', 'application', 'submission', 'objection')
            value = value.model_copy(update={
                'end': value.end or value.start if action_window else value.end,
                'start': None if action_window else value.start,
                'state': 'rescheduled' if value.state == 'announced' else value.state,
            })
        yield SimpleDateLabel(code=code, scope=_scope(part, phase_prefix[0] if phase_prefix else section),
                              evidence=evidence, value=value)


def _prose(document):
    primary = primary_clauses(document)
    source_ids = {ref.segment_id for clause in primary for ref in clause.evidence}
    extras = []
    for segment in document.segments[1:]:
        if segment.id in source_ids or segment.kind == 'body' or segment.asset_id in document.primary_asset_ids:
            continue
        for line in segment.text.splitlines():
            if '\t' in line or line.lstrip().startswith('|'):
                continue
            for match in _SENTENCE.finditer(line):
                quote = match[0].strip()
                if quote:
                    extras.append(SourceClause(reading_text(quote), (RuleEvidence(segment_id=segment.id, quote=quote),),
                                               source_key=(segment.kind, segment.asset_id)))
    return primary, extras


def _table_dates(document):
    context, slot, location = None, None, None
    labels = {}
    cited_slots = set()
    for segment in document.segments[1:]:
        sheet = segment.location.split('/row:', 1)[0] if segment.location.startswith('sheet:') else None
        key = (segment.kind, segment.asset_id, segment.page, sheet)
        if key != location:
            context, slot, location = None, None, key
        lines = (segment.text,) if sheet and '\t' in segment.text else segment.text.splitlines()
        for raw in lines:
            line = raw.strip('\r\n') if '\t' in raw else raw.strip()
            if not line.strip():
                continue
            evidence = RuleEvidence(segment_id=segment.id, quote=line)
            next_slot = table_slot(line, evidence, document.title, allow_unheaded=bool(sheet),
                                   merged_ranges=segment.table_merges)
            if next_slot:
                slot, context = next_slot, None
                cited_slots.add(evidence)
                continue
            context, row = table_row(line, evidence, document.title, context, slot)
            if row and row.code != 'internal_reporting':
                row = row.model_copy(update={'scope': normalize_table_scope(row.scope)})
                code = 'policy_validity' if row.code in ('policy_effective', 'policy_expiry') else row.code
                value = SimpleDateValue(start=row.value.start, end=row.value.end, state=row.value.state)
                if any(endpoint and endpoint.kind in ('month_day', 'pending') for endpoint in (value.start, value.end)):
                    value = value.model_copy(update={'state': 'unknown'})
                campus = tuple(dict.fromkeys(group.campus for group in row.scope.audience_groups))
                key = (code, row.scope.action, row.scope.track, row.scope.phase, value, campus, row.evidence[0])
                prior = labels.get(key)
                if prior:
                    groups = tuple(dict.fromkeys((*prior.scope.audience_groups, *row.scope.audience_groups)))
                    scope = row.scope.model_copy(update={'audience_groups': groups})
                    refs = _refs(prior.evidence, row.evidence)
                else:
                    scope, refs = row.scope, row.evidence
                labels[key] = SimpleDateLabel(code=code, scope=scope, evidence=refs, value=value)
    return list(labels.values()), cited_slots


def _audiences(text, evidence, *, context='', title=False, date=False):
    scope = _scope(text, context).model_copy(update={'audience_groups': ()})
    for group in target_groups(text, context=context, title=title, date=date):
        yield SimpleAudienceLabel(value=group, scope=scope, evidence=evidence)


def _statuses(text, evidence):
    if _STATUS_DISPUTED.search(text):
        return
    for value, pattern in _STATUS_PATTERNS:
        if pattern.search(text) and (value != 'event_ended'
                                     or _purpose(text) == 'event'
                                     or _purpose(text) is None and not re.search(r'报名|申请|申报', text)):
            scope = _scope(text)
            if '姓名' in text and '学号' in text:
                scope = scope.model_copy(update={'audience_groups': ()})
            elif not re.search(r'面向|仅限|对象|适用于', text):
                scope = scope.model_copy(update={'audience_groups': tuple(
                    group for group in scope.audience_groups if group.audience or group.class_name)})
            yield SimpleStatusLabel(value=value, scope=scope, evidence=evidence)


def _date_conflicts(dates):
    groups = defaultdict(list)
    for index, label in enumerate(dates):
        value = label.value
        if label.code in ('registration', 'application', 'submission', 'objection') and value.end and (
                value.end.kind != 'pending'):
            groups[label.code, label.scope, value.start].append(index)
    for indices in groups.values():
        if len({dates[index].value.end for index in indices}) > 1:
            for index in indices:
                label = dates[index]
                dates[index] = label.model_copy(update={'value': label.value.model_copy(update={'state': 'conflicting'})})


def _deduplicate(labels):
    merged = {}
    for label in labels:
        key = label.kind, label.code, label.scope, label.value
        prior = merged.get(key)
        merged[key] = label if prior is None else prior.model_copy(update={'evidence': _refs(prior.evidence, label.evidence)})
    return tuple(merged.values())


def _source_gaps(document, primary):
    gaps = [RuleGap(code='document_gap', detail=gap) for gap in document.gaps]
    if document.body_status != 'full' or (not primary and not any(
        segment.kind == 'body' or segment.asset_id in document.primary_asset_ids for segment in document.segments[1:]
    )):
        gaps.append(RuleGap(code='body_incomplete', detail=f'正文状态：{document.body_status}'))
    read_assets = {(segment.asset_id, segment.asset_hash) for segment in document.segments if segment.kind == 'attachment'}
    for asset in document.assets:
        if (asset.asset_id, asset.asset_hash) not in read_assets:
            gaps.append(RuleGap(code='attachment_unread', detail=asset.asset_id))
    return gaps


def _merge_policy_endpoints(dates):
    merged = []
    for label in dates:
        if label.code == 'policy_validity' and merged:
            prior = merged[-1]
            left, right = prior.value, label.value
            same_subject = prior.evidence == label.evidence or re.match(
                r'^(?:有效期|有效至|长期有效|永久有效)', label.evidence[-1].quote
            )
            if (prior.code == label.code and prior.scope == label.scope and same_subject
                    and left.start and not left.end and left.state == 'announced' and not left.explicit_long_term
                    and not right.start and right.state == 'announced' and (right.end or right.explicit_long_term)):
                value = SimpleDateValue(start=left.start, end=right.end, explicit_long_term=right.explicit_long_term,
                                        state='conflicting' if endpoints_reversed(left.start, right.end) else 'announced')
                merged[-1] = prior.model_copy(update={'value': value, 'evidence': _refs(prior.evidence, label.evidence)})
                continue
        merged.append(label)
    return merged


def _collect_prose_dates(clauses, title, table_refs):
    dates = []
    previous = None
    active = None
    for clause in clauses:
        text = clause.text
        if any(ref in table_refs for ref in clause.evidence):
            previous, active = None, None
            continue
        if _is_time_heading(text):
            previous, active = None, clause
            continue
        current = clause
        if active and active.source_key == clause.source_key and not clause.section:
            current = replace(clause, section=active.text, heading_evidence=active.evidence[0])
        active = None
        if previous and previous.source_key == clause.source_key:
            clock_window = _CLOCK_ONLY_WINDOW.fullmatch(text)
            preceding = dates[-1] if dates else None
            if (preceding and preceding.code == 'event' and _TENTATIVE.search(text)
                    and re.match(r'^(?:具体)?(?:时间|日期)(?:暂定|拟定|初定)', text)
                    and previous.section == clause.section
                    and any(ref in previous.evidence for ref in preceding.evidence)):
                qualifier = _date_value(text, 'event')
                if qualifier and qualifier.start == preceding.value.start:
                    dates[-1] = preceding.model_copy(update={
                        'value': preceding.value.model_copy(update={'state': 'tentative'}),
                        'evidence': _refs(preceding.evidence, clause.evidence)})
                    previous = clause
                    continue
            if (clock_window and preceding and preceding.code == 'event'
                    and previous.section == clause.section and _is_time_heading(clause.section)
                    and any(ref in previous.evidence for ref in preceding.evidence)
                    and preceding.value.start and preceding.value.start.kind in ('absolute', 'month_day')):
                try:
                    start = type(preceding.value.start).model_validate(
                        preceding.value.start.model_dump() | {'time': clock_window[1].zfill(5)})
                    end = type(start).model_validate(start.model_dump() | {'time': clock_window[2].zfill(5)})
                    value = SimpleDateValue(start=start, end=end,
                                            state='conflicting' if endpoints_reversed(start, end) else preceding.value.state)
                except ValueError:
                    pass
                else:
                    dates.append(preceding.model_copy(update={
                        'value': value, 'evidence': _refs(preceding.evidence, clause.evidence)}))
                    previous = clause
                    continue
            if _REVISION.search(text) and _ORIGINAL.search(previous.text) and not _REVISION.search(previous.text):
                current = replace(clause, text=previous.text + ',' + text,
                                  evidence=_refs(previous.evidence, clause.evidence))
            elif (_PUBLICITY_REFERENCE.search(text) or _PUBLICITY_DAYS.search(previous.text)
                  and re.search(r'如(?:有|对.{0,12}有)?异议|如有异议', text)) and not _CALENDAR_HINT.search(text) and not _NEGATIVE_DATE.search(text):
                if dates and dates[-1].scope.phase in ('公示', '名单公布') and dates[-1].evidence[-1] in previous.evidence:
                    publicity = dates[-1]
                    dates.append(publicity.model_copy(update={
                        'code': 'objection', 'evidence': _refs(publicity.evidence, clause.evidence),
                    }))
                    previous = clause
                    continue
        dates.extend(_date_labels(current, title))
        previous = clause
    return _merge_policy_endpoints(dates)


def _resolve_calendar_context(document, dates):
    from .product_labels import AbsoluteEndpoint

    title_year, title_evidence = calendar_context(document)
    segments = {segment.id: segment for segment in document.segments}
    primary_sources = {('body', None)} | {('attachment', asset) for asset in document.primary_asset_ids}
    def sources(label):
        return {(segments[ref.segment_id].kind, segments[ref.segment_id].asset_id)
                for ref in label.evidence if segments[ref.segment_id].kind != 'title'}
    def same_stage_or_adjacent(candidate, label):
        # A result/objection publication is a continuation of the same notice's
        # event, even when the intervening sentence points to its result roster.
        if label.scope.phase in ('公示', '名单公布'):
            return True
        if candidate.scope.phase == label.scope.phase:
            return True
        for left in candidate.evidence:
            for right in label.evidence:
                if left.segment_id != right.segment_id or left.quote == right.quote:
                    continue
                text = segments[left.segment_id].text
                gap = text.find(right.quote) - (text.find(left.quote) + len(left.quote))
                if 0 <= gap <= 80:
                    between = text[text.find(left.quote) + len(left.quote):text.find(right.quote)]
                    if not re.search(r'[一二三四五六七八九十\d]+[、.]|附件', between):
                        return True
        return False
    resolved = []
    for label in dates:
        if any(re.search(r'下一(?:年|年度)|次年|明年|来年|翌年', ref.quote) for ref in label.evidence):
            resolved.append(label)
            continue
        source = sources(label)
        year, evidence = (title_year, title_evidence) if source & primary_sources else (None, ())
        if year is None:
            anchors = [(point.date, candidate.evidence) for candidate in dates
                       if candidate.code != 'policy_validity' and candidate.scope.action == label.scope.action
                       and candidate.scope.track == label.scope.track
                       and same_stage_or_adjacent(candidate, label)
                       and (not candidate.scope.audience_groups or not label.scope.audience_groups
                            or candidate.scope.audience_groups == label.scope.audience_groups)
                       and not any(re.search(r'往届|历届|往年|去年|上届|上一(?:年|年度)', ref.quote)
                                   for ref in candidate.evidence)
                       and sources(candidate) & source
                       for point in (candidate.value.start, candidate.value.end)
                       if point is not None and point.kind == 'absolute']
            if len({date[:4] for date, _ in anchors}) != 1:
                resolved.append(label)
                continue
            if any(point and point.kind == 'month_day' and point.month_day < min(date[5:] for date, _ in anchors)
                   for point in (label.value.start, label.value.end)):
                resolved.append(label)
                continue
            year, evidence = anchors[0][0][:4], _refs(*(refs for _, refs in anchors))
        value = label.value
        changes = {}
        for key in ('start', 'end'):
            endpoint = getattr(value, key)
            if endpoint is not None and endpoint.kind == 'month_day':
                try:
                    changes[key] = AbsoluteEndpoint(date=f'{year}-{endpoint.month_day}', time=endpoint.time)
                except ValueError:
                    continue  # e.g. a leap day incompatible with the explicit year
        if changes:
            updated = value.model_copy(update=changes)
            if endpoints_reversed(updated.start, updated.end) and value.end and value.end.kind == 'month_day':
                # A Dec→Jan window does not establish which year the end uses.
                # Keep its visible precision rather than invent a reversed date.
                updated = updated.model_copy(update={'end': value.end, 'state': 'unknown'})
            if updated.state == 'unknown' and all(
                point is None or point.kind not in ('pending', 'month_day')
                for point in (updated.start, updated.end)
            ):
                updated = updated.model_copy(update={'state': 'announced'})
            if endpoints_reversed(updated.start, updated.end):
                updated = updated.model_copy(update={'state': 'conflicting'})
            updated = SimpleDateValue.model_validate(updated.model_dump())
            label = label.model_copy(update={'value': updated, 'evidence': _refs(label.evidence, evidence)})
        resolved.append(label)
    return resolved


def _resolve_deadline_references(document, dates):
    """Resolve an explicit back-reference only when one same-source window fits."""
    segments = {s.id: s for s in document.segments}
    def source_keys(label):
        return {(segments[r.segment_id].kind, segments[r.segment_id].asset_id)
                for r in label.evidence if segments[r.segment_id].kind != 'title'}
    def submission_object(label):
        text = ' '.join(reading_text(ref.quote) for ref in label.evidence)
        # Resolve only a positively identified common object. Generic material
        # submissions may belong to independent applications in the same notice.
        if re.search(r'补助|补贴|资助|困难证明', text):
            return None
        objects = set()
        for match in re.finditer(r'([\u3400-\u9fff]{0,14})(作品|论文|材料)', text):
            qualifier = re.split(r'提交|发送|递交|报送|附上', match[1])[-1]
            qualifier = re.sub(r'^(?:将|把)?(?:所有|全部)?', '', qualifier)
            qualifier = re.sub(r'初审|初赛|复赛|决赛|参赛', '', qualifier)
            if qualifier:
                objects.add(qualifier + match[2])
            elif match[2] == '作品' or '参赛' in match[1]:
                objects.add('competition_work')
        return next(iter(objects)) if len(objects) == 1 else None
    resolved = set()
    for index, pointer in enumerate(dates):
        points = [v for v in (pointer.value.start, pointer.value.end) if v]
        text = ' '.join(reading_text(ref.quote) for ref in pointer.evidence)
        if (pointer.code != 'submission' or submission_object(pointer) is None
                or not points or any(p.kind != 'pending' or p.reason != 'unresolved' for p in points)
                or not re.search(r'(?:上述|规定的?|提交)?截止时间(?:之)?前', text)
                or _CALENDAR_HINT.search(text) or _PENDING.search(text)):
            continue
        candidates = [other for other, target in enumerate(dates)
                      if other != index and target.code == pointer.code
                      and target.value.end and target.value.end.kind in ('absolute', 'month_day')
                      and source_keys(target) & source_keys(pointer)
                      and submission_object(target) == submission_object(pointer)
                      and _same_pointer_scope(pointer.scope, target.scope)]
        if len(candidates) == 1:
            target = dates[candidates[0]]
            dates[candidates[0]] = target.model_copy(update={'evidence': _refs(target.evidence, pointer.evidence)})
            resolved.add(index)
    return [date for i, date in enumerate(dates) if i not in resolved]


def _resolve_schedule_pointers(document, dates):
    """Cite a uniquely matching readable schedule instead of a pending pointer."""
    from .simple_attachment_binding import audience_covered, bind_numbered_attachment, compatible_audience

    segments = {segment.id: segment for segment in document.segments}
    read = {(segment.asset_id, segment.asset_hash) for segment in document.segments}
    if any((asset.asset_id, asset.asset_hash) not in read for asset in document.assets):
        return dates
    supplemental = {asset.asset_id for asset in document.assets} - set(document.primary_asset_ids)
    schedules = defaultdict(lambda: defaultdict(list))
    for index, date in enumerate(dates):
        endpoints = tuple(endpoint for endpoint in (date.value.start, date.value.end) if endpoint)
        if not endpoints or any(endpoint.kind == 'pending' for endpoint in endpoints):
            continue
        sources = {segments[ref.segment_id].asset_id for ref in date.evidence} & supplemental
        if len(sources) == 1:
            schedules[date.code][next(iter(sources))].append(index)
    resolved = set()
    for index, date in enumerate(dates):
        value = date.value
        endpoints = tuple(endpoint for endpoint in (value.start, value.end) if endpoint)
        if value.state != 'unknown' or not endpoints or any(
            not isinstance(endpoint, PendingEndpoint) or endpoint.reason != 'unresolved' for endpoint in endpoints
        ):
            continue
        quotes = tuple(reading_text(ref.quote) for ref in date.evidence)
        if (not any(_SCHEDULE_POINTER.search(quote) for quote in quotes)
                or any(_CALENDAR_HINT.search(quote) for quote in quotes)
                or any(segments[ref.segment_id].asset_id in supplemental for ref in date.evidence)):
            continue
        pointer_refs = tuple(ref for ref in date.evidence if _SCHEDULE_POINTER.search(reading_text(ref.quote)))
        numbered, source, proof = bind_numbered_attachment(document, pointer_refs)
        matching = {}
        if numbered:
            if source is None:
                continue
            compatible = [other for other in schedules[date.code].get(source, ()) if all(
                getattr(date.scope, field) in (None, getattr(dates[other].scope, field))
                for field in ('action', 'track', 'phase')
            ) and compatible_audience(date.scope, dates[other].scope)]
            if compatible and audience_covered(date.scope, [dates[other].scope for other in compatible]):
                matching[source] = compatible
        else:
            for source, indices in schedules[date.code].items():
                compatible = [other for other in indices if _same_pointer_scope(date.scope, dates[other].scope)]
                if compatible:
                    matching[source] = compatible
        if len(matching) != 1:
            continue
        for other in next(iter(matching.values())):
            target = dates[other]
            dates[other] = target.model_copy(update={'evidence': _refs(target.evidence, date.evidence, proof)})
        resolved.add(index)
    return [date for index, date in enumerate(dates) if index not in resolved]


def _same_pointer_scope(pointer, schedule):
    if any(getattr(pointer, field) not in (None, getattr(schedule, field)) for field in ('action', 'track', 'phase')):
        return False
    # A document-wide cohort can constrain a schedule whose rows add colleges
    # and classes. Each explicit qualifier in the pointer must have a match.
    qualifiers = ('audience', 'campus', 'college', 'class_name')
    return all(any(
        all(getattr(group, field) in (None, getattr(row, field)) for field in qualifiers)
        for row in schedule.audience_groups
    ) for group in pointer.audience_groups)


def _shared_audience(label, audiences, *, table=False):
    if not audiences:
        return label
    local = label.scope.audience_groups
    if local and not table:
        return label
    if not local:
        merged = [(audience.value, audience.evidence) for audience in audiences]
    else:
        merged = []
        for group in local:
            candidates = [audience for audience in audiences if audience.value.audience and all(
                getattr(audience.value, field) in (None, getattr(group, field))
                for field in ('campus', 'college', 'class_name')
            )]
            if not group.audience and len(candidates) == 1:
                audience = candidates[0]
                merged.append((group.model_copy(update={'audience': audience.value.audience}), audience.evidence))
            else:
                merged.append((group, ()))
    scope = label.scope.model_copy(update={'audience_groups': tuple(dict.fromkeys(group for group, _ in merged))})
    return label.model_copy(update={'scope': scope, 'evidence': _refs(label.evidence, *(refs for _, refs in merged))})



def analyze_simple_rules(document: DocumentBundle) -> SimpleRuleResult:
    """Extract the current product vocabulary from a versioned public document."""
    document = primary_view(document)
    primary, extras = _prose(document)
    title = reading_text(document.title)
    title_evidence = (RuleEvidence(segment_id=document.segments[0].id, quote=document.title),)
    # Retain the historical primary-body classification precedence while there
    # is a readable HTML body. Supplemental schedules are not new notices.
    body = tuple(clause.text for clause in primary if clause.source_key[0] == 'body') or tuple(
        clause.text for clause in primary
    )
    category = classify_simple_notice(title, body)
    gaps = _source_gaps(document, primary)
    labels: list[SimpleFact] = []
    if category == 'unknown':
        gaps.append(RuleGap(code='category_unknown', detail='主要事项缺少可判定线索'))
    if category != 'excluded':
        clauses = (*primary, *extras)
        table_dates, table_refs = _table_dates(document)
        dates = _collect_prose_dates(clauses, title, table_refs)
        title_clause = SourceClause(title, title_evidence)
        dates.extend(label for label in _date_labels(title_clause, title)
                     if label.value.state in ('ended', 'cancelled') or label.value.explicit_long_term)
        dates = _resolve_deadline_references(document, dates)
        audiences, shared = collect_audiences(primary, title, title_evidence, _audiences)
        audiences = _deduplicate(audiences)
        # Resolve years before unrelated audience evidence is appended to dates.
        dates = _resolve_calendar_context(document, dates)
        table_dates = _resolve_calendar_context(document, table_dates)
        dates = [_shared_audience(label, shared) if label.code != 'policy_validity' else label for label in dates]
        dates.extend(_shared_audience(label, shared, table=True) for label in table_dates)
        dates = _resolve_schedule_pointers(document, dates)
        _date_conflicts(dates)
        for label in dates:
            if label.value.state == 'conflicting':
                gaps.append(RuleGap(code='date_conflict', detail='同一适用范围出现冲突日期', evidence=label.evidence))
            elif label.value.state == 'unknown' or any(
                endpoint is not None and endpoint.kind in ('month_day', 'pending')
                for endpoint in (label.value.start, label.value.end)
            ):
                gaps.append(RuleGap(code='date_unresolved', detail='原文日期尚未确定或无法解析', evidence=label.evidence))
        labels.extend(dates)
        labels.extend(audiences)
        denied = _denied_title_codes(primary)
        labels.extend(_shared_audience(benefit, shared) for benefit in _benefits(title, title_evidence, title=True)
                      if benefit.code not in denied)
        labels.extend(_statuses(title, title_evidence))
        for clause in clauses:
            labels.extend(_shared_audience(benefit, shared) for benefit in _benefits(clause.text, clause.evidence))
            labels.extend(_statuses(clause.text, clause.evidence))
    return SimpleRuleResult(
        notice_id=document.notice_id, content_version=document.content_version, input_fingerprint=document.input_fingerprint,
        category=category, complete=not gaps, labels=_deduplicate(labels), gaps=tuple(dict.fromkeys(gaps)),
    )
