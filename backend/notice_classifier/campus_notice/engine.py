"""Deterministic notice decisions. No network, model, or account access."""
import copy
import json
import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .audience import match_audience
from .deadlines import extract_deadline


CST = timezone(timedelta(hours=8))
SCHEMA_VERSION = '1.0'


def _datetime(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('时间必须是 ISO 字符串或 datetime')
    if result.tzinfo is None:
        result = result.replace(tzinfo=CST)
    return result.astimezone(CST)


def _load_rules(path):
    try:
        rules = json.loads(Path(path or Path(__file__).with_name('rules.json')).read_text(encoding='utf-8'))
        if not isinstance(rules, dict) or not isinstance(rules.get('version'), str):
            raise ValueError('缺少规则版本')
        for section in ('categories', 'types'):
            entries = rules[section]
            if not isinstance(entries, list) or not entries:
                raise ValueError(section + ' 必须是非空数组')
            ids = set()
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item['id'], str) or not item['id']:
                    raise ValueError('规则缺少 id')
                if item['id'] in ids:
                    raise ValueError('规则 id 重复')
                ids.add(item['id'])
                if not isinstance(item['label'], str) or not item['label']:
                    raise ValueError('规则缺少中文名称')
                if section == 'types' and (type(item['level']) is not int or item['level'] not in (1, 2, 3, 4)):
                    raise ValueError('重要等级必须为 1 到 4')
                _validate_patterns(item['patterns'])
        category_ids = {item['id'] for item in rules['categories']}
        if any(item['category'] not in category_ids for item in rules['types']):
            raise ValueError('事项引用了不存在的类别')
        if not isinstance(rules.get('kinds'), dict) or not isinstance(rules.get('priorities'), dict):
            raise ValueError('kinds 和 priorities 必须是对象')
        for key in ('news', 'policy', 'result', 'update', 'application', 'arrangement'):
            _validate_patterns(rules['kinds'][key])
        for key in ('excluded_patterns', 'appeal_patterns', 'participation_required_patterns'):
            _validate_patterns(rules[key])
        if any(not isinstance(rules['priorities'].get(str(i)), str) for i in range(1, 5)):
            raise ValueError('缺少重要等级名称')
        return rules
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        raise ValueError('无法加载分类规则：' + str(exc)) from exc


def _validate_patterns(patterns):
    if not isinstance(patterns, list) or not patterns:
        raise ValueError('patterns 必须是非空数组')
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError('规则表达式必须是非空字符串')
        re.compile(pattern)


def _profile(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('学生资料必须是 JSON 对象')
    value = copy.deepcopy(value)
    for key in ('school', 'college', 'major', 'campus', 'degree'):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ValueError('学生资料 ' + key + ' 必须是非空字符串，未知请省略')
        if key in value:
            value[key] = value[key].strip()
    if 'grade' in value and (type(value['grade']) is not int or not 1 <= value['grade'] <= 8):
        raise ValueError('grade 必须为 1 到 8 的整数，未知请省略')
    if 'cohort' in value and (type(value['cohort']) is not int or not 1900 <= value['cohort'] <= 2200):
        raise ValueError('cohort 必须为入学年份整数')
    for key in ('followed_ids', 'participating_ids'):
        if key in value and (not isinstance(value[key], list) or
                             any(not isinstance(x, str) or not x.strip() for x in value[key])):
            raise ValueError(key + ' 必须是非空字符串组成的数组')
    return value


def _notice(value):
    if not isinstance(value, dict):
        raise ValueError('每条通知必须是 JSON 对象')
    value = copy.deepcopy(value)
    for key in ('id', 'title'):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(key + ' 必须为非空字符串')
        value[key] = value[key].strip()
    for key in ('content', 'source', 'source_url', 'school', 'event_id'):
        if key in value and not isinstance(value[key], str):
            raise ValueError(key + ' 必须是字符串')
        if key in value and key != 'content':
            value[key] = value[key].strip()
    value.setdefault('content', '')
    value.setdefault('source', '')
    value.setdefault('source_url', '')
    if value.get('published_at') is not None and value.get('published_at') != '':
        if not isinstance(value['published_at'], str):
            raise ValueError('published_at 必须是有效 ISO 日期或时间')
        try:
            _datetime(value['published_at'])
        except (ValueError, TypeError):
            raise ValueError('published_at 必须是有效 ISO 日期或时间')
    if value.get('body_status', 'full') not in ('full', 'title_only', 'partial'):
        raise ValueError('body_status 必须为 full、title_only 或 partial')
    value.setdefault('body_status', 'full' if value['content'].strip() else 'title_only')
    if not value['content'].strip():
        value['body_status'] = 'title_only'
    audience = value.get('audience')
    if audience is None:
        value.pop('audience', None)
    if audience is not None:
        if not isinstance(audience, dict):
            raise ValueError('audience 必须为 JSON 对象')
        for key in ('grades', 'cohorts', 'colleges', 'majors', 'campuses', 'degrees'):
            if key not in audience:
                continue
            entries = audience[key]
            if not isinstance(entries, list) or not entries:
                raise ValueError('audience.' + key + ' 必须是非空数组，未知请省略')
            for item in entries:
                if key in ('grades', 'cohorts'):
                    lower, upper = (1, 8) if key == 'grades' else (1900, 2200)
                    if type(item) is not int or not lower <= item <= upper:
                        raise ValueError('audience.' + key + ' 数值无效')
                elif not isinstance(item, str) or not item.strip():
                    raise ValueError('audience.' + key + ' 必须包含非空字符串')
    if 'deadline' in value and value['deadline'] is not None and not isinstance(value['deadline'], dict):
        raise ValueError('deadline 必须是含 value、role、evidence 的对象')
    return value


def _hit(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _active_appeal(text, patterns):
    for clause in re.split(r'[，,。；;\n！？!?]', text):
        if re.search(r'无异议|未收到.{0,6}异议|不(?:再)?受理|无需|已经?结束|已截止|已过期', clause):
            continue
        matched = _hit(patterns, clause)
        if matched:
            return matched
    return None


def _classify(notice, rules):
    title = notice['title']
    content = notice['content'] if notice['body_status'] != 'title_only' else ''
    full = title + '\n' + content
    kind = 'unknown'
    evidence = []
    # Document purpose is separate from subject; title is the strongest cue.
    for candidate in ('news', 'policy', 'result', 'update', 'application', 'arrangement'):
        matched = _hit(rules['kinds'][candidate], title)
        if matched:
            kind = candidate
            evidence.append({'field': 'document_kind', 'text': matched, 'source': 'title'})
            break
    selected = None
    for source, text in (('title', title), ('content', content)):
        for rule in rules['types']:
            matched = _hit(rule['patterns'], text)
            if matched:
                selected = rule
                evidence.append({'field': 'notice_type', 'text': matched, 'source': source})
                break
        if selected:
            break
    if kind == 'result':
        appeal = _active_appeal(full, rules['appeal_patterns'])
        if appeal:
            selected = {'id': 'appeal', 'label': '公示异议或申诉', 'level': 1,
                        'category': 'financial_aid' if '奖' in full or '资助' in full else 'student_affairs'}
            evidence.append({'field': 'notice_type', 'text': appeal,
                             'source': 'title' if appeal in title else 'content'})
        else:
            selected = {'id': 'result', 'label': '结果公示', 'level': 3,
                        'category': selected['category'] if selected else 'student_affairs'}
    scores = []
    for category in rules['categories']:
        score = 0
        for source, text, weight in (('title', title, 3), ('content', content, 1)):
            matched = _hit(category['patterns'], text)
            if matched:
                score += weight
                evidence.append({'field': 'category', 'text': matched, 'source': source})
        if score:
            scores.append((score, category))
    scores.sort(key=lambda item: -item[0])
    categories = {c['id']: c for c in rules['categories']}
    primary = (selected['category'] if selected else
               scores[0][1]['id'] if scores else 'unknown')
    tags = [item[1]['id'] for item in scores]
    if primary != 'unknown' and primary not in tags:
        tags.insert(0, primary)
    excluded = _hit(rules['excluded_patterns'], title)
    return ({'primary_category': primary,
             'category_label': categories[primary]['label'] if primary in categories else '待分类',
             'tags': tags,
             'notice_type': selected['id'] if selected else 'unknown',
             'type_label': selected['label'] if selected else '待确认事项',
             'document_kind': kind, 'evidence': evidence},
            selected['level'] if selected else None, excluded)


def _deadline_dt(deadline):
    if deadline['status'] != 'known' or not deadline['value']:
        return None
    if deadline['precision'] == 'date':
        return datetime.combine(date.fromisoformat(deadline['value']), time.max, tzinfo=CST)
    return _datetime(deadline['value'])


def _urgency(deadline, now):
    moment = _deadline_dt(deadline)
    if moment is None:
        return {'status': 'unknown', 'hours_remaining': None}
    hours = (moment - now).total_seconds() / 3600
    if hours < 0:
        status = 'expired'
    elif moment.date() == now.date():
        status = 'today'
    elif hours <= 72:
        status = 'soon'
    else:
        status = 'upcoming'
    return {'status': status, 'hours_remaining': round(hours, 2)}


def _analyze(notice, profile, now, rules):
    classification, level, excluded = _classify(notice, rules)
    relevance = match_audience(notice, profile)
    deadline = extract_deadline(notice, now)
    urgency = _urgency(deadline, now)
    identities = {notice['id'], notice.get('event_id', '')} - {''}
    participating = bool(identities.intersection(profile.get('participating_ids', [])))
    followed = bool(identities.intersection(profile.get('followed_ids', [])))
    if (participating or followed) and relevance['status'] != 'irrelevant':
        relevance['status'] = 'relevant'
        relevance['reasons'].append('用户已参与该事项' if participating else '用户已关注该事项')
    reasons = ['事项类型：' + classification['type_label']] if level else ['无法识别具体事项，需确认']
    text = notice['title'] + '\n' + (notice['content'] if notice['body_status'] != 'title_only' else '')
    if participating and relevance['status'] != 'irrelevant' and classification['document_kind'] not in ('news', 'policy'):
        requirement = _hit(rules['participation_required_patterns'], text)
        if requirement:
            level = 1
            reasons.append('已参与事项涉及必要操作：' + requirement)
    uncertainty = list(relevance.get('warnings', [])) + list(deadline.get('warnings', []))
    if notice['body_status'] == 'title_only':
        uncertainty.append('仅根据公开标题初判，正文未读取；请查看官方原文。')
    elif notice['body_status'] == 'partial':
        uncertainty.append('正文或附件不完整，可能缺少适用条件与时间。')
    if relevance['status'] == 'possible':
        uncertainty.append('用户资料或通知对象不完整，相关性待确认。')
    if deadline['status'] != 'known':
        uncertainty.append('没有可确认的学生截止时间。')
    if level is None:
        uncertainty.append('当前规则未覆盖该事项类型。')
    tentative = notice['body_status'] != 'full' or relevance['status'] == 'possible' or level is None
    change = classification['document_kind'] == 'update'
    change_alert = bool(change and (followed or participating) and relevance['status'] != 'irrelevant' and not excluded)
    kind = classification['document_kind']
    if excluded or kind == 'news' or relevance['status'] == 'irrelevant':
        destination, why = 'excluded', ('与学生无关的事项：' + excluded if excluded else
                                       '新闻回顾不作为行动通知' if kind == 'news' else '不在用户适用范围内')
    elif kind == 'policy':
        destination, why = 'knowledge', '政策或办事指南保留为知识资料'
    elif urgency['status'] == 'expired' and not change_alert:
        destination, why = 'archive', '已过学生行动截止时间'
    elif level is None or notice['body_status'] != 'full':
        destination, why = 'review', '信息不完整或规则未覆盖，保留在待确认区域'
    else:
        destination, why = 'feed', '学生相关事项进入信息流'
    eligible = (destination == 'feed' and relevance['status'] == 'relevant' and
                not tentative and level is not None and (level < 4 or change_alert) and
                deadline['status'] != 'ambiguous' and not deadline.get('year_inferred', False))
    return {'notice_id': notice['id'], 'title': notice['title'], 'source': notice['source'],
            'source_url': notice['source_url'], 'published_at': notice.get('published_at'),
            'body_status': notice['body_status'], 'classification': classification,
            'relevance': relevance,
            'importance': {'level': level, 'label': rules['priorities'][str(level)] if level else '待确认',
                           'reasons': reasons, 'tentative': tentative},
            'deadline': deadline, 'urgency': urgency,
            'routing': {'status': destination, 'reason': why,
                        'notify_eligible': bool(eligible), 'change_alert': change_alert},
            'eligibility': {'status': 'not_evaluated', 'reason': '只匹配通知适用对象，不判断完整报名资格。'},
            'uncertainties': list(dict.fromkeys(uncertainty))}


def _sort_key(result):
    status = result['routing']['status']
    # Review items remain near their tentative importance rather than disappearing.
    group = 0 if status in ('feed', 'review') else {'knowledge': 1, 'archive': 2, 'excluded': 3}[status]
    deadline = _deadline_dt(result['deadline'])
    expiry = deadline.timestamp() if deadline else float('inf')
    published = _datetime(result['published_at']).timestamp() if result.get('published_at') else 0
    return (group, result['importance']['level'] or 5,
            0 if result['routing']['change_alert'] else 1, expiry,
            0 if result['relevance']['status'] == 'relevant' else 1,
            -published, result['notice_id'])


def analyze_batch(notices, profile=None, *, now=None, rules_path=None):
    """Return the versioned JSON-compatible batch contract; invalid items are isolated.

    Invalid batch/profile/rules raise ValueError. Naive ``now`` is interpreted in
    China Standard Time, independent of the computer's local timezone.
    """
    if not isinstance(notices, list):
        raise ValueError('notices 必须是通知对象数组')
    profile = _profile(profile)
    rules = _load_rules(rules_path)
    moment = _datetime(now) if now is not None else datetime.now(CST)
    results, errors, seen = [], [], set()
    for index, raw in enumerate(notices):
        try:
            item = _notice(raw)
            if item['id'] in seen:
                raise ValueError('通知 id 重复：' + item['id'])
            seen.add(item['id'])
            results.append(_analyze(item, profile, moment, rules))
        except (ValueError, TypeError) as exc:
            error_id = raw.get('id') if isinstance(raw, dict) else None
            errors.append({'index': index, 'notice_id': error_id if isinstance(error_id, str) else None,
                           'message': str(exc)})
    results.sort(key=_sort_key)
    for rank, result in enumerate(results, 1):
        result['rank'] = rank
    counts = Counter(result['routing']['status'] for result in results)
    return {'schema_version': SCHEMA_VERSION, 'rules_version': rules['version'],
            'generated_at': moment.isoformat(), 'timezone': 'Asia/Shanghai',
            'summary': {'input_count': len(notices), 'processed_count': len(results),
                        'error_count': len(errors),
                        'by_status': {key: counts[key] for key in ('feed', 'review', 'archive', 'knowledge', 'excluded')}},
            'results': results, 'errors': errors}
