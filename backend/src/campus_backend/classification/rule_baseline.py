"""Deterministic public-notice rules with local, citable evidence."""

import re
from datetime import date, time

from campus_backend.documents.models import DocumentBundle
from campus_backend.classification.rule_labels import (
    BenefitLabel, BenefitValue, Category, ConditionLabel, ConditionValue,
    DateLabel, DateValue, Label, RuleBaselineResult, RuleEvidence, RuleGap,
    RuleScope, StatusLabel,
)

RULES_VERSION = '1.6.0'

_AID = re.compile(
    r'奖学金|助学金|助学贷款|困难(?:学生)?认定|困难补助|勤工助学|勤助工资|奖助|奖励金|'
    r'评优|评先评优|先进个人评选|优秀学生(?:评选|干部)|优秀毕业生'
)
_RESEARCH = re.compile(r'竞赛|比赛|大赛|赛事|科研|创新训练|创新创业项目|大创项目|科创(?:班|项目|培养)|创新人才项目')
_DAILY = re.compile(
    r'招聘会|毕业生.*招聘|校园招聘|实习|就业|推免|夏令营|交换生|访学|选课|退课|考试|'
    r'缴费|宿舍|停水|停电|讲座|志愿者|志愿服务|招新|体测|补测|停课|调课|补考|'
    r'学籍|注册|转(?:换)?专业|专业分流|辅修|免试攻读|图像采集|征兵|学生活动|图书馆|校历|研学|'
    r'食堂|心理普测|微专业'
)
_NEWS = re.compile(r'成功举办|圆满(?:举行|落幕|闭幕|结束)|顺利举办|载誉归来|喜报|赛后回顾|活动回顾|工作纪实|来访交流|赴.*调研|大会顺利召开|活动总结')
_NONSTUDENT = re.compile(
    r'采购公告|中标公告|招标公告|教师招聘|招聘教师|招聘辅导员|行政人员招聘|'
    r'(?:工作人员|非事业编(?:制)?人员)\s*招聘|教学质量优秀奖|优秀教师.{0,12}奖励|'
    r'大学生.*导师征集|学生信息导入工作'
)
_GRADUATE_TOPIC = re.compile(
    r'研究生(?:拔尖)?(?:创新(?:创业)?人才项目|奖学金|奖(?=的通知|评选|公示)|课程)'
)
_ADMISSIONS = re.compile(r'(?:研究生|博士生|硕士生)(?:招生|入学)|考研')
_GRADUATE_AWARD = re.compile(r'(?:MBA|EMBA|MPA|MEM|专业硕士)\s*新生.{0,12}(?:奖学金|助学金)', re.I)
_HARD_QUALIFICATION = re.compile(
    r'(?:申请人|申报人|申请者|申报者|参会者).{0,12}(?:须|必须|应当)(?:具有|具备)'
    r'(?:博士学位|[^。；]{0,16}职称)|具有博士学位(?:或[^。；]{0,24}职称)?的科研人员.{0,8}可申报'
)
_YOUNG_RESEARCHER = re.compile(r'青年学者.{0,12}在读博士研究生.{0,24}(?:博士后|青年教师)')
_VENUE_GUIDE = re.compile(r'(?:活动场地|租赁设备).{0,18}(?:审批|办理|预约)(?:指南|流程|须知)')
_PROFILE = re.compile(r'(?:团委|组织|机构|场地|活动中心).{0,12}(?:介绍|概况)\s*$')
_FORUM = re.compile(r'学术论坛|博士论坛')
_FORUM_INVITATION = re.compile(r'举办|预告|报名|征稿|欢迎.{0,12}(?:参加|参会)|定于.{0,32}(?:召开|举行)')
_FOLLOWUP_ACTION = re.compile(
    r'报名(?:现已|即将|仍|继续)开放|(?:欢迎|请|可).{0,10}(?:报名|提出异议|提出申诉|申请使用|预约场地)'
    r'|(?:报名|申诉|异议|复核).{0,12}(?:截止|截至)|(?:报名|申诉|异议|复核)入口|可.{0,28}前提出(?:异议|申诉)'
)
_EXCLUSIVE = re.compile(r'(?:仅限|只限|仅面向|只面向|仅接受|只招收)(?:本校|在校|全日制|在读)*(?:硕士|博士|研究生|教师|教职工|行政人员)(?!院|处)')
_LOCAL_RESTRICTION = re.compile(r'第[一二三四五六七八九十0-9]+(?:批|阶段|轮|组)|(?:初赛|复赛|决赛)')
_BENEFICIARY = re.compile(r'为.*(?:服务|提供|辅导)|面向.*(?:提供|服务|帮扶|辅导)')
_UNDERGRAD = re.compile(r'本科(?:生|毕业生|学生)')
_AUDIENCE = re.compile(
    r'(?:[0-9]{4}(?:级|届))?(?:本科(?:毕业生|学生|生)|硕士研究生|博士研究生|研究生|'
    r'全体学生|在校学生|毕业生|新生|参赛者)(?:(?:和|与|及|、|或)(?:本科生|研究生))?'
)
_TRACK = re.compile(r'[A-Za-z0-9]+(?:赛道|组)|(?:本科生|研究生|创新|创业实践|创业|创意|普通|专项|主)(?:赛道|组)')
_DEPARTMENT = re.compile(r'(?:各|有关)?(?:学院|学校|辅导员|单位|部门|院系|研究生院|教务处)')
_CLAUSES = re.compile(r'[^。；;！？!?\n，,]+')
_DATE_TEXT = (
    r'(?P<year>[0-9]{4})\s*(?:年|[-/.])\s*(?P<month>[0-9]{1,2})'
    r'\s*(?:月|[-/.])\s*(?P<day>[0-9]{1,2})(?:日|号)?'
)
_CLOCK_TEXT = r'(?:\s*(?P<period>上午|下午|晚上|中午)?\s*(?P<hour>[0-9]{1,2})(?:(?:[:：](?P<minute>[0-9]{2}))|[时点](?:(?P<zh_minute>[0-9]{1,2})分?)?))?'
_DATE = re.compile(r'(?<![0-9])' + _DATE_TEXT + _CLOCK_TEXT + r'(?![0-9])')
_PROVISIONAL_DATE = re.compile(r'暂定|拟定|初定|待定|另行通知|尚未确定')
_ORIGINAL_DATE = re.compile(r'原(?:为|定(?:为|于)?|先为)')
_EXTENSION_DATE = re.compile(r'(?:现)?(?:延长|延后|延期|推迟|顺延|改|调整)至')
_DATE_HINT = re.compile(r'[0-9]{1,2}月[0-9]{1,2}[日号]|[0-9]{4}年')
_DEADLINE = re.compile(r'截止(?:时间|日期)?|截至|之前|(?:日|号|分)前|最迟|有效期|起止|公示时间')
_DATE_ACTIONS = (
    ('internal_reporting_deadline', re.compile(r'报送|汇总上报')),
    ('objection_deadline', re.compile(r'申诉|异议|复核')),
    ('registration_deadline', re.compile(r'报名|参赛登记')),
    ('application_deadline', re.compile(r'申请|申报')),
    ('submission_deadline', re.compile(r'提交|递交|补交')),
    ('publicity_end', re.compile(r'公示')),
    ('policy_expiry', re.compile(r'有效期|有效至')),
    ('event_start', re.compile(r'开始时间|开始日期|开始于|举行|开赛')),
    ('event_end', re.compile(r'结束时间|结束日期|结束于|比赛结束|完赛')),
)
_ACTION_TEXT = re.compile(r'报名|申请|申报|提交|参赛|参加|报送|登记|复核|反馈')
_BENEFIT = re.compile(
    r'(?P<volunteer_hours>志愿(?:服务)?(?:时长|工时))|(?P<innovation_credit>创新(?:创业|实践)?学分)|'
    r'(?P<course_credit>课程学分|实践学分|学分)|(?P<sports_points>体育(?:分|积分))|'
    r'(?P<recommendation_points>推免加分|保研加分)|(?P<comprehensive_points>综测(?:加分|积分)|综合测评(?:加分|积分))|'
    r'(?P<second_classroom_points>第二课堂(?:积分|分数|学分)?)|'
    r'(?P<financial_award>奖金|奖励金|奖学金|补助金|补贴)|(?P<certificate>(?:获奖|荣誉|参与)?证书)'
)
_GRANT = re.compile(r'可(?:获得|获|计入|计|认定|加|领取|兑换)|予以认定|认定为|获得|发放|授予|给予|颁发|计入|奖励为')
_NEGATION = re.compile(r'不(?:予|得|计|认|加|获|发|颁|享|提供|折算)|不能|不可|无(?:额外|任何)?|尚未|待定|未明确')
_REQUIREMENT = re.compile(r'(?P<text>[^。；;，,]{1,60}?(?:后|者|时))\s*(?:方(?:可|能)|才(?:可|能)|可)')
_ONLY_IF = re.compile(r'只有(?P<text>[^，,。；;]{1,60}?)才(?:会|能|可)?(?:获|颁发|认定|计入|授予|给予|发放)')
_APPROVAL_IF = re.compile(r'(?P<text>(?:通过审核|审核通过|经审核合格))\s*可')
_STATUS_DISPUTED = re.compile(r'不是|并非|并未|并不|不再|不实|否认|质疑|待核实|所谓|[“”「」『』]')
_NUMBER = r'[0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十百千]+'
_QUANTITY = re.compile(rf'(?P<number>{_NUMBER})\s*(?P<unit>小时|学分|分|万元|元)')
_SIMPLE_TITLE = re.compile(r'[^与及和、：:；;。！？]+?(?P<action>报名|申请|提交)通知')
_SAME_CLAUSE_RANGE = re.compile(r'^\s*(?:至|到|或|~|～|—|-)[\s0-9一二三四五六七八九十]')
_ROUTINE_CLOSING = re.compile(r'特此通知|(?:如|若)有疑问请咨询主办方')
_SIMPLE_BENEFIT = re.compile(
    r'(?P<condition>完成签到后|签到后|通过审核)可(?:获得|获)'
    rf'(?P<benefit>{_BENEFIT.pattern})\s*(?:{_NUMBER})\s*(?:小时|学分|分|万元|元)'
)

_WINDOW_ACTIONS = {
    '报名': ('registration_start', 'registration_deadline'),
    '申请': ('application_start', 'application_deadline'),
    '申报': ('application_start', 'application_deadline'),
    '提交': ('submission_start', 'submission_deadline'),
    '活动': ('event_start', 'event_end'),
    '比赛': ('event_start', 'event_end'),
}
_WINDOW_PREFIX = re.compile(r'(?P<action>报名|申请|申报|提交|活动|比赛)(?:时间|日期|期间)\s*(?:为|是|[:：])?\s*$')
_WINDOW_LINK = re.compile(r'\s*(?:至|到|—|–|~|～)\s*')
_SUFFIX_REQUIREMENT = re.compile(r'[（(]((?:仅限|适用于|面向)[^）)]+)[）)]')
_SUSPECT_CONDITION = re.compile(r'仅限|条件|获奖|合格|完成|通过|符合|以.*为准|按.*认定')
_SIMPLE_DEADLINE = re.compile(
    rf'{_AUDIENCE.pattern}\s*(?:报名|申请|提交)(?:截止(?:时间|日期)?\s*(?:至|为|[:：])?)\s*{_DATE.pattern}'
)


def _category(title: str, body: tuple[str, ...]) -> Category:
    exclusive = any(
        _EXCLUSIVE.search(text) and not _UNDERGRAD.search(text) and not _TRACK.search(text)
        and not _BENEFICIARY.search(text) and not _LOCAL_RESTRICTION.search(text)
        for text in (title, *body)
    )
    undergraduate_opportunity = any(
        re.search(r'本科(?:生|毕业生|学生).{0,12}(?:可|也|报名|申请|参加)', text)
        for text in (title, *body)
    )
    title_excludes_undergrad = bool(
        _GRADUATE_TOPIC.search(title) and not _UNDERGRAD.search(title)
        and not re.search(r'推免|免试攻读', title)
    )
    admissions = bool(_ADMISSIONS.search(title))
    hard_requirements = [clause for clause in body if _HARD_QUALIFICATION.search(clause)]
    # A named exception must be accounted for before the main rule can exclude the whole notice.
    hard_exclusion = bool(
        hard_requirements and not admissions and (
            all('除外' not in clause and '例外' not in clause for clause in hard_requirements)
            or any(_YOUNG_RESEARCHER.search(clause) for clause in body)
        )
    )
    if (
        ((exclusive or title_excludes_undergrad or hard_exclusion or _GRADUATE_AWARD.search(title))
         and not undergraduate_opportunity) or _NONSTUDENT.search(title)
    ):
        return 'excluded'
    has_followup = any(_FOLLOWUP_ACTION.search(text) for text in (title, *body))
    if (_NEWS.search(title) or _PROFILE.search(title)) and not has_followup:
        return 'excluded'
    if _AID.search(title):
        return 'financial_aid'
    if _RESEARCH.search(title) and not re.search(r'讲座|培训|经验分享', title):
        return 'research_innovation'
    forum_invitation = _FORUM.search(title) and any(
        _FORUM_INVITATION.search(text) for text in (title, *body)
    )
    if admissions or _VENUE_GUIDE.search(title) or forum_invitation or (
        _PROFILE.search(title) and has_followup
    ) or _DAILY.search(title) or re.search(r'培训|经验分享', title):
        return 'daily'
    return 'unknown'


def _scope(clause: str, action: str | None = None) -> RuleScope:
    audience = _AUDIENCE.search(clause)
    track = _TRACK.search(clause)
    return RuleScope(action=action, track=track.group() if track else None,
                     audience=audience.group() if audience else None)


def _date_value(match: re.Match[str]) -> DateValue:
    calendar = date(*(int(match[key]) for key in ('year', 'month', 'day')))
    clock = None
    if match['hour'] is not None:
        hour = int(match['hour'])
        if match['period'] in ('下午', '晚上', '中午') and 1 <= hour < 12:
            hour += 12
        minute = int(match['minute'] or match['zh_minute'] or '0')
        clock = time(hour, minute).isoformat(timespec='minutes')
    return DateValue(date=calendar.isoformat(), time=clock)


def _dates(clause: str, evidence: RuleEvidence) -> tuple[list[DateLabel], bool]:
    matches = list(_DATE.finditer(clause))
    if _PROVISIONAL_DATE.search(clause) and (_DATE_HINT.search(clause) or _DEADLINE.search(clause)):
        return [], True
    if len(matches) == 2:
        start, end = matches
        prefix = clause[:start.start()]
        window = _WINDOW_PREFIX.search(prefix)
        if window and _WINDOW_LINK.fullmatch(clause[start.end():end.start()]):
            if clause[end.end():].strip() or _NEGATION.search(prefix) or _DEPARTMENT.search(prefix):
                return [], True
            try:
                values = (_date_value(start), _date_value(end))
            except ValueError:
                return [], True
            if (values[0].date, values[0].time or '') > (values[1].date, values[1].time or ''):
                return [], True
            action = window['action']
            scope = _scope(prefix, action)
            return [DateLabel(code=code, value=value, scope=scope, evidence=(evidence,))
                    for code, value in zip(_WINDOW_ACTIONS[action], values)], False
    if len(matches) > 1 and any(
        _WINDOW_LINK.fullmatch(clause[first.end():second.start()]) for first, second in zip(matches, matches[1:])
    ):
        return [], True
    unresolved = bool((_DATE_HINT.search(clause) or _DEADLINE.search(clause)) and not matches)
    labels = []
    for index, match in enumerate(matches):
        before = clause[matches[index - 1].end() if index else 0:match.start()]
        after = clause[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(clause)]
        local = before + match[0] + after
        actions = [(hit.start(), code, hit.group()) for code, pattern in _DATE_ACTIONS
                   for hit in pattern.finditer(before)]
        if not actions and len(matches) == 1:
            actions = [(hit.start(), code, hit.group()) for code, pattern in _DATE_ACTIONS
                       for hit in pattern.finditer(after)]
        if not actions:
            unresolved |= bool(_DEADLINE.search(local) or len(matches) > 1)
            continue
        _, code, action = max(actions)
        if code.endswith('_deadline') and not _DEADLINE.search(local):
            unresolved = True
            continue
        if _DEPARTMENT.search(before) and code in ('submission_deadline', 'application_deadline'):
            code = 'internal_reporting_deadline'
        department_action = bool(_DEPARTMENT.match(before.strip()))
        if department_action and code == 'registration_deadline':
            unresolved = True
            continue
        if _NEGATION.search(before) or _SAME_CLAUSE_RANGE.match(after):
            unresolved = True
            continue
        try:
            value = _date_value(match)
        except ValueError:
            unresolved = True
            continue
        scope = _scope(local, action)
        department = _DEPARTMENT.search(before)
        if code == 'internal_reporting_deadline' and department:
            scope = RuleScope(action=action, track=scope.track, audience=department[0])
        labels.append(DateLabel(code=code, value=value, scope=scope, evidence=(evidence,)))
    return labels, unresolved


def _number(text: str) -> int | float:
    if text.isascii():
        return float(text) if '.' in text else int(text)
    digits = dict(zip('零〇一二两三四五六七八九', (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    units = {'十': 10, '百': 100, '千': 1000}
    if all(char in digits for char in text):
        return int(''.join(str(digits[char]) for char in text))
    total, digit = 0, None
    for char in text:
        if char in units:
            total += (1 if digit is None else digit) * units[char]
            digit = None
        else:
            digit = digits[char]
    return total + (digit or 0)


def _benefits(clause: str, evidence: RuleEvidence) -> tuple[list[Label], bool]:
    matches = list(_BENEFIT.finditer(clause))
    labels: list[Label] = []
    unresolved = False
    for index, match in enumerate(matches):
        before = clause[matches[index - 1].end() if index else 0:match.start()]
        after = clause[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(clause)]
        if _NEGATION.search(before) or _NEGATION.match(after.strip()) or re.search(r'不实|不成立|仅供参考', after):
            continue
        if not _GRANT.search(before) and not _GRANT.match(after.strip()):
            unresolved = True
            continue
        requirement = _ONLY_IF.search(before) or _APPROVAL_IF.search(before) or _REQUIREMENT.search(before)
        suffix_requirement = _SUFFIX_REQUIREMENT.search(after)
        condition = suffix_requirement[1] if suffix_requirement else None
        if requirement:
            condition = requirement['text'].strip()
            leading_track = _TRACK.match(condition)
            if leading_track:
                condition = condition[leading_track.end():].strip()
        if not condition and _SUSPECT_CONDITION.search(after):
            unresolved = True
            continue
        quantity = _QUANTITY.match(after.strip())
        amount = _number(quantity['number']) if quantity else None
        if amount is not None and not 0 < amount < float('inf'):
            unresolved = True
            continue
        if quantity and _SAME_CLAUSE_RANGE.match(after.strip()[quantity.end():]):
            unresolved = True
            continue
        if re.search(r'^(?:以|按)|另行|见附件|待审核|待认定', after.strip()):
            unresolved = True
            continue
        scope = _scope(before, _ACTION_TEXT.search(before)[0] if _ACTION_TEXT.search(before) else None)
        labels.append(BenefitLabel(
            code=match.lastgroup, scope=scope, evidence=(evidence,),
            value=BenefitValue(text=match[0], amount=amount,
                               unit=quantity['unit'] if quantity else None, condition=condition,
                               condition_status='stated' if condition else 'unknown'),
        ))
        if condition:
            labels.append(ConditionLabel(code='benefit_requirement', value=ConditionValue(text=condition),
                                         scope=scope, evidence=(evidence,)))
    return labels, unresolved


def _statuses(clause: str, evidence: RuleEvidence) -> list[StatusLabel]:
    phrases = {
        'result_publicity': r'名单公示|结果公示|公示名单',
        'event_ended': r'圆满落幕|圆满闭幕|(?:比赛|活动)(?:已经|已)结束',
        'policy_valid': r'^本(?:政策|办法|规定|通知|文件|细则|指南)(?:自发布之日起|目前|现|仍在)?(?:现行有效(?:范围内)?|长期有效)$',
        'policy_expired': r'^本(?:政策|办法|规定|通知|文件|细则|指南)(?:现|目前)?已(?:废止|失效)$',
    }
    return [StatusLabel(code='document_status', value=value, scope=_scope(clause), evidence=(evidence,))
            for value, pattern in phrases.items()
            if re.search(pattern, clause) and not _STATUS_DISPUTED.search(clause)]



def _resolve_extension(clause: str, original: DateLabel, evidence: RuleEvidence) -> DateLabel | None:
    extension = _EXTENSION_DATE.search(clause)
    match = _DATE.fullmatch(clause[extension.end():].strip()) if extension else None
    if not match or _PROVISIONAL_DATE.search(clause) or _NEGATION.search(clause):
        return None
    prefix = clause[:extension.start()]
    scope = _scope(prefix)
    if any((value is not None and value != getattr(original.scope, field))
           for field, value in (('track', scope.track), ('audience', scope.audience))):
        return None
    action = _ACTION_TEXT.search(prefix)
    if action and action[0] != original.scope.action:
        return None
    try:
        value = _date_value(match)
    except ValueError:
        return None
    if (value.date, value.time or '') <= (original.value.date, original.value.time or ''):
        return None
    return original.model_copy(update={'value': value, 'evidence': tuple(dict.fromkeys((*original.evidence, evidence)))})


def _date_conflicts(labels: list[Label]) -> list[RuleGap]:
    groups: dict[tuple[str, RuleScope], list[DateLabel]] = {}
    for label in labels:
        if isinstance(label, DateLabel):
            groups.setdefault((label.code, label.scope), []).append(label)
    return [
        RuleGap(code='date_conflict', detail='同一动作及范围存在不同日期或时刻',
                evidence=tuple(dict.fromkeys(ref for label in group for ref in label.evidence)))
        for group in groups.values()
        if len({label.value for label in group}) > 1
    ]



def _covered_benefit(clause: str, labels: list[Label]) -> bool:
    match = _SIMPLE_BENEFIT.fullmatch(clause)
    benefits = [label for label in labels if isinstance(label, BenefitLabel)]
    requirements = [label for label in labels if isinstance(label, ConditionLabel)]
    return bool(
        match and len(benefits) == len(requirements) == 1
        and benefits[0].value.condition_status == 'stated'
        and benefits[0].value.condition == requirements[0].value.text == match['condition']
        and benefits[0].value.text == match['benefit']
        and benefits[0].value.amount is not None
    )


def analyze_rules(document: DocumentBundle) -> RuleBaselineResult:
    """Extract supported local facts and report unexplained public input."""
    has_body = document.body_status in ('full', 'partial')
    segments = document.segments if has_body else document.segments[:1]
    verified_assets = {(asset.asset_id, asset.asset_hash) for asset in document.assets
                       if asset.asset_id in document.primary_asset_ids}
    html = tuple(seg for seg in segments if seg.kind == 'body')
    pdf = tuple(seg for seg in segments if seg.kind == 'attachment' and seg.page is not None
                and (seg.asset_id, seg.asset_hash) in verified_assets)
    primary_segments = html or pdf
    primary_ids = {seg.id for seg in primary_segments}
    body = tuple(part[0].strip() for seg in primary_segments
                 for part in _CLAUSES.finditer(seg.text) if part[0].strip())
    category = _category(document.title, body)
    gaps = [RuleGap(code='document_gap', detail=gap) for gap in document.gaps]
    if document.body_status != 'full' or not body:
        gaps.append(RuleGap(code='body_incomplete', detail=f'正文状态：{document.body_status}'))
    read_assets = {(seg.asset_id, seg.asset_hash) for seg in segments if seg.kind == 'attachment'}
    for asset in document.assets:
        if (asset.asset_id, asset.asset_hash) not in read_assets:
            gaps.append(RuleGap(code='attachment_unread', detail=asset.asset_id))
    if category == 'unknown':
        gaps.append(RuleGap(code='category_unknown', detail='主要事项缺少可判定线索'))
    labels: list[Label] = []
    simple_title = _SIMPLE_TITLE.fullmatch(document.title)
    covered_action = False
    uncovered: list[RuleEvidence] = []
    for seg in segments:
        prior_original = None
        original_gap_index = None
        for match in _CLAUSES.finditer(seg.text):
            clause = match[0].strip()
            if not clause:
                continue
            evidence = RuleEvidence(segment_id=seg.id, quote=clause)
            if seg.kind == 'title':
                labels.extend(_statuses(clause, evidence))
                continue
            dates, uncertain_date = _dates(clause, evidence)
            extension = _EXTENSION_DATE.search(clause)
            if extension:
                original = prior_original
                prefix = clause[:extension.start()]
                if _ORIGINAL_DATE.search(prefix):
                    historical, _ = _dates(prefix, evidence)
                    original = historical[0] if len(historical) == 1 and historical[0].code.endswith('_deadline') else None
                    change_text = clause[extension.start():]
                    original_gap_index = None
                else:
                    change_text = clause
                replacement = _resolve_extension(change_text, original, evidence) if original else None
                dates = [replacement] if replacement else []
                uncertain_date = replacement is None
                if replacement and original_gap_index is not None:
                    gaps.pop(original_gap_index)
            prior_original = None
            original_gap_index = None
            if _ORIGINAL_DATE.search(clause) and not extension:
                if len(dates) == 1 and dates[0].code.endswith('_deadline'):
                    prior_original = dates[0]
                    original_gap_index = len(gaps)
                dates = []
                uncertain_date = True
            benefits, uncertain_benefit = _benefits(clause, evidence)
            labels.extend(dates)
            labels.extend(benefits)
            labels.extend(_statuses(clause, evidence))
            is_simple = bool(len(dates) == 1 and _SIMPLE_DEADLINE.fullmatch(clause))
            is_covered_action = bool(
                is_simple and seg.id in primary_ids and simple_title
                and simple_title['action'] == dates[0].scope.action
            )
            covered_action |= is_covered_action
            if not (is_covered_action or (seg.id in primary_ids and (
                _ROUTINE_CLOSING.fullmatch(clause) or _covered_benefit(clause, benefits)
            ))):
                uncovered.append(evidence)
            if is_simple or (
                re.search(r'仅面向|仅限|可申请|可报名|可参加|申请对象|报名对象', clause)
                and not _BENEFICIARY.search(clause)
            ):
                labels.append(ConditionLabel(code='eligibility', value=ConditionValue(text=clause),
                                             scope=_scope(clause), evidence=(evidence,)))
            if uncertain_date:
                gaps.append(RuleGap(code='date_unresolved', detail='日期不完整或适用事项不明确', evidence=(evidence,)))
            if uncertain_benefit:
                gaps.append(RuleGap(code='benefit_unresolved', detail='收益承诺或归属条件不明确', evidence=(evidence,)))
    gaps.extend(_date_conflicts(labels))
    if not covered_action or uncovered:
        gaps.append(RuleGap(code='coverage_unconfirmed', detail='存在未确认覆盖的产品事实',
                            evidence=tuple(uncovered)))
    return RuleBaselineResult(
        rules_version=RULES_VERSION, notice_id=document.notice_id,
        content_version=document.content_version, input_fingerprint=document.input_fingerprint,
        category=category, complete=not gaps, labels=tuple(labels), gaps=tuple(gaps),
    )


def classify_notice(title: str, body: tuple[str, ...]) -> Category:
    """Classify public notice text independently of label extraction."""
    return _category(title, body)


def extract_local_scope(clause: str) -> RuleScope:
    """Read explicit audience and track markers within a single source clause."""
    return _scope(clause)


def extract_local_benefits(clause: str, evidence: RuleEvidence) -> tuple[list[Label], bool]:
    """Return direct local claims and whether recognition found an unresolved candidate."""
    return _benefits(clause, evidence)


def date_revision_role(clause: str) -> str | None:
    """Recognize historical-date and explicit revision markers in the same clause."""
    if _EXTENSION_DATE.search(clause):
        return 'revision'
    if _ORIGINAL_DATE.search(clause):
        return 'historical'
    return None
