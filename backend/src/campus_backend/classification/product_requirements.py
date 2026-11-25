"""Bounded, source-preserving requirements for specific student actions."""
from dataclasses import dataclass
import re

from .product_context import NoticeContext, parenthesis_balance, reading_text
from .product_labels import Requirement, WindowLabel
from .rule_labels import RuleEvidence, RuleGap

_NUMBERING = re.compile(r'^\d+[.、]\s*')
_ADMISSION_START = re.compile(
    r'^(?:(?:所有|全体|各)?(?:参考学生|考生|参加考试的学生|学生|本科生))?(?:均|都)?'
    r'(?:必须|须|应)(?:携带|持|出示|使用)'
)
_IDENTITY_DOCUMENT = re.compile(r'校园卡|学生证|身份证|准考证|护照')
_ADMISSION_ACTION = re.compile(r'入场|进入考场|参加考试|参考')
_EXCEPTION = re.compile(r'遗失|不清晰|否则|无需|无须|不必|免于|例外|改用|替代')
_ELLIPTICAL_EXCEPTION = re.compile(r'^(?:但|如|若)?(?:遗失|丢失|不清晰|损坏)(?:的|时|者|情况下).*(?:可凭|可用|可持|可出示|改用|替代)')
_LOCAL_SCOPE = re.compile(r'最后一场|末场|第[一二三四五六七八九十百\d]+场|指定场次|补考|初试|复试|仅限|仅适用|只适用')
_EVENT_TIME = re.compile(r'\d{1,2}\s*[月日]|\d{1,2}\s*[:：]\s*\d{2}')
_OTHER_EVENT = re.compile(r'培训|讲座|辅导|练习|演练|答疑')
_EXAM_TIME_SECTION = re.compile(r'(?:[一二三四五六七八九十\d]+[、.．]\s*)?考试(?:时间|日期)(?:(?:和|及)地点)?[:：]?$')
_COMMON_ENTRY_SECTION = re.compile(
    r'(?:(?:本科(?:生|学生)?|研究生)?考试(?:对象|内容|安排|规则|要求|时间|地点|形式(?:及安排)?|方式(?:及操作步骤)?)?'
    r'|其他有关事项|注意事项|入场(?:要求|规定|须知)|证件(?:要求|检查))'
)
MAX_REQUIREMENT_CHARS = 1200


@dataclass(frozen=True)
class ScopedRequirement:
    text: str
    evidence: tuple[RuleEvidence, ...]


@dataclass(frozen=True)
class RequirementContext:
    admission: tuple[ScopedRequirement, ...] = ()
    gaps: tuple[RuleGap, ...] = ()


def collect_requirements(context: NoticeContext) -> RequirementContext:
    """Keep a conditional credential clause whole; do not infer an AND/OR tree."""
    candidates, gaps = [], []
    for index, clause in enumerate(context.clauses):
        text = _NUMBERING.sub('', clause.text)
        start = _ADMISSION_START.match(text)
        credential = _IDENTITY_DOCUMENT.search(text, start.end()) if start else None
        if not credential or context.target_role is None:
            continue
        headings = tuple(ref for ref in (clause.root_heading_evidence, clause.heading_evidence) if ref)
        evidence = tuple(dict.fromkeys((*headings, *clause.evidence)))
        section = re.sub(r'^[一二三四五六七八九十\d]+[、.．]\s*', '', clause.section)
        if not context.exam_clause_applies(clause) or (section and not _COMMON_ENTRY_SECTION.fullmatch(section)):
            gaps.append(RuleGap(code='coverage_unconfirmed', detail='入场证件的局部阶段或章节尚不能唯一绑定，未扩展至所有场次',
                                evidence=evidence))
            continue
        if _LOCAL_SCOPE.search(text):
            gaps.append(RuleGap(code='coverage_unconfirmed', detail='入场证件的正文适用范围尚不能唯一绑定，未扩展至所有场次',
                                evidence=evidence))
            continue
        following = context.clauses[index + 1] if index + 1 < len(context.clauses) else None
        if (following is not None and following.source_key == clause.source_key
                and following.section == clause.section and context.exam_clause_applies(following)
                and ((_IDENTITY_DOCUMENT.search(following.text) and _EXCEPTION.search(following.text))
                     or _ELLIPTICAL_EXCEPTION.search(following.text))):
            gaps.append(RuleGap(code='coverage_unconfirmed', detail='考试入场证件的后续例外尚未合并，未保留无条件主张',
                                evidence=tuple(dict.fromkeys((*evidence, *following.evidence)))))
            continue
        if (parenthesis_balance(text) != 0 or len(text) > MAX_REQUIREMENT_CHARS
                or not _ADMISSION_ACTION.search(text, credential.end())):
            gaps.append(RuleGap(code='coverage_unconfirmed', detail='考试入场证件条件不完整或跨页关系未确认', evidence=evidence))
            continue
        candidates.append(ScopedRequirement(text, evidence))
    return RequirementContext(tuple(dict.fromkeys(candidates)), tuple(dict.fromkeys(gaps)))


def _conjoin(existing, conditions):
    if existing is None:
        items = ()
    elif existing.operator == 'any':
        items = ('(' + '或'.join('(' + item + ')' for item in existing.items) + ')',)
    else:
        items = existing.items
    items = tuple(dict.fromkeys((*items, *(condition.text for condition in conditions))))
    return Requirement(operator='text' if len(items) == 1 else 'all', items=items)


def _is_exam_window(label, context):
    """Identify the dated action from its own evidence, before adding context."""
    dated = [ref for ref in label.evidence if _EVENT_TIME.search(reading_text(ref.quote))]
    if not dated or any(_OTHER_EVENT.search(reading_text(ref.quote)) for ref in dated):
        return False
    if any(context.segment_assets.get(ref.segment_id) in context.schedule_assets for ref in dated):
        return True
    for clause in context.clauses:
        if (context.exam_clause_applies(clause) and any(ref in dated for ref in clause.evidence)
                and ('考试' in clause.text or _EXAM_TIME_SECTION.fullmatch(clause.section))):
            return True
    return False


def apply_requirements(labels, requirements: RequirementContext, context: NoticeContext):
    """Admission applies to this exam's actionable windows, never credit benefits."""
    result, gaps = [], list(requirements.gaps)
    for label in labels:
        if (requirements.admission and isinstance(label, WindowLabel) and label.code == 'event'
                and label.value.student_action and label.value.state not in ('ended', 'cancelled')
                and context.related(label)):
            evidence = tuple(dict.fromkeys((*label.evidence, *(ref for item in requirements.admission for ref in item.evidence))))
            if _is_exam_window(label, context):
                label = label.model_copy(update={
                    'value': label.value.model_copy(update={'requirement': _conjoin(label.value.requirement, requirements.admission)}),
                    'evidence': evidence,
                })
            else:
                gaps.append(RuleGap(code='coverage_unconfirmed', detail='日期证据尚不能绑定本次考试动作，未继承考试入场证件条件', evidence=evidence))
        result.append(label)
    return result, tuple(dict.fromkeys(gaps))
