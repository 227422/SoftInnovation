"""Named student populations and notice-level audience declarations for v3.

A department can publish, host, or receive an application without restricting
who may apply.  Keep those roles separate from the population being addressed.
"""

import re

from .product_labels import AudienceGroup, ProductScope
from .simple_labels import SimpleAudienceLabel

_COHORT = r'(?:非?[0-9]{4}[级届]|[一二三四五]年级|大[一二三四五]|低年级|高年级)'
_MODIFIER = r'(?:全校|全体|全日制|本校|在校|在读|在籍|普通|所有|应届|优秀)'
_POPULATION = re.compile(
    rf'(?:{_MODIFIER})*(?:{_COHORT}(?:[、及和与]{_COHORT})*(?:{_MODIFIER})*)?'
    r'(?:本科(?:毕业生|学生|新生|生)|专科生|大学生|(?:硕士|博士)?研究生|硕士生|博士生|毕业生|新生)'
    rf'|(?:(?:[\u3400-\u9fff]{{2,18}}大学)?(?:全校|全体|在校|在读|所有)+学生)'
    rf'|{_COHORT}'
)
_GROUP_WORD = re.compile(
    r'(?P<college>[\u3400-\u9fff]{1,20}学院)|(?P<campus>[\u3400-\u9fff]{1,10}校区)'
    r'|(?P<major>[\u3400-\u9fffA-Za-z]{1,14}专业)(?!分流|介绍|通知)'
    r'|(?P<class_name>(?<![\dA-Za-z])[\u3400-\u9fffA-Za-z]{0,12}\d{2,8}(?!\d)班?|'
    r'[\u3400-\u9fffA-Za-z]{0,12}[一二三四五六七八九十]+班|[A-Za-z]{1,3}班)'
)
_NAMED_CLASS = re.compile(r'(?:\d{4}[级年届])?[\u3400-\u9fff]{2,14}班(?!级)')
_CONTACT = re.compile(
    r'(?:https?://|www\.)[^\s,，;；。<>]+|[A-Za-z\d_.+-]+@[A-Za-z\d.-]+\.[A-Za-z]{2,}'
    r'|(?:QQ(?:群)?|微信群|群号|电话|手机|学[工]?号|编号|序号|账号)\s*[:：]?\s*[A-Za-z\d+()-]+'
)
_CLASS_FIELD = re.compile(r'(?:专业|行政|教学)?班级\s*[:：]')
_ARRANGEMENT_SOURCE = re.compile(
    r'(?:以|按照|按|参照|依照)[\u3400-\u9fff]{1,20}(?:学院|校区)(?:的)?'
    r'(?:发布的|公布的|另行)?(?:通知|安排)[^,，;；。]{0,12}(?:为准|执行|办理)'
)
_LEADING = re.compile(
    r'.*(?:面向|仅限|适用于|开放给|对象(?:为|是|包括|:)?|欢迎|请|须由|只限|'
    r'须提交|须提供|须持|要求|具有|具备|涉及|通过|由|的|及|和|与|或|、)'
)
_CLASS_LEADING = re.compile(r'.*(?:进入|转入|录取|入围|招收|招募|举办|开展|关于|确定了|参加)')
_QUALIFIER_END = re.compile(
    r'中(?:的)?(?:成绩|满足|符合|获得|获奖)|成绩|排名|须提交|须提供|须携带|须持|必须|'
    r'(?:提交|报送|上报)(?:至|到|给)|(?:主办|承办|组织)(?:单位)?(?:为|是|:)|由.{0,20}(?:组织|主办|承办)|'
    r'(?:地点|地址)(?:为|是|:)|前往|(?:在|于)[^,，]{1,30}(?:学院|校区)[^,，]{0,16}(?:举行|举办|召开|进行)'
)
_REFERENTIAL_COLLEGE = re.compile(
    r'(?:通知)?(?:各|有关|相关|各相关|各有关|各二级|本|所在|原|现|转入|转出|拟转入|拟转出|'
    r'申请转入|接收|报考|申报|招生|主办|承办|指定|对应|可以跨|跨)学院'
)
_GROUP_SPLIT = re.compile(r'[,，;；、:：]|(?:及|与|和|或)(?=[\u3400-\u9fff]{1,10}学院)')
_NON_MAJOR = re.compile(r'^(?:鼓励)?跨|^(?:各|本|原|现|相关|所有|同一|某一|每一|其他|所在|所学|拟转入|拟转出)|'
                        r'转(?:换|入|出)?专业|辅修专业|微专业|主修专业|成绩专业|排名专业|学科专业|学科跨|指定专业|促进|培养')
_DECLARED = re.compile(
    r'面向|仅限|只限|对象(?:为|是|:|包括)|适用于|欢迎|招募|招收|'
    r'(?:参赛队)?队员(?:为|是|:)|(?:参赛|社团|团队)(?:成员|人员)(?:为|是|:)|'
    r'(?:报名|注册|参加|参与|招生)(?:人员|对象|范围)[:为是]|'
    r'为(?:全校|全体|本校|在校)?(?:本科生|研究生|学生)提供|'
    r'(?:学校确定了|拟同意|拟录取|录取).{0,50}(?:班|学生名单|本科生|研究生)'
)
_TARGET_SECTION = re.compile(r'对象|(?:报名|申请|招生|参赛|选拔)(?:范围|条件|类别|名额)|参赛要求')
_CONDITION_ONLY = re.compile(
    r'不得|不能|不可以|取消.{0,8}资格|须完成|须修满|人数|持股|排名|成绩|教师.{0,8}(?:指导|负责)|'
    r'招生单位|负责.{0,10}(?:审核|组织|接收)|入学前|鼓励跨|方可|才可|累计(?:达到|达|满)|学习时间累计'
)
_STUDENT_ACTION = re.compile(r'可(?:以)?(?:参加|报名|申请)|(?:本科|学院|专业|班|级)[^,，;；。]{0,12}(?:报名|申请|参加)')
_ADMIN_SECTION = re.compile(r'工作机构|工作小组|领导小组|联系方式|组织机构|评审人员')
_GENERAL_PROCEDURE = re.compile(r'辅修|微专业|转专业')
_RECOMMENDATION = re.compile(r'推免|推荐.{0,14}免试|免试.{0,24}推荐')


def _parts(text):
    """Split independent groups, keeping a coordinated grade phrase intact."""
    populations = tuple(_POPULATION.finditer(text))
    start = 0
    for match in _GROUP_SPLIT.finditer(text):
        if any(item.start() < match.start() < item.end() for item in populations):
            continue
        yield text[start:match.start()]
        start = match.end()
    yield text[start:]


def _destination(part, match):
    before, after = part[max(0, match.start() - 18):match.start()], part[match.end():match.end() + 12]
    return bool(re.search(r'(?:攻读|报考|免试|推荐)[^,，。]{0,12}$', before)
                and '研究生' in match[0] or re.match(r'入学|招生(?:单位|专业|目录)', after))


def groups(text):
    """Return atomic named populations, excluding conditions and venue names."""
    # An exception narrows eligibility, not the main cohort being addressed.
    text = re.sub(r'[（(][^（）()]*除外[^（）()]*[）)]', '', text)
    text = re.sub(r'《[^》]*》', '', text)
    text = _CONTACT.sub(' ', text)
    # The department whose separate notice controls a schedule is a source,
    # while the campus/cohort before that reference can still be a real target.
    text = _ARRANGEMENT_SOURCE.sub(' ', text)
    text = re.split(r'(?:仅限|只可|允许)?转入以下指定专业', text, maxsplit=1)[0]
    class_field = bool(_CLASS_FIELD.search(text))
    result = []
    for raw in _parts(text):
        part = _QUALIFIER_END.split(raw, maxsplit=1)[0]
        if re.match(r'(?:除|排除)(?:\d|本科|研究生|全体|[\u3400-\u9fff]{1,10}学院)', part):
            continue
        class_matches = list(_NAMED_CLASS.finditer(part))
        populations = [m for m in _POPULATION.finditer(part) if not _destination(part, m)
                       and not re.search(r'(?:非|排除)$', part[:m.start()])
                       and not any(c.start() <= m.start() < c.end() for c in class_matches)]
        fields = {}
        for match in _GROUP_WORD.finditer(part):
            name, field = _LEADING.sub('', match[0]).strip(), match.lastgroup
            if not name or re.fullmatch(r'(?:各|有关|相关|本|所有|指定|以下|拟转入)?(?:学院|校区|专业|班)', name):
                continue
            if field in ('college', 'campus'):
                tail = part[match.end():]
                if (_REFERENTIAL_COLLEGE.fullmatch(name)
                        or name == '技师学院'
                        or re.search(r'(?:主修|辅修|所在|相关|有关|其他|其它|转入|转出|接收)学院$', name)
                        or re.match(r'(?:的)?(?:官方)?(?:网站|网页|平台|办公室|教务办|负责|组织|审核|教师|主办|承办)', tail)
                        or re.search(r'(?:在|于|到|至)[^,，]{0,18}$', part[:match.start()])
                        or re.search(r'(?:在|于|到|至|向)[\u3400-\u9fff]*学院$', name)):
                    continue
                if field == 'college':
                    name = re.sub(r'^.*大学', '', name)
            if field == 'class_name' and (
                not re.search(r'班|[A-Za-z\u3400-\u9fff]\d{3,8}', name)
                or ('班' not in name and not (class_field or re.match(r'(?:学生|同学)', part[match.end():])))
                or re.search(r'机房|报告厅|教室|教学楼|南楼|北楼|东楼|西楼|楼|层|室', name)
                or re.search(r'[年月日级届]|成绩|学分|分钟|截止|期至|时长|设立', part[match.end():match.end() + 3])
                or any(match.start() < item.end() and item.start() < match.end() for item in populations)
            ):
                continue
            if field == 'major':
                if _NON_MAJOR.search(name):
                    continue
                field = 'audience'
            fields.setdefault(field, []).append(name)
        for match in class_matches:
            name = _CLASS_LEADING.sub('', match[0])
            if len(name) > 2 and not re.search(r'上班|下班|值班|全班|本班|各班|每班', name):
                fields.setdefault('class_name', []).append(name)
        audience = [m[0].strip().replace('优秀', '') for m in populations]
        majors = fields.pop('audience', [])
        if majors:
            audience = [major + member for major in majors for member in audience or ('',)]
        if not (audience or fields):
            continue
        colleges, campuses, classes = (list(dict.fromkeys(fields.get(field, [None])))
                                       for field in ('college', 'campus', 'class_name'))
        if sum(len(values) > 1 for values in (audience, colleges, campuses, classes)) > 1:
            continue  # Do not turn two unrelated lists into a Cartesian product.
        result.extend(AudienceGroup(audience=member, college=college, campus=campus, class_name=class_name)
                      for member in audience or (None,) for college in colleges
                      for campus in campuses for class_name in classes)
    return tuple(dict.fromkeys(result))


def declared(text, context=''):
    return bool(_DECLARED.search(text) or _TARGET_SECTION.search(context)
                and not _CONDITION_ONLY.search(text))


def target_groups(text, *, context='', title=False, date=False):
    if not title and _ADMIN_SECTION.search(context):
        return ()
    text = re.sub(r'《[^》]*》', '', text)
    explicit = _DECLARED.search(text)
    if not (title or date or declared(text, context) or _STUDENT_ACTION.search(text)):
        return ()
    if not explicit and not title and _CONDITION_ONLY.search(text):
        return ()
    # Addressees and the agencies processing an application are not applicants.
    if re.match(r'^(?:各|有关|相关)(?:学院|单位|部门)', text):
        return ()
    return groups(text)


def _global_label(group, evidence):
    return SimpleAudienceLabel(value=group, scope=ProductScope(), evidence=evidence)


def _recommendation_audience(primary, title, title_evidence):
    if not _RECOMMENDATION.search(title):
        return []
    # The degree being applied for is a destination. The source cohort is an
    # explicitly stated undergraduate cohort in the current notice's purpose.
    matches = [(clause, re.search(r'(\d{4}届)(?:优秀|应届)*本科(?:毕业生|生)', clause.text))
               for clause in primary if re.search(r'为(?:切实)?(?:做好|做实)|面向|推荐对象', clause.text)]
    match = next(((clause, m) for clause, m in matches if m), None)
    if not match:
        return []
    clause, cohort = match
    college = next((g.college for g in groups(title) if g.college), None)
    entry = re.search(r'[（(](\d{4}级)[）)]', title)
    member = f'{cohort[1]}（{entry[1]}）本科生' if entry else f'{cohort[1]}本科毕业生'
    refs = tuple(dict.fromkeys((*clause.evidence, *title_evidence)))
    return [_global_label(AudienceGroup(audience=member, college=college), refs)]


def _current_scope(label, text, context):
    """An earlier selection stage or cited notice does not scope today's cohort."""
    current = re.sub(r'《[^》]*》', '', text)
    scope = label.scope
    phase = scope.phase
    if phase and not any(re.match(rf'^(?:[一二三四五六七八九十\d]+[、.])?{re.escape(phase)}(?:$|[:：]|对象|阶段|面向)', part)
                         for part in (current, context)):
        phase = None
    action = scope.action if scope.action and scope.action in current else None
    return label.model_copy(update={'scope': scope.model_copy(update={'phase': phase, 'action': action})})


def _title_cohort(label, title, title_evidence):
    # Refine a generic body degree only. The title's publishing college is not
    # evidence that the body cohort is restricted to that college.
    member = label.value.audience
    if member not in ('本科生', '本科学生', '研究生', '硕士研究生', '博士研究生', '专科生'):
        return label
    candidates = {g.audience for g in groups(title) if g.audience and re.search(_COHORT, g.audience)
                  and g.audience.endswith(member)}
    if len(candidates) != 1:
        return label
    return label.model_copy(update={
        'value': label.value.model_copy(update={'audience': next(iter(candidates))}),
        'evidence': tuple(dict.fromkeys((*label.evidence, *title_evidence))),
    })


def _distinct_stage_labels(audiences):
    by_phase = {}
    for label in audiences:
        if label.scope.phase:
            by_phase.setdefault(label.scope.phase, set()).add(label.value)
    if len(by_phase) > 1 and len({frozenset(values) for values in by_phase.values()}) > 1:
        return audiences
    return [label.model_copy(update={'scope': label.scope.model_copy(update={'phase': None})})
            for label in audiences]


def collect_audiences(primary, title, title_evidence, factory):
    """Prefer main-body targets; use title or cited degree only as fallbacks."""
    records = []
    for clause in primary:
        local = tuple(factory(clause.text, clause.evidence, context=clause.section))
        for label in local:
            label = _title_cohort(_current_scope(label, clause.text, clause.section), title, title_evidence)
            records.append((label, declared(clause.text, clause.section), bool(_TARGET_SECTION.search(clause.section))))
    explicit_degrees = [label.value.audience for label, _, section in records if section and label.value.audience]
    audiences, shared = [], []
    for label, is_declared, section in records:
        member = label.value.audience
        # A named object section narrows overview prose such as "all undergraduates
        # must take the exam"; prerequisite learning hours are not a new cohort.
        broad = re.sub(rf'^(?:{_MODIFIER})+', '', member or '')
        if not is_declared and not section and broad in ('本科生', '本科学生', '研究生', '学生') and any(
                name != member and name.endswith(broad) for name in explicit_degrees):
            continue
        audiences.append(label)
        if is_declared and not (label.scope.phase or label.scope.track or label.scope.action):
            shared.append(label)
    recommendation = _recommendation_audience(primary, title, title_evidence)
    if recommendation:
        return recommendation, recommendation
    if not audiences and _GENERAL_PROCEDURE.search(title):
        # A cited selection policy can establish the degree without making its
        # owning department a restriction on minor/transfer applicants.
        for clause in primary:
            if '《' not in clause.text:
                continue
            for name in re.findall(r'《([^》]+)》', clause.text):
                if not _GENERAL_PROCEDURE.search(name):
                    continue
                for group in groups(name):
                    if group.audience and re.search(r'本科|专科|研究生', group.audience):
                        audiences.append(_global_label(AudienceGroup(audience=group.audience), clause.evidence))
        shared.extend(audiences)
    if not audiences:
        shared = list(factory(title, title_evidence, title=True))
        audiences.extend(shared)
    return _distinct_stage_labels(audiences), shared
