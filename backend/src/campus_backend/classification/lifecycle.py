"""Collector admission and list visibility, independent of legacy routing.

Dates are interpreted in Asia/Shanghai. A registration deadline is a distinct
fact from an event ending; only evidenced student competition registration gets
fourteen days. Unknown and conflicting facts remain reviewable.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import os
import re

from campus_notice.deadlines import extract_deadline

BEIJING = timezone(timedelta(hours=8))
_DATE = re.compile(r'(?<!\d)(?:\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}|\d{1,2}月\d{1,2}日)')
_COMPETITION = re.compile(r'竞赛|比赛|大赛|赛事')
_REGISTER = re.compile(r'报名|注册参赛|参赛登记')
_OTHER_ACTION = re.compile(r'申请|申报|提交|递交|缴费|报送|汇总|确认|补交|登记|选课|退课|填报|异议|申诉')
_DEPARTMENT = re.compile(r'学生工作(?:办公室|处)|各?学院|各?系(?:部)?|各?单位|各?部门|辅导员|班主任|教务处|研究生院')
_STUDENT = re.compile(r'学生|同学|考生|报名者|参赛者|参与者')
_EXTENSION = re.compile(r'延至|延期至|延长至|顺延至|调整为|调整至')


def as_moment(value):
    """Normalize an ISO timestamp or datetime; naive values mean Beijing."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('时间必须为ISO字符串或datetime')
    return (parsed.replace(tzinfo=BEIJING) if parsed.tzinfo is None else parsed).astimezone(BEIJING)


def deadline_moment(candidate):
    if candidate.get('status') != 'known' or not candidate.get('value'):
        return None
    if candidate.get('precision') == 'date':
        return datetime.combine(date.fromisoformat(candidate['value']), time.max, tzinfo=BEIJING)
    return as_moment(candidate['value'])


def _student_extension_actor(prefix):
    units = list(_DEPARTMENT.finditer(prefix))
    actors = [(m.start(), 'student') for m in _STUDENT.finditer(prefix)
              if not any(unit.start() <= m.start() < unit.end() for unit in units)]
    actors += [(m.start(), 'department') for m in units]
    return not actors or max(actors)[1] == 'student'


def _empty():
    return {'status': 'unknown', 'value': None, 'precision': None, 'evidence': None,
            'source': None, 'year_inferred': False, 'candidates': [], 'warnings': []}


def _select(candidates):
    result = _empty()
    result['candidates'] = deepcopy(candidates)
    if not candidates:
        return result
    # Explicit dates alone are authoritative. Inferred years and invalid dates
    # remain evidence, but cannot silently produce an automatic hide time.
    usable = [c for c in candidates if c.get('value') and not c.get('year_inferred')]
    values = {c['value'] for c in usable}
    precise = [c for c in usable if c.get('precision') == 'minute']
    compatible = len({c['value'][:10] for c in usable}) == 1 and len({c['value'] for c in precise}) <= 1
    if len(usable) != len(candidates):
        result['warnings'].append('存在无明确年份或无法解析的日期，需核对原文')
        result['status'] = 'ambiguous'
    elif len(values) > 1 and not compatible:
        result['status'] = 'ambiguous'
        result['warnings'].append('存在多个不同日期，需核对适用事项或延期依据')
    elif usable:
        selected = precise[0] if precise else usable[0]
        result.update({key: selected.get(key) for key in ('value', 'precision', 'evidence', 'source', 'year_inferred')})
        result['status'] = 'known'
    return result


def extract_temporal_facts(notice, *, now):
    """Collect evidenced registration, event-end and policy validity facts.

    Legacy date parsing still supplies dates/actors. This layer additionally
    requires registration semantics local to that date, rather than treating
    every student or departmental action deadline as a registration deadline.
    """
    texts = [('title', notice.get('title', ''))]
    if notice.get('body_status') != 'title_only':
        texts.append(('content', notice.get('content', '')))
    registrations, events, policy_ends, extensions = [], [], [], []
    ended_evidence = None
    visible_text = '\n'.join(text for _, text in texts)
    competition_title = notice.get('title', '')
    competition = bool((_COMPETITION.search(competition_title) and not re.search(
        r'讲座|培训|经验|获奖|结果|公示|名单', competition_title)) or any(
        re.search(r'(?:报名|参加|参与)[^。\n]{0,15}(?:竞赛|比赛|大赛)|(?:竞赛|比赛|大赛)[^。\n]{0,15}(?:报名|将于|举行|结束|时间|参赛)', clause)
        and not re.search(r'曾获|获奖|奖项|获得|往年|上届|培训|讲座', clause)
        for source, text in texts if source == 'content' for clause in re.split(r'[。；;\n]', text)))
    previous_registration = None
    for source, text in texts:
        for clause in re.split(r'[，,。；;\n！？!?]', text):
            clause = clause.strip()
            if not clause:
                continue
            parsed = extract_deadline({'title': clause, 'body_status': 'title_only',
                'published_at': notice.get('published_at')}, now)['candidates']
            matches = list(_DATE.finditer(clause))
            for index, candidate in enumerate(parsed):
                if index >= len(matches):
                    continue
                candidate = dict(candidate, source=source)
                match = matches[index]
                start = matches[index - 1].end() if index else 0
                prefix = clause[start:match.start()]
                suffix = clause[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(clause)]
                register_hits = list(_REGISTER.finditer(prefix))
                other_hits = [m for m in _OTHER_ACTION.finditer(prefix)
                              if not any(r.start() <= m.start() < r.end() for r in register_hits)]
                is_registration = bool(register_hits and (not other_hits or register_hits[-1].start() > other_hits[-1].start()))
                extension = bool(_EXTENSION.search(prefix))
                # A directly adjacent explicit continuation can inherit only a
                # previously evidenced registration action, never another task.
                inherited = extension and previous_registration is not None and not other_hits
                is_student = (candidate['role'] == 'student'
                    or (candidate['role'] == 'unknown' and _student_extension_actor(prefix)
                        and (inherited or (is_registration and extension))))
                if (is_registration or inherited) and is_student:
                    registrations.append(candidate)
                    previous_registration = candidate
                    if extension:
                        extensions.append(candidate)
                else:
                    # Any intervening dated task breaks inheritance, including
                    # action vocabulary this version does not recognize.
                    previous_registration = None
                if (_COMPETITION.search(clause) and not re.search(r'报名|提交|缴费|报送', clause)
                        and not re.search(r'未结束|尚未结束|未截止', clause)
                        and ((index == len(matches) - 1 and re.search(r'结束|落幕|完赛', suffix))
                             or re.search(r'(?:结束时间|结束日期|结束于|截止时间|截至|截止于)\s*(?:为|是)?\s*$', prefix))):
                    events.append(candidate)
                if re.search(r'有效期(?:至|截止|截至)|有效至', prefix):
                    policy_ends.append(candidate)
            if _COMPETITION.search(clause) and re.search(r'(?:已经|已)结束|已经落幕|已完赛', clause):
                ended_evidence = clause
            if not parsed and not _EXTENSION.search(clause):
                previous_registration = None
    registration = _select(extensions if extensions else registrations)
    registration['candidates'] = registrations
    event = _select(events)
    if ended_evidence and event['status'] == 'unknown':
        event.update(status='ended', evidence=ended_evidence)
    policy_expiry = _select(policy_ends)
    return {'competition': competition, 'registration_deadline': registration,
            'event_end': event, 'policy_expiry': policy_expiry,
            'policy_valid_evidence': next((m.group(0) for m in re.finditer(
                r'现行有效|长期有效|自发布之日起施行|自公布之日起施行', visible_text)), None),
            'policy_expired_evidence': next((m.group(0) for m in re.finditer(
                r'本(?:办法|规定|政策|指南|细则|通知)[^，,。；;\n]{0,40}(?:已废止|已失效|已过期|废止|失效)', visible_text)), None)}


# 展示期限：默认只收最近30天；演示环境可用 CAMPUS_VISIBILITY_DAYS 放宽。
MAX_AGE_DAYS = int(os.environ.get('CAMPUS_VISIBILITY_DAYS', '30'))


def evaluate_visibility(notice: dict, result: dict, *, now: datetime, first_seen: datetime | None = None) -> dict:
    """Return independent visibility/lifecycle labels without changing routing."""
    now = as_moment(now)
    # Result facts come only from this module's validated rule analysis. A
    # direct caller without facts receives an independent deterministic parse.
    facts = result.get('_temporal_facts') or extract_temporal_facts(notice, now=now)
    reg, event = facts['registration_deadline'], facts['event_end']
    reg_at, end_at = deadline_moment(reg), deadline_moment(event)
    event_expired = event['status'] == 'ended' or (end_at is not None and now > end_at)
    registration_status = ('closed' if now > reg_at else 'open') if reg_at else 'unknown'
    kind = result.get('classification', {}).get('document_kind')
    is_policy = kind == 'policy'
    policy_at = deadline_moment(facts['policy_expiry'])
    action = result.get('deadline', {})
    action_at = deadline_moment(action) if not action.get('year_inferred') else None
    validity = {'status': 'unknown', 'reason': '未确认有效期或活动结束时间', 'evidence': None}
    if is_policy:
        if facts['policy_expired_evidence'] or (policy_at and now > policy_at):
            validity.update(status='expired', reason='已有明确失效依据', evidence=facts['policy_expired_evidence'] or facts['policy_expiry']['evidence'])
        elif facts['policy_valid_evidence'] or (policy_at and now <= policy_at):
            validity.update(status='valid', reason='有明确有效依据', evidence=facts['policy_valid_evidence'] or facts['policy_expiry']['evidence'])
    elif event_expired:
        validity.update(status='expired', reason='比赛已结束', evidence=event['evidence'])
    elif end_at and now <= end_at:
        validity.update(status='valid', reason='比赛尚未结束', evidence=event['evidence'])
    elif facts['competition'] and registration_status == 'closed':
        validity.update(reason='报名已截止，尚无比赛结束依据', evidence=reg['evidence'])
    elif action_at:
        validity.update(status='valid' if now <= action_at else 'expired', reason='依据学生行动截止时间', evidence=action.get('evidence'))

    seen = first_seen if first_seen is not None else notice.get('first_seen_at')
    seen = as_moment(seen) if seen else None
    # first_seen records when a version was first admitted, not when this
    # calculation happens. A later lifecycle change must not evict it early.
    admitted_before_end = seen is not None and seen <= now and (end_at is None or seen <= end_at)
    hide_at = reg_at + timedelta(days=14) if facts['competition'] and reg_at else None
    admitted, status, reason = True, 'included', f'最近{MAX_AGE_DAYS}天内的学生通知'
    pending = notice.get('body_status') in ('title_only', 'partial')
    if result.get('relevance', {}).get('status') == 'irrelevant' or result.get('routing', {}).get('status') == 'excluded':
        admitted, status, reason = False, 'excluded', '明确与学生或当前用户无关'
    elif is_policy:
        if validity['status'] == 'expired':
            admitted, status, reason = False, 'excluded', '政策已有明确失效依据'
        elif validity['status'] == 'valid':
            reason = '有效政策不受发布日期限制'
        else:
            pending, status, reason = True, 'pending_confirmation', '政策有效性待确认，保留核对入口'
    elif hide_at:
        if event_expired and not admitted_before_end:
            admitted, status, reason = False, 'excluded', '首次发现时比赛已完全结束'
        else:
            reason = '比赛报名截止后保留14天，与报名状态分开'
            pending = pending or event['status'] in ('unknown', 'ambiguous')
    elif event_expired or (action_at and now > action_at):
        admitted, status, reason = False, 'excluded', '首次收录时事项已过期'
    elif action_at and now <= action_at:
        reason = '未过期事项不受发布日期限制'
    elif end_at and now <= end_at:
        reason = '尚未结束事项不受发布日期限制'
    elif reg['status'] == 'ambiguous' or action.get('status') == 'ambiguous':
        pending, status, reason = True, 'pending_confirmation', '日期存在冲突，展示期限待确认'
    else:
        published = notice.get('published_at')
        if not published:
            pending, status, reason = True, 'pending_confirmation', '发布日期未知，收录范围待确认'
        else:
            try:
                # The stated 30-day scope is a publication-date rule, including
                # the boundary date regardless of the scrape hour.
                age = (now.date() - as_moment(published).date()).days
            except (ValueError, TypeError):
                pending, status, reason = True, 'pending_confirmation', '发布日期无法确认'
            else:
                if age > MAX_AGE_DAYS:
                    admitted, status, reason = False, 'excluded', f'超过最近{MAX_AGE_DAYS}天，且无仍有效依据'
                elif age < 0:
                    pending, status, reason = True, 'pending_confirmation', '发布日期晚于当前日期，需核对'
    visible = admitted and not (hide_at is not None and now > hide_at)
    display_status = 'visible' if visible else 'hidden'
    if visible and (pending or status == 'pending_confirmation'):
        display_status = 'pending_confirmation'
        if status == 'included':
            status = 'pending_confirmation'
    if admitted and hide_at and now > hide_at:
        reason = '已超过比赛报名截止后14天展示期限'
    return {'visibility': {'visible': bool(visible), 'status': display_status, 'reason': reason,
                           'hide_at': hide_at.isoformat() if hide_at else None},
            'lifecycle': {'admitted': bool(admitted), 'admission_status': status, 'validity': validity,
                          'registration_status': registration_status, 'registration_deadline': deepcopy(reg),
                          'event_end': deepcopy(event), 'hide_at': hide_at.isoformat() if hide_at else None,
                          'evaluated_at': now.isoformat()}}
