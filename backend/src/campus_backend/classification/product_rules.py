"""Version 2 public notice extraction and presentation scopes."""

import re
from collections import defaultdict

from campus_backend.documents.models import DocumentBundle
from .product_labels import (
    RULES_VERSION, AudienceGroup, ProductBenefitLabel, ProductBenefitValue,
    AbsoluteEndpoint, ProductConditionLabel, ProductRuleResult, ProductScope, ProductStatusLabel,
    Requirement, WindowLabel, WindowValue,
)
from .rule_baseline import analyze_rules, date_revision_role, extract_local_benefits, extract_local_scope
from .rule_labels import BenefitLabel, ConditionLabel, DateLabel, RuleEvidence, RuleGap, StatusLabel
from .rule_windows import prose_window, prose_windows, table_row, table_slot
from .product_context import build_context, enrich_labels, objection_requirement, window_clauses
from .product_requirements import apply_requirements, collect_requirements

_CLAUSE = re.compile(r'[^。；;！？!?\n]+')
_CURRICULUM = re.compile(r'辅修学士学位|辅修专业|微专业')
_CREDIT_QUANTITY = re.compile(r'(?P<amount>\d+(?:\.\d+)?)\s*学分')
_MINIMUM = re.compile(r'最低|至少|不少于|不得低于|须修满|学分要求')
_MAXIMUM = re.compile(r'至多|不超过|不得超过')
_OFFERING = re.compile(r'共计|合计|课程包|总计')
_NECESSARY_CREDIT = re.compile(r'(?:未通过考试|考试(?:未通过|不(?:合格|通过))).{0,16}(?:不能|不得|无法)(?:取得|获得|获取).{0,10}(?:课程)?学分')
_PRIZE_CERTIFICATE = re.compile(r'设(?P<awards>(?:[一二三]等奖[、，,]?){1,3})(?:若干)?[，,]\s*颁发(?:荣誉)?证书')
_TIME_HEADING = re.compile(r'^(?:[0-9一二三四五六七八九十]+[.．、]\s*)?(?:考试|报名|提交|申请|活动|比赛)(?:日期|时间)\s*[:：]?$')
_CERTIFICATE_NEGATION = re.compile(r'并非|不是|不会|不予|不能|不颁发|不实|未经证实')
_CERTIFICATE_CONJUNCTION = re.compile(r'及|且|和')
_CERTIFICATE_ALTERNATIVE = re.compile(r'或|/')
_CERTIFICATE_EXTRA = re.compile(r'(?:但|且|并)?须\s*(审核通过|通过审核)$')
_CERTIFICATE_LEVEL_DESCRIPTION = re.compile(r'(?:获奖|该奖项)(?:视为|属于|认定为)(?:校级|省级|国家级)(?:学科)?竞赛获奖$')
_CONDITIONAL_CERTIFICATE = re.compile(r'获(?:得)?(?P<awards>[一二三](?:[、/一二三等奖及且和或 ]{0,20})等奖)者(?:予以|将)?颁发(?:荣誉)?证书')


def _product_scope(old):
    groups = (AudienceGroup(audience=old.audience),) if old.audience else ()
    return ProductScope(action=old.action, track=old.track, audience_groups=groups)


def _product_benefits(text, evidence, gaps):
    program = _CURRICULUM.search(text)
    quantity = _CREDIT_QUANTITY.search(text)
    minimum, maximum, offering = (_MINIMUM.search(text), _MAXIMUM.search(text), _OFFERING.search(text))
    if program and quantity and sum(map(bool, (minimum, maximum, offering))) == 1:
        return [ProductBenefitLabel(
            code='course_credit', scope=ProductScope(track=program[0]), evidence=(evidence,),
            value=ProductBenefitValue(
                amount=float(quantity['amount']) if '.' in quantity['amount'] else int(quantity['amount']),
                unit='学分', claim_relation='curriculum_offering' if offering else 'curriculum_requirement',
                quantity_operator='eq' if offering else 'gte' if minimum else 'lte',
            ),
        )]
    scope = _product_scope(extract_local_scope(text))
    if _NECESSARY_CREDIT.search(text):
        return [ProductBenefitLabel(
            code='course_credit', scope=scope, evidence=(evidence,),
            value=ProductBenefitValue(
                claim_relation='necessary_condition_not_sufficient_guarantee', condition_status='stated',
                requirement=Requirement(operator='text', items=('考试合格',)),
            ),
        )]
    award = _CONDITIONAL_CERTIFICATE.search(text) or _PRIZE_CERTIFICATE.search(text)
    if award:
        if _CERTIFICATE_NEGATION.search(text):
            return []
        awards = tuple(dict.fromkeys(level + '等奖' for level in re.findall(r'[一二三]', award['awards'])))
        conjunction = _CERTIFICATE_CONJUNCTION.search(award['awards'])
        alternative = _CERTIFICATE_ALTERNATIVE.search(award['awards'])
        tail = text[award.end():].strip(' ，,')
        if _CERTIFICATE_LEVEL_DESCRIPTION.fullmatch(tail):
            tail = ''
        extra = _CERTIFICATE_EXTRA.fullmatch(tail)
        if (conjunction and alternative) or (extra and len(awards) > 1 and not conjunction) or (tail and not extra):
            gaps.append(RuleGap(code='benefit_unresolved', detail='证书获得条件尚未完整解析', evidence=(evidence,)))
            return []
        if extra:
            awards = (*awards, '审核通过')
        operator = 'text' if len(awards) == 1 else 'all' if conjunction or extra else 'any'
        return [ProductBenefitLabel(
            code='certificate', scope=scope, evidence=(evidence,),
            value=ProductBenefitValue(
                claim_relation='direct_conditional_award', condition_status='stated',
                requirement=Requirement(operator=operator, items=awards),
            ),
        )]
    legacy, _ = extract_local_benefits(text, evidence)
    return [ProductBenefitLabel(
        code=benefit.code, scope=_product_scope(benefit.scope), evidence=benefit.evidence,
        value=ProductBenefitValue(
            claim_relation='direct_conditional_award' if benefit.value.condition else 'direct_award',
            condition_status=benefit.value.condition_status, amount=benefit.value.amount, unit=benefit.value.unit,
            requirement=Requirement(operator='text', items=(benefit.value.condition,)) if benefit.value.condition else None,
        ),
    ) for benefit in legacy if isinstance(benefit, BenefitLabel)]



def _resolved_extensions(legacy):
    labels = []
    for date_label in legacy.labels:
        if not isinstance(date_label, DateLabel) or not any(
            date_revision_role(ref.quote) == 'revision' for ref in date_label.evidence
        ):
            continue
        code = date_label.code.removesuffix('_deadline')
        if code not in ('registration', 'application', 'submission', 'objection'):
            continue
        labels.append(WindowLabel(
            code=code, scope=_product_scope(date_label.scope), evidence=date_label.evidence,
            value=WindowValue(state='rescheduled', end=AbsoluteEndpoint(**date_label.value.model_dump())),
        ))
    return labels



def _merge_table_windows(labels):
    merged = {}
    for label in labels:
        key = label.code, label.scope.action, label.scope.track, label.scope.phase, label.value
        campus = tuple(dict.fromkeys(group.campus for group in label.scope.audience_groups))
        key += (campus, label.evidence[0])
        previous = merged.get(key)
        if previous:
            scope = label.scope.model_copy(update={
                'audience_groups': tuple(dict.fromkeys((*previous.scope.audience_groups, *label.scope.audience_groups)))
            })
            label = label.model_copy(update={'scope': scope,
                                            'evidence': tuple(dict.fromkeys((*previous.evidence, *label.evidence)))})
        merged[key] = label
    return merged.values()


def _mark_conflicts(labels):
    groups = defaultdict(list)
    for index, label in enumerate(labels):
        if isinstance(label, WindowLabel) and label.code not in ('event',) and label.value.end is not None:
            groups[label.code, label.scope, label.value.start].append(index)
    gaps = [RuleGap(code='date_conflict', detail='明确日期区间的结束早于开始', evidence=label.evidence)
            for label in labels if isinstance(label, WindowLabel) and label.value.state == 'conflicting']
    for indices in groups.values():
        if len({labels[index].value.end for index in indices}) < 2:
            continue
        refs = []
        for index in indices:
            label = labels[index]
            refs.extend(label.evidence)
            labels[index] = label.model_copy(update={'value': label.value.model_copy(update={'state': 'conflicting'})})
        gaps.append(RuleGap(code='date_conflict', detail='同一事项和对象存在不同截止日期',
                            evidence=tuple(dict.fromkeys(refs))))
    return gaps


def analyze_product_rules(document: DocumentBundle) -> ProductRuleResult:
    """Analyze only public segments while keeping legacy output independently readable."""
    legacy = analyze_rules(document)
    notice_context = build_context(document)
    labels = _resolved_extensions(legacy)
    for label in legacy.labels:
        if isinstance(label, ConditionLabel) and label.code == 'eligibility':
            labels.append(ProductConditionLabel(
                code=label.code, scope=_product_scope(label.scope), evidence=label.evidence,
                presentation='detail', value=Requirement(operator='text', items=(label.value.text,)),
            ))
        elif isinstance(label, StatusLabel) and label.value != 'event_ended':
            labels.append(ProductStatusLabel(
                code=label.code, value=label.value, scope=_product_scope(label.scope),
                evidence=label.evidence, presentation='detail',
            ))
    context, slot, last_asset_page = None, None, None
    table_windows = []
    table_slot_refs = set()
    product_gaps = []
    for segment in document.segments[1:]:
        sheet = segment.location.split('/row:', 1)[0] if segment.location.startswith('sheet:') else None
        asset_page = (segment.kind, segment.asset_id, segment.page, sheet)
        if asset_page != last_asset_page:
            context, slot = None, None
        last_asset_page = asset_page
        lines = (segment.text,) if '\t' in segment.text and sheet else segment.text.splitlines()
        wrapped_prose = not sheet and '\t' not in segment.text and '\n' in segment.text
        time_heading = None
        for raw_line in lines:
            line = raw_line.strip('\r\n') if sheet or '\t' in raw_line else raw_line.strip()
            if not line.strip():
                continue
            evidence = RuleEvidence(segment_id=segment.id, quote=line)
            if _TIME_HEADING.fullmatch(line):
                time_heading = evidence
                continue
            heading, time_heading = time_heading, None
            local_slot = table_slot(line, evidence, document.title, allow_unheaded=bool(sheet),
                                    merged_ranges=segment.table_merges)
            if local_slot:
                slot, context = local_slot, None
                table_slot_refs.add((evidence.segment_id, evidence.quote))
                continue
            context, window = table_row(line, evidence, document.title, context, slot)
            if window:
                table_windows.append(window)
                continue
            if '\t' in line or line.startswith('|'):
                continue
            if segment.id in notice_context.prose_ids:
                continue  # main prose is read as logical clauses below
            for match in _CLAUSE.finditer(line):
                text = match[0].strip()
                if not text:
                    continue
                evidence = RuleEvidence(segment_id=segment.id, quote=text)
                historical_or_extension = date_revision_role(text) is not None
                windows = () if historical_or_extension else prose_windows(
                    text, evidence, document.title, heading.quote if heading else None
                )
                for window in windows:
                    if wrapped_prose and window.value.start and window.value.start.kind == 'relative':
                        continue
                    if heading:
                        window = window.model_copy(update={'evidence': (heading, *window.evidence)})
                    labels.append(window)
                if not wrapped_prose:
                    labels.extend(_product_benefits(text, evidence, product_gaps))
        if wrapped_prose and segment.id not in notice_context.prose_ids:
            for clause in re.split(r'[。；;！？!?]', segment.text):
                text = clause.strip()
                if text:
                    evidence = RuleEvidence(segment_id=segment.id, quote=text)
                    joined = text.replace('\n', '')
                    labels.extend(_product_benefits(joined, evidence, product_gaps))
                    if '日后' in joined.replace(' ', '') and ('核对' in joined or '校对' in joined):
                        relative_window = prose_window(joined, evidence, document.title)
                        if relative_window:
                            labels.append(relative_window)
    for clause in window_clauses(notice_context.clauses):
        if any((ref.segment_id, ref.quote) in table_slot_refs for ref in clause.evidence):
            continue
        heading = clause.section if _TIME_HEADING.fullmatch(clause.section) else None
        windows = () if date_revision_role(clause.text) is not None else prose_windows(
            clause.text, clause.evidence[0], document.title, heading,
        )
        for window in windows:
            evidence = tuple(dict.fromkeys((
                *((clause.heading_evidence,) if heading and clause.heading_evidence else ()),
                *window.evidence, *clause.evidence,
            )))
            requirement = objection_requirement(clause.text) if window.code == 'objection' else None
            if window.code == 'objection':
                window = window.model_copy(update={'value': window.value.model_copy(update={'requirement': requirement})})
            labels.append(window.model_copy(update={'evidence': evidence}))
        for benefit in _product_benefits(clause.text, clause.evidence[0], product_gaps):
            labels.append(benefit.model_copy(update={'evidence': tuple(dict.fromkeys((*benefit.evidence, *clause.evidence)))}))
    labels.extend(_merge_table_windows(table_windows))
    labels, requirement_gaps = apply_requirements(labels, collect_requirements(notice_context), notice_context)
    labels, context_gaps = enrich_labels(labels, notice_context)
    v2_conflicts = _mark_conflicts(labels)
    category = notice_context.category_override or legacy.category
    legacy_gaps = tuple(gap for gap in legacy.gaps if gap.code != 'category_unknown' or category == 'unknown')
    gaps = tuple(dict.fromkeys((*legacy_gaps, *v2_conflicts, *product_gaps, *context_gaps, *requirement_gaps)))
    if category == 'excluded':
        labels = [label.model_copy(update={'presentation': 'detail'}) for label in labels]
    return ProductRuleResult(
        rules_version=RULES_VERSION, notice_id=document.notice_id,
        content_version=document.content_version, input_fingerprint=document.input_fingerprint,
        category=category, complete=not gaps and legacy.complete, labels=tuple(dict.fromkeys(labels)), gaps=gaps,
    )
