"""Conservative, dependency-free extraction of evidenced student deadlines.

Date mentions are retained as candidates even when their role is unknown.  A
candidate becomes a usable deadline only when both its action and date are clear.
"""
import re
from datetime import date, datetime, timedelta, timezone


BEIJING = timezone(timedelta(hours=8))
_DATE = re.compile(
    r'(?<!\d)(?:(?P<cy>\d{4})年(?P<cm>\d{1,2})月(?P<cd>\d{1,2})日'
    r'|(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})(?!\d)'
    r'|(?P<m>\d{1,2})月(?P<d>\d{1,2})日)')
_WEEKDAY = re.compile(r'^\s*[（(]\s*(?:周|星期)[一二三四五六日天]\s*[）)]\s*')
_TIME = re.compile(
    r'^\s*T?\s*(?P<period>上午|下午|晚上|中午|凌晨|傍晚|晚|早)?\s*'
    r'(?:(?P<h>\d{1,2})[:：](?P<minute>\d{1,2})(?::(?P<second>\d{2}))?'
    r'(?P<zone>Z|[+-]\d{2}:\d{2})?'
    r'|(?P<ch>\d{1,2})[时点](?:(?P<cm>\d{1,2})分?)?)')
_ACTION = re.compile(r'报名|申请|申报|提交|递交|缴费|确认|补交|选课|退课|填报|登记|异议|申诉')
_STUDENT = re.compile(r'学生|同学|考生|申请人|报名者|参赛者|参与者')
_DEPARTMENT = re.compile(r'学生工作(?:办公室|处)|各?学院|各?系(?:部)?|各?单位|各?部门|辅导员|班主任|教务处|研究生院')
_CUTOFF = re.compile(r'截止|截至|最迟|不得晚于|不晚于|限于')


def _parse_input_value(value):
    """Accept an ISO date or timezone-aware ISO timestamp at minute precision."""
    if not isinstance(value, str):
        raise ValueError('时间不是字符串')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value).isoformat(), 'date'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('时间必须带时区')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.second:
        raise ValueError('秒级时间暂不支持')
    return parsed.astimezone(BEIJING).isoformat(timespec='seconds'), 'minute'


def _publication_date(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(BEIJING)
        return parsed.date()
    except (ValueError, OverflowError):
        return None


def _role(clause, date_start, date_end):
    """Use the local action's actor, never a source unit or mere recipient."""
    before = clause[:date_start]
    after = _WEEKDAY.sub('', clause[date_end:], count=1)
    after_time = _TIME.sub('', after, count=1)
    deadline = (bool(_CUTOFF.search(before))
                or bool(re.match(r'^\s*(?:为|是)?(?:学生|同学|考生|报名|申请|材料提交)?(?:截止|截至)', after_time))
                or (bool(_ACTION.search(clause) or re.search(r'汇总|报送', clause))
                    and bool(re.match(r'^\s*(?:之前|以前|前)', after_time))))
    if not deadline:
        return 'unknown'
    # An actor before the time is stronger than a recipient after the time.
    departments = list(_DEPARTMENT.finditer(before))
    actors = [(m.start(), 'student') for m in _STUDENT.finditer(before)
              if not any(unit.start() <= m.start() < unit.end() for unit in departments)]
    actors += [(m.start(), 'department') for m in departments
               if not re.search(r'(?:向|交至|提交至|报送至|送交|交到)\s*$', before[:m.start()])]
    if actors:
        return max(actors)[1]
    if re.search(r'汇总|报送', clause):
        return 'department'
    if _ACTION.search(clause):
        return 'student'
    return 'unknown'


def _date_value(match, tail, published):
    year = match.group('cy') or match.group('iy')
    month = match.group('cm') or match.group('im') or match.group('m')
    day = match.group('cd') or match.group('id') or match.group('d')
    inferred = year is None
    if inferred and published is None:
        return None, None, False, '日期未写年份，且无有效发布日期，需确认年份'
    try:
        parsed = date(int(year) if year else published.year, int(month), int(day))
    except ValueError:
        return None, None, False, '日期不合法，需核对原文'
    if inferred and not 0 <= (parsed - published).days <= 183:
        return None, None, False, '日期未写年份，与发布日期存在跨年或远期歧义，需确认年份'
    tail = _WEEKDAY.sub('', tail, count=1)
    clock = _TIME.match(tail)
    if clock:
        if re.match(r'[\d零一二三四五六七八九十半刻秒:：]', tail[clock.end():]):
            return None, None, inferred, '未支持或不完整的时分表达，需核对截止时间'
        if clock.group('period'):
            return None, None, inferred, '上午／下午等时段表达暂不解析，需确认准确时分'
        hour = int(clock.group('h') or clock.group('ch'))
        minute = int(clock.group('minute') or clock.group('cm') or 0)
        if clock.group('second') not in (None, '00'):
            return None, None, inferred, '秒级时间暂不支持，需确认截止时分'
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return None, None, inferred, '时分不合法或为24点表达，需核对截止时间'
        tz = BEIJING
        if clock.group('zone'):
            zone = clock.group('zone')
            if zone == 'Z':
                tz = timezone.utc
            else:
                sign = 1 if zone[0] == '+' else -1
                zh, zm = map(int, zone[1:].split(':'))
                if zh > 23 or zm > 59:
                    return None, None, inferred, '时区偏移不合法，需确认截止时间'
                tz = timezone(sign * timedelta(hours=zh, minutes=zm))
        value = datetime(parsed.year, parsed.month, parsed.day, hour, minute, tzinfo=tz)
        return value.astimezone(BEIJING).isoformat(timespec='seconds'), 'minute', inferred, None
    if re.match(r'^\s*(?:上午|下午|晚上|中午|凌晨|傍晚|晚|早|[零一二三四五六七八九十]+[时点])', tail):
        return None, None, inferred, '未支持的时间表达，需确认准确时分'
    return parsed.isoformat(), 'date', inferred, None


def extract_deadline(notice: dict, now: datetime) -> dict:
    """Return a deadline only when supported by a clear student-facing action.

    ``now`` is deliberately not used for year inference: a historical notice
    must not silently acquire the current year.  A missing year is inferred only
    from a valid publication date and a same-year date within the next 183 days.
    """
    result = {'status': 'unknown', 'value': None, 'precision': None,
              'source': None, 'evidence': None, 'year_inferred': False,
              'candidates': [], 'warnings': []}
    warnings = result['warnings']
    body_status = notice.get('body_status', 'full')
    texts = [('title', notice.get('title', ''))]
    if body_status == 'title_only':
        warnings.append('仅有标题，未使用正文或结构化截止字段，截止信息可能不完整')
    else:
        texts.append(('content', notice.get('content', '')))
        if body_status == 'partial':
            warnings.append('正文不完整，已识别截止仍需核对完整通知')
    published = _publication_date(notice.get('published_at'))
    for source, text in texts:
        if not isinstance(text, str):
            continue
        for clause in re.split(r'[，,。；;\n！？!?]', text):
            if not clause.strip():
                continue
            matches = list(_DATE.finditer(clause))
            if not matches and _CUTOFF.search(clause):
                warnings.append('出现截止表述但未识别出支持的明确日期，需核对原文')
            previous_role = 'unknown'
            for index, match in enumerate(matches):
                start = matches[index - 1].end() if index else 0
                end = matches[index + 1].start() if index + 1 < len(matches) else len(clause)
                local = clause[start:end]
                role = _role(local, match.start() - start, match.end() - start)
                if index and re.search(r'延至|延期至|延长至|顺延至|调整为', clause[start:match.start()]):
                    role = previous_role
                previous_role = role
                value, precision, inferred, issue = _date_value(match, clause[match.end():end], published)
                candidate = {'value': value, 'role': role, 'evidence': clause.strip(),
                             'source': source, 'precision': precision, 'year_inferred': inferred}
                if issue:
                    candidate['warning'] = issue
                    warnings.append(issue)
                result['candidates'].append(candidate)
    supplied = notice.get('deadline')
    if supplied is not None and body_status != 'title_only':
        if (not isinstance(supplied, dict) or supplied.get('role') != 'student'
                or not isinstance(supplied.get('evidence'), str) or not supplied['evidence'].strip()):
            warnings.append('结构化截止缺少学生角色或原文依据，未作为有效截止使用')
        else:
            try:
                value, precision = _parse_input_value(supplied.get('value'))
            except (ValueError, OverflowError) as exc:
                warnings.append('结构化截止无效：' + str(exc))
            else:
                result['candidates'].append({'value': value, 'role': 'student',
                    'evidence': supplied['evidence'].strip(), 'source': 'input',
                    'precision': precision, 'year_inferred': False})
    student = [c for c in result['candidates'] if c['role'] == 'student']
    known = [c for c in student if c['value'] is not None]
    values = {c['value'] for c in known}
    minute_candidates = [c for c in known if c['precision'] == 'minute']
    compatible = (len({c['value'][:10] for c in known}) == 1
                  and len({c['value'] for c in minute_candidates}) <= 1)
    if len(values) > 1 and not compatible:
        result['status'] = 'ambiguous'
        warnings.append('存在多个不同的学生截止时间，需核对适用事项或延期后的截止')
    elif known and len(known) != len(student):
        result['status'] = 'ambiguous'
        warnings.append('另有无法确定的学生截止候选，需核对后再使用')
    elif known:
        selected = minute_candidates[0] if minute_candidates else known[0]
        result.update({key: selected[key] for key in
                       ('value', 'precision', 'source', 'evidence', 'year_inferred')})
        result['status'] = 'known'
    result['warnings'] = list(dict.fromkeys(warnings))
    return result
