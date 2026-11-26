"""Evidence-backed main-notice context; attachment conditions never flow upstream."""
from dataclasses import dataclass, replace
import re
import unicodedata

from .product_labels import AudienceGroup, ProductBenefitLabel, ProductScope, Requirement, WindowLabel
from .rule_labels import RuleEvidence, RuleGap

_HEADING = re.compile(r'^(?:[一二三四五六七八九十]+[、.．]|[0-9]+[.．、])\s*[^0-9。；;，,：:（）()《》]{1,20}$')
_HOURS = re.compile(r'^(?:\d+[.、])?(?:所有学生|学生)?在线学习(?:时间)?累计(?:达到|至少|不少于)(\d+(?:\.\d+)?)小时方可参加考试')
_SCORE = re.compile(r'(?:^|[，,:：])\s*(?:本次考试)?(?:合格分数(?:为|是)|考试成绩(?:至少|不低于))(\d+(?:\.\d+)?)分')
_OBJECTION = re.compile(r'(?:公示期间|公示期内).{0,20}(?:异议|申诉|复核)')
_DATE = re.compile(r'\d{1,4}\s*[年月日]')
_STUDENT_ACTION = re.compile(
    r'(?:欢迎|邀请)(?:全体|所有|在校)?(?:本科生|学生).{0,16}(?:投票|报名|体验|参加)|'
    r'(?:本科生|学生)(?:均|都)?可(?:以)?(?:申请)?(?:参与|参加|报名|体验|投票)|'
    r'请(?:本科生|学生)(?:报名|投票|参加|体验)'
)
_TEACHING = re.compile(r'(?:课程|金课).{0,12}评选|教材.{0,12}(?:奖励|建设)|教学项目.{0,12}(?:征集|申报)|实验教学.{0,8}项目')
_TEACHER_APPLICATION = re.compile(r'(?:教师|教职工|主讲教师)(?:申请|申报)|经(?:协议)?教师申请')
_UNIT_TEACHING = re.compile(r'(?:各单位|各学院).{0,16}(?:组织)?申报')
_SCHEDULE_REFERENCE = re.compile(r'安排.{0,10}(?:见|详见)附件|附件.{0,30}(?:考试|考场|图像采集).{0,20}安排')
_PHASE_LIMIT = re.compile(r'最后一场|末场|第[一二三四五六七八九十百\d]+场|指定场次')
_ISSUE_SIGNATURE = re.compile(
    r'(?:^|\n)(?:[ \t]*[\u3400-\u9fff]{2,32}(?:院|处|部|办公室|委员会|中心|大学)[ \t]*\n)+'
    r'[ \t]*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[ \t\r\n]*$'
)
_TIME_SECTION = re.compile(r'(?:考试|报名|申请|提交|活动|比赛|采集|拍摄)(?:时间|日期)(?:(?:和|及)地点)?\s*[:：]?$')
_CONTINUATION_BOUNDARY = re.compile(r'^(?:[一二三四五六七八九十\d]+[、.．]|[（(][一二三四五六七八九十\d]+[）)]|[①-⑳•\uf0d8]|附件|联系人|注意[:：])')
MAX_CONTINUED_CLAUSE_CHARS = 1200


def _without_issue_signature(text, active_section=''):
    match = _ISSUE_SIGNATURE.search(text)
    if match:
        headings = []
        for raw_line in text[:match.start()].splitlines():
            line = raw_line.strip()
            if re.match(r'^附件\s*(?:\d+\s*)?[:：.．、]', line):
                headings.append('')  # attachment titles cannot reopen a time section
            elif _HEADING.fullmatch(line) or _TIME_SECTION.search(line):
                headings.append(line)
        if _TIME_SECTION.search(headings[-1] if headings else active_section):
            return text
    if match and not re.search(r'请|须|必须|前往|参加|报名|截止|举办|举行|地点|时间', match[0]):
        return text[:match.start()]
    return text


def _population(text):
    roles = [role for role, pattern in (
        ('undergraduate', r'本科(?:生|学生)?'), ('graduate', r'研究生|硕士生|博士生'),
        ('staff', r'教师|教职工'),
    ) if re.search(pattern, text)]
    return roles[0] if len(roles) == 1 else 'mixed' if roles else None


def reading_text(text):
    """Join CJK soft wrapping without joining separate numeric/Latin tokens."""
    text = unicodedata.normalize('NFKC', text)
    text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff0-9])|(?<=[0-9])\s+(?=[\u3400-\u9fff])', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def parenthesis_balance(text):
    balance = 0
    for char in text:
        if char in '(（':
            balance += 1
        elif char in ')）':
            balance -= 1
            if balance < 0:
                return None
    return balance


@dataclass(frozen=True)
class SourceClause:
    text: str
    evidence: tuple[RuleEvidence, ...]
    section: str = ''
    heading_evidence: RuleEvidence | None = None
    source_key: tuple[str, str | None] | None = None
    audience_role: str | None = None
    root_section: str = ''
    root_heading_evidence: RuleEvidence | None = None


def primary_clauses(document):
    """Preserve raw citations while joining prose within explicit main segments."""
    clauses, section, heading_evidence, last_source = [], '', None, None
    parent_role, audience_role = None, None
    root_section, root_heading, chinese_root = '', None, False
    last_segments = {(segment.kind, segment.asset_id): segment.id for segment in document.segments[1:]
                     if segment.kind == 'body' or segment.asset_id in document.primary_asset_ids}
    for segment in document.segments[1:]:
        if segment.kind != 'body' and segment.asset_id not in document.primary_asset_ids:
            continue
        source = (segment.kind, segment.asset_id)
        if source != last_source:
            section, heading_evidence = '', None
            parent_role, audience_role = None, None
            root_section, root_heading, chinese_root = '', None, False
        last_source = source
        if '\t' in segment.text:
            continue  # tabular context is handled by the table parser
        text = _without_issue_signature(segment.text, section) if segment.id == last_segments[source] else segment.text
        blocks, start = [], 0
        for match in re.finditer(r'^.*$', text, re.M):
            line = match[0].strip()
            if _HEADING.fullmatch(line):
                if match.start() > start:
                    blocks.append((text[start:match.start()], section, heading_evidence, audience_role, root_section, root_heading))
                section = reading_text(line)
                heading_evidence = RuleEvidence(segment_id=segment.id, quote=line)
                is_chinese = bool(re.match(r'^[一二三四五六七八九十]+[、.．]', line))
                if is_chinese or not chinese_root:
                    parent_role = _population(section)
                    root_section, root_heading, chinese_root = section, heading_evidence, is_chinese
                audience_role = _population(section) or parent_role
                start = match.end()
        if start < len(text):
            blocks.append((text[start:], section, heading_evidence, audience_role, root_section, root_heading))
        for block, heading, heading_ref, role, root, root_ref in blocks:
            for part in re.split(r'[。；;！？!?]', block):
                quote = part.strip()
                if quote:
                    clauses.append(SourceClause(reading_text(quote), (RuleEvidence(segment_id=segment.id, quote=quote),), heading, heading_ref, source, role, root, root_ref))
    return _join_page_continuations(document, clauses)


def _join_page_continuations(document, clauses):
    """Join one open parenthesis across two adjacent main-PDF pages only."""
    segments = {segment.id: segment for segment in document.segments}
    result = []
    for clause in clauses:
        prior = result[-1] if result else None
        if prior and len(prior.evidence) == len(clause.evidence) == 1:
            left = segments[prior.evidence[0].segment_id]
            right = segments[clause.evidence[0].segment_id]
            joined = reading_text(prior.text + '\n' + clause.text)
            if (left.asset_id in document.primary_asset_ids and left.asset_id == right.asset_id
                    and left.page is not None and right.page == left.page + 1
                    and prior.section == clause.section and prior.root_section == clause.root_section
                    and prior.audience_role == clause.audience_role
                    and left.text.rstrip().endswith(prior.evidence[0].quote)
                    and right.text.lstrip().startswith(clause.evidence[0].quote)
                    and not _CONTINUATION_BOUNDARY.match(clause.evidence[0].quote)
                    and (parenthesis_balance(prior.text) or 0) > 0
                    and parenthesis_balance(joined) == 0
                    and len(joined) <= MAX_CONTINUED_CLAUSE_CHARS):
                result[-1] = replace(prior, text=joined, evidence=(*prior.evidence, *clause.evidence))
                continue
        result.append(clause)
    return tuple(result)


def window_clauses(clauses):
    """Resolve only an explicit adjacent 'during this publicity period' reference."""
    result, index = [], 0
    while index < len(clauses):
        clause = clauses[index]
        if index + 1 < len(clauses):
            following = clauses[index + 1]
            if ('公示' in clause.text and _DATE.search(clause.text)
                    and following.source_key == clause.source_key and following.section == clause.section and _OBJECTION.search(following.text)
                    and not _DATE.search(following.text)
                    and not re.search(r'(?:不接受|不受理|禁止|不得)(?:任何|提出)?(?:异议|申诉|复核)', following.text)):
                clause = SourceClause(clause.text + '。' + following.text,
                                      (*clause.evidence, *following.evidence), clause.section, clause.heading_evidence, clause.source_key, clause.audience_role, clause.root_section, clause.root_heading_evidence)
                index += 1
        result.append(clause)
        index += 1
    return tuple(result)


@dataclass(frozen=True)
class ContextFact:
    text: str
    evidence: tuple[RuleEvidence, ...]


@dataclass(frozen=True)
class ScopedAudience:
    fact: ContextFact
    phase: str


@dataclass(frozen=True)
class NoticeContext:
    clauses: tuple[SourceClause, ...]
    prose_ids: frozenset[str]
    primary_ids: frozenset[str]
    schedule_assets: frozenset[str]
    segment_assets: dict[str, str | None]
    audience: ContextFact | None = None
    entry_conditions: tuple[ContextFact, ...] = ()
    pass_score: ContextFact | None = None
    category_override: str | None = None
    entry_window_codes: frozenset[str] = frozenset()
    target_role: str | None = None
    scoped_audiences: tuple[ScopedAudience, ...] = ()
    schedule_complete: bool = False
    gaps: tuple[RuleGap, ...] = ()

    def exam_clause_applies(self, clause):
        return self.target_role is not None and _same_exam_scope(clause, self.target_role)

    def related(self, label):
        for clause in self.clauses:
            if self.target_role and not _same_exam_scope(clause, self.target_role) and any(
                    ref.segment_id == original.segment_id and ref.quote == original.quote
                    for ref in label.evidence for original in clause.evidence):
                return False
        return any(ref.segment_id in self.primary_ids or
                   self.segment_assets.get(ref.segment_id) in self.schedule_assets
                   for ref in label.evidence)


def _unique_fact(clauses, pattern, render):
    matches = [(match[1], _clause_refs(clause)) for clause in clauses for match in pattern.finditer(clause.text)]
    values = {value for value, _ in matches}
    if len(values) != 1:
        return None
    return ContextFact(render(next(iter(values))), tuple(dict.fromkeys(ref for _, refs in matches for ref in refs)))


def _clause_refs(clause):
    headings = tuple(ref for ref in (clause.root_heading_evidence, clause.heading_evidence) if ref is not None)
    return tuple(dict.fromkeys((*headings, *clause.evidence)))


def _same_exam_scope(clause, target_role):
    if clause.audience_role not in (None, target_role) or _population(clause.text) not in (None, target_role):
        return False
    root = re.sub(r'^[一二三四五六七八九十\d]+[、.．]\s*', '', clause.root_section)
    return not root or bool(re.fullmatch(
        r'(?:(?:本科(?:生|学生)?|研究生)?考试(?:对象|内容|安排|规则|要求|时间|地点|形式(?:及安排)?|方式(?:及操作步骤)?)?|其他有关事项|注意事项)', root))


def _audience_facts(clause):
    found = []
    if re.search(r'尚未通过[^。；]{0,30}考试的所有在校本科(?:学生|生)', clause.text):
        found.append('尚未通过考试的所有在校本科生')
    found.extend(year + '级全体全日制本科生' for year in re.findall(r'(\d{4})级全体全日制本科生', clause.text))
    found.extend('未通过考试的非' + year + '级本科生' for year in re.findall(r'未通过(?:考试)?的?非(\d{4})级本科生', clause.text))
    return [ContextFact(text, _clause_refs(clause)) for text in dict.fromkeys(found)]


def student_category_override(title, text):
    """Distinguish student participation from staff-only teaching work."""
    if _TEACHING.search(title):
        if _STUDENT_ACTION.search(text):
            return 'daily'
        if _TEACHER_APPLICATION.search(text) or ('教学' in title and _UNIT_TEACHING.search(text)):
            return 'excluded'
    return None


def build_context(document):
    clauses = primary_clauses(document)
    all_text = '。'.join(clause.text for clause in clauses)
    title = reading_text(document.title)
    primary_ids = frozenset(segment.id for segment in document.segments[1:]
                            if segment.kind == 'body' or segment.asset_id in document.primary_asset_ids)
    audience, entry, score = None, [], None
    scoped, gaps, target_role = [], [], None
    mode = 'exam' if '考试' in title else 'photo' if re.search(r'图像采集|毕业照', title) else None
    if mode == 'exam':
        target_role = _population(title) or 'undergraduate'
        exam_clauses = [clause for clause in clauses if _same_exam_scope(clause, target_role)]
        for clause in clauses:
            if clause not in exam_clauses and (_HOURS.search(clause.text) or _SCORE.search(clause.text)):
                gaps.append(RuleGap(code='coverage_unconfirmed', detail='局部章节的考试条件未扩展至其他对象',
                                    evidence=_clause_refs(clause)))
        target_clauses = [clause for clause in exam_clauses if '考试对象' in clause.section] or exam_clauses
        found = []
        for clause in target_clauses:
            limit = _PHASE_LIMIT.search(clause.text)
            for fact in _audience_facts(clause):
                if limit:
                    scoped.append(ScopedAudience(fact, limit[0]))
                else:
                    found.append(fact)
        if found:
            audience = ContextFact('及'.join(dict.fromkeys(fact.text for fact in found)),
                                   tuple(dict.fromkeys(ref for fact in found for ref in fact.evidence)))
        hours = _unique_fact(exam_clauses, _HOURS, lambda value: f'在线学习累计至少{value}小时方可参加考试')
        if hours:
            entry.append(hours)
        score = _unique_fact(exam_clauses, _SCORE, lambda value: f'考试成绩≥{value}分；未通过不能取得该课程学分')
    elif mode == 'photo':
        candidates = [(match, clause) for clause in clauses
                      for match in re.finditer(r'采集对象(?:为|是|:)(\d{4})届本科毕业生', clause.text)]
        years = {match[1] for match, _ in candidates}
        if len(years) == 1:
            year = next(iter(years)); refs = tuple(ref for _, clause in candidates for ref in clause.evidence)
            audience = ContextFact(year + '届本科毕业生', refs)
            entry.append(ContextFact(year + '届毕业', refs))
            excluded = [clause for clause in clauses if re.search(r'已采集过学历电子照片.{0,100}不参加本次采集', clause.text)]
            if excluded:
                entry.append(ContextFact('尚未采集学历电子照片', tuple(ref for clause in excluded for ref in clause.evidence)))
    if audience is None and '转专业' in title:
        eligible = [clause for clause in clauses if '符合' in clause.text and re.search(r'第[^。]{1,45}规定', clause.text)]
        for clause in eligible:
            match = re.search(r'符合(?P<rule>《[^》]+》第[^，,。]{1,45}?规定)', clause.text)
            if match:
                entry.append(ContextFact('符合' + match['rule'], clause.evidence))
                audience = ContextFact('符合有关规定的本科生', clause.evidence)
        limited = [clause for clause in clauses if '仅限转入以下指定专业' in clause.text]
        if limited:
            entry.append(ContextFact('仅限正文指定转入专业', tuple(ref for clause in limited for ref in clause.evidence)))
    category = student_category_override(title, all_text)
    schedule_assets = set()
    if mode and _SCHEDULE_REFERENCE.search(all_text):
        grouped = {}
        for segment in document.segments[1:]:
            if segment.kind == 'attachment' and segment.asset_id not in document.primary_asset_ids:
                grouped.setdefault(segment.asset_id, []).append(segment.text)
        for asset_id, texts in grouped.items():
            beginning = reading_text(' '.join(texts[:5]))
            if mode == 'exam' and _population(beginning) not in (None, target_role):
                continue
            if (mode == 'exam' and re.search(r'考试.{0,24}(?:安排|考场)', beginning)
                    or mode == 'photo' and re.search(r'图像采集.{0,24}(?:安排|时间)', beginning)):
                schedule_assets.add(asset_id)
    entry_window_codes = frozenset(('event',)) if mode else frozenset(('registration', 'application', 'submission')) if '转专业' in title else frozenset()
    return NoticeContext(clauses, frozenset(ref.segment_id for c in clauses for ref in c.evidence), primary_ids,
                         frozenset(schedule_assets), {segment.id: segment.asset_id for segment in document.segments},
                         audience, tuple(entry), score, category, entry_window_codes, target_role,
                         tuple(scoped), document.body_status == 'full' and not document.gaps, tuple(gaps))


def _requirement(existing, facts):
    additions = tuple(fact.text for fact in facts)
    if existing:
        prior = existing.items if existing.operator != 'any' else ('或'.join(existing.items),)
        additions = (*prior, *additions)
    additions = tuple(dict.fromkeys(additions))
    return Requirement(operator='text' if len(additions) == 1 else 'all', items=additions) if additions else None


def _scope(scope, audience):
    if audience is None:
        return scope
    groups = scope.audience_groups or (AudienceGroup(audience=audience.text),)
    return scope.model_copy(update={'audience_groups': tuple(group.model_copy(update={
        'audience': audience.text if not group.audience or group.audience == audience.text
        else audience.text + '；' + group.audience}) if _compatible_audience(group, audience.text)
        else group for group in groups)})


def _compatible_audience(group, audience):
    """Do not narrow an explicit exceptional table group to an unrelated cohort."""
    local = ' '.join(value for value in (group.audience, group.class_name) if value)
    role, target = _population(local), _population(audience)
    if role and target and role != target and target != 'mixed':
        return False
    included = set(re.findall(r'(?<!非)(\d{4})级', audience))
    excluded = set(re.findall(r'非(\d{4})级', audience))
    local_included = set(re.findall(r'(?<!非)(\d{4})级', local))
    local_excluded = set(re.findall(r'非(\d{4})级', local))
    if included and not excluded:
        if (local_included and not local_included & included) or included <= local_excluded:
            return False
        if re.search(r'未通过|补考|重修', local) and not re.search(r'未通过|补考|重修', audience):
            return False
    if excluded and local_included and all(year in excluded and year not in included for year in local_included):
        return False
    return True


def _effective_audience(label, context, phase_audience):
    audience = context.audience if (isinstance(label, ProductBenefitLabel) or label.code in context.entry_window_codes) else None
    if phase_audience is not None:
        facts = tuple(fact for fact in (audience, phase_audience) if fact is not None)
        audience = ContextFact('或'.join(dict.fromkeys(fact.text for fact in facts)),
                               tuple(dict.fromkeys(ref for fact in facts for ref in fact.evidence)))
    return audience


def enrich_label(label, context, *, phase_audience=None):
    if not context.related(label):
        return label
    facts = ()
    if isinstance(label, WindowLabel) and label.code in context.entry_window_codes and label.value.state != 'ended':
        facts = context.entry_conditions
    elif (isinstance(label, ProductBenefitLabel) and label.code == 'course_credit'
          and label.value.claim_relation == 'necessary_condition_not_sufficient_guarantee'):
        facts = (*context.entry_conditions, *((context.pass_score,) if context.pass_score else ()))
    if facts:
        existing = label.value.requirement
        if isinstance(label, ProductBenefitLabel) and context.pass_score and existing and existing.items == ('考试合格',):
            existing = None
        label = label.model_copy(update={'value': label.value.model_copy(update={'requirement': _requirement(existing, facts)})})
    use_audience = _effective_audience(label, context, phase_audience)
    refs = tuple(dict.fromkeys((*label.evidence, *(ref for fact in facts for ref in fact.evidence),
                                *(use_audience.evidence if use_audience else ()))))
    return label.model_copy(update={'scope': _scope(label.scope, use_audience), 'evidence': refs})


def _last_schedule_indices(labels, context):
    """Resolve only one complete, explicitly ordered schedule, never list order."""
    if not context.schedule_complete or len(context.schedule_assets) != 1:
        return ()
    windows = []
    for index, label in enumerate(labels):
        if not isinstance(label, WindowLabel) or label.code != 'event':
            continue
        if not any(context.segment_assets.get(ref.segment_id) in context.schedule_assets for ref in label.evidence):
            continue
        start, end = label.value.start, label.value.end
        if (label.value.state != 'announced' or start is None or end is None
                or start.kind != 'absolute' or end.kind != 'absolute'
                or not start.time or not end.time):
            return ()
        windows.append((index, (start.date, start.time), (end.date, end.time)))
    intervals = sorted(set((start, end) for _, start, end in windows))
    if not intervals or any(earlier[1] > later[0] for earlier, later in zip(intervals, intervals[1:])):
        return ()
    return tuple(index for index, start, end in windows if (start, end) == intervals[-1])


def enrich_labels(labels, context):
    phase_audiences, gaps = {}, list(context.gaps)
    for audience in context.scoped_audiences:
        indices = _last_schedule_indices(labels, context) if audience.phase in ('最后一场', '末场') else ()
        if not indices:
            gaps.append(RuleGap(code='coverage_unconfirmed',
                                detail=f'限定{audience.phase}的对象尚不能唯一绑定到可靠场次，未扩展至所有场次',
                                evidence=audience.fact.evidence))
            continue
        for index in indices:
            phase_audiences.setdefault(index, []).append(audience.fact)
    result = []
    for index, label in enumerate(labels):
        facts = phase_audiences.get(index, [])
        phase = ContextFact('或'.join(dict.fromkeys(fact.text for fact in facts)),
                            tuple(dict.fromkeys(ref for fact in facts for ref in fact.evidence))) if facts else None
        audience = _effective_audience(label, context, phase)
        if audience and context.related(label) and any(
                not _compatible_audience(group, audience.text) for group in label.scope.audience_groups):
            gaps.append(RuleGap(code='coverage_unconfirmed', detail='表内特殊对象与共同受众的交集未确认，保留原组未添加共同范围',
                                evidence=tuple(dict.fromkeys((*label.evidence, *audience.evidence)))))
        result.append(enrich_label(label, context, phase_audience=phase))
    return result, tuple(dict.fromkeys(gaps))


def objection_requirement(text):
    if not re.search(r'异议|申诉|复核', text):
        return None
    terms = []
    written = '书面' in text and not re.search(r'无需书面|不用书面|不要求书面', text)
    named = '署名' in text and not re.search(r'无需署名|不用署名|不要求署名', text)
    if written and named:
        terms.append('书面署名')
    elif written or named:
        terms.append('书面' if written else '署名')
    if '如实反映' in text:
        terms.append('如实反映')
    return Requirement(operator='text' if len(terms) == 1 else 'all', items=tuple(terms)) if terms else None
