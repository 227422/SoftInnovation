"""Conservative audience matching; this does not evaluate full eligibility.

Only structured fields and explicit audience clauses impose restrictions. A
publishing unit and incidental mentions are never audience restrictions.
"""
import re


_FIELDS = {
    'grades': ('grade', '年级'),
    'cohorts': ('cohort', '入学年份'),
    'colleges': ('college', '学院'),
    'majors': ('major', '专业'),
    'campuses': ('campus', '校区'),
    'degrees': ('degree', '学历层次'),
}
_GRADE_NUMBERS = dict(zip('一二三四五六七八12345678', list(range(1, 9)) * 2))
_AUDIENCE_CUE = re.compile(
    r'(?:报名|申请|招募|参加|参与|申报|评选|招聘|服务|适用)对象\s*[:：为是]?'
    r'|(?:仅)?面向|仅限|限定为'
)
_EXAMPLE = re.compile(r'示例|举例|例如|例\s*[:：]|假设|比如')
_PREFERENCE = re.compile(r'优先|优选|鼓励|推荐|欢迎')
_COMPLEX = re.compile(r'除[^，,。；;]+(?:外|以外)|但|并非|不含|不包括|不面向|不接受|不招收'
                      r'|条件之一|满足.*之一|或符合|视情况|原则上|以上|以下'
                      r'|[一二三四五六七八1-8](?:年级)?(?:至|到|—|～|~|-)(?:大)?[一二三四五六七八1-8]'
                      r'|非[^，,。；;]*(?:学院|专业|本科|研究生|硕士|博士)')
_QUALIFICATION = re.compile(r'成绩|排名|绩点|学分|获奖|资格|符合|满足|通过|证书|贫困|困难认定|党员|团员|年龄')
_DEGREES = {'本科生': '本科', '本科学生': '本科', '专科生': '专科', '专科学生': '专科',
            '硕士研究生': '硕士', '博士研究生': '博士', '硕士生': '硕士', '博士生': '博士'}


def _unique(values):
    return list(dict.fromkeys(values))


def _degree(value):
    return _DEGREES.get(value.strip(), value.strip())


def _matches(field, value, allowed):
    if field != 'degrees':
        return value in allowed
    normalized = _degree(value)
    choices = [_degree(item) for item in allowed]
    if normalized == '研究生' and '研究生' not in choices and any(item in ('硕士', '博士') for item in choices):
        return None
    return normalized in choices or (normalized in ('硕士', '博士') and '研究生' in choices)


def _extract_dimensions(text):
    """Read the supported simple vocabulary inside an audience clause."""
    result = {}
    grades = [_GRADE_NUMBERS[value] for value in re.findall(r'大([一二三四五六七八1-8])', text)]
    grades += [_GRADE_NUMBERS[value] for value in re.findall(r'(?<![\d一二三四五六七八])([一二三四五六七八1-8])年级', text)]
    short_lists = re.findall(r'大([一二三四五六七八1-8](?:[、和及或][一二三四五六七八1-8])+)', text)
    short_lists += re.findall(r'(?<![\d一二三四五六七八])([一二三四五六七八1-8](?:[、和及或][一二三四五六七八1-8])+)年级', text)
    grades += [_GRADE_NUMBERS[value] for group in short_lists for value in group if value in _GRADE_NUMBERS]
    if grades:
        result['grades'] = sorted(set(grades))
    cohort_lists = re.findall(r'(?<!\d)((?:(?:19|20)\d{2}级?\s*[、和或及]\s*)*(?:19|20)\d{2})级', text)
    cohorts = [int(value) for group in cohort_lists for value in re.findall(r'(?:19|20)\d{2}', group)]
    if cohorts:
        result['cohorts'] = _unique(cohorts)
    degrees = re.findall(r'硕士研究生|博士研究生|硕士生|博士生|本科(?:学生|生)?|专科(?:学生|生)?|研究生|硕士|博士', text)
    if degrees:
        result['degrees'] = _unique([_degree(value) for value in degrees])
    # Restrict institutional names to a leading list item. Otherwise prose such
    # as “由计算机学院负责” can be mistaken for an audience name.
    colleges = []
    campuses = []
    majors = []
    for item in re.split(r'[、，,]|以及|或|和|及', text):
        item = re.sub(r'^(?:全日制|在校|本校|我校|仅限|面向|仅|限|的)+', '', item.strip())
        college = re.match(r'([\u4e00-\u9fffA-Za-z]{2,16}学院)(?=本科|专科|研究生|硕士|博士|学生|同学|大[一二三四五六七八]|20\d{2}级|$)', item)
        if college and not re.search(r'负责|组织|承办|主办|来自|由|不限', college.group(1)):
            colleges.append(college.group(1))
        campus = re.match(r'([\u4e00-\u9fffA-Za-z]{1,12}校区)(?=本科|专科|研究生|硕士|博士|学生|同学|大[一二三四五六七八]|20\d{2}级|$)', item)
        if campus and not re.search(r'不限|各|所有', campus.group(1)):
            campuses.append(campus.group(1))
        major = re.match(r'([\u4e00-\u9fffA-Za-z]{2,20})专业(?:学生|同学|本科生|研究生)?$', item)
        if major and not re.search(r'不限|所有|相关|各|任何|全部', major.group(1)):
            majors.append(major.group(1))
    if colleges and not re.search(r'全校|各学院|不限学院', text):
        result['colleges'] = _unique(colleges)
    if campuses:
        result['campuses'] = _unique(campuses)
    if majors and '不限专业' not in text:
        result['majors'] = _unique(majors)
    return result


def _ambiguous_combination(text):
    # “及/和/与” can join distinct eligible populations, just like “或”. A
    # grade attached to one population must not constrain every population.
    parts = re.split(r'或者|或|以及|及|和|与', text)
    if len(parts) == 1:
        return False
    branch_values = [_extract_dimensions(part) for part in parts]
    dimensions = [set(values) for values in branch_values]
    if any(not dimension for dimension in dimensions):
        return True
    for index, (left, right) in enumerate(zip(dimensions, dimensions[1:])):
        if left and right and (not left.intersection(right) or (len(left) > 1 and len(right) > 1)):
            return True
        shared = left.intersection(right)
        if (left != shared or right != shared) and any(
            field not in ('grades', 'cohorts')
            and set(branch_values[index][field]) != set(branch_values[index + 1][field])
            for field in shared
        ):
            return True
    return False


def _text_constraints(text, source):
    found = {}
    evidence = []
    warnings = []
    broad_audience = False
    uncertain = False
    # Sentence boundaries contain the scope of “面向”; arbitrary later sentences
    # are not silently inherited into that scope.
    for sentence in re.split(r'[。！？!?；;\n]', text):
        cue = _AUDIENCE_CUE.search(sentence)
        if not cue:
            continue
        if _EXAMPLE.search(sentence):
            warnings.append('受众描述含示例或假设，未作为实际限制。')
            uncertain = True
            continue
        if re.search(r'去年|往年|上届|曾经|此前|过去', sentence[:cue.start()]):
            warnings.append('历史受众描述未作为本次限制。')
            uncertain = True
            continue
        # Keep modifiers before the cue: slicing after “面向” would otherwise
        # turn “优先面向” into an exclusive audience restriction.
        cue_prefix = re.split(r'[，,]', sentence[:cue.start()])[-1]
        if _PREFERENCE.search(cue_prefix):
            warnings.append('受众描述为优先或推荐范围，未作为硬性限制。')
            uncertain = True
            continue
        clause = sentence[cue.end():].strip(' ：:')
        if _COMPLEX.search(sentence) or _ambiguous_combination(clause):
            warnings.append('受众条件含例外或复杂组合，需人工确认。')
            uncertain = True
            continue
        if _QUALIFICATION.search(clause):
            warnings.append('通知还含资格条件；这里只匹配受众，完整资格待确认。')
            uncertain = True
        # Preference clauses are not hard restrictions. Removing a comma-sized
        # segment also prevents a preferred grade/degree from becoming one.
        hard_parts = [part for part in re.split(r'[，,]', clause) if not _PREFERENCE.search(part)]
        hard_clause = '，'.join(hard_parts)
        values = _extract_dimensions(hard_clause)
        if re.search(r'全校(?:学生|师生|同学|本科|专科|研究生|硕士|博士)|全体学生', hard_clause):
            broad_audience = True
        if not values and not broad_audience:
            uncertain = True
        for field, allowed in values.items():
            found[field] = _unique(found.get(field, []) + allowed)
            evidence.append({'field': field, 'text': sentence.strip(), 'source': source})
    return found, evidence, warnings, broad_audience, uncertain


def match_audience(notice: dict, profile: dict) -> dict:
    """Return relevant/possible/irrelevant plus constraints and cited evidence.

    Arrays within one dimension are alternatives; separate dimensions are all
    required. Missing profile fields never count as mismatches. ``title_only``
    ignores content and supplied audience, while source school remains usable.
    Callers validate input types before calling this function.
    """
    profile = profile or {}
    result = {'status': 'possible', 'reasons': [], 'constraints': {}, 'evidence': [], 'warnings': []}
    constraints = result['constraints']
    evidence = result['evidence']
    warnings = result['warnings']
    body_status = notice.get('body_status', 'full')
    uncertain = body_status in ('partial', 'title_only')
    if body_status == 'title_only':
        warnings.append('仅有标题：未使用正文和结构化受众，结果需确认。')
    elif body_status == 'partial':
        warnings.append('正文不完整，可能遗漏受众条件。')

    if notice.get('school'):
        constraints['school'] = notice['school']
        evidence.append({'field': 'school', 'text': notice['school'], 'source': 'input'})

    structured = notice.get('audience', {}) if body_status != 'title_only' else {}
    for field in _FIELDS:
        if structured.get(field):
            constraints[field] = _unique(structured[field])
            evidence.append({'field': field, 'text': '结构化受众：' + '、'.join(map(str, structured[field])), 'source': 'input'})

    broad_audience = False
    conflicting_fields = set()
    sources = [('title', notice.get('title', ''))]
    if body_status != 'title_only':
        sources.append(('content', notice.get('content', '')))
    for source, text in sources:
        parsed, cited, issues, broad, unclear = _text_constraints(text, source)
        warnings.extend(issues)
        uncertain = uncertain or unclear
        broad_audience = broad_audience or broad
        for field, values in parsed.items():
            if field in conflicting_fields:
                continue
            if field not in constraints:
                constraints[field] = values
                evidence.extend(item for item in cited if item['field'] == field)
            elif set(constraints[field]) != set(values):
                # Contradictory evidence cannot justify an exclusion. Preserve
                # its citations, but stop applying this dimension as a fact.
                uncertain = True
                warnings.append('受众描述存在不同范围，需确认：' + _FIELDS[field][1] + '。')
                del constraints[field]
                conflicting_fields.add(field)
                evidence.extend(item for item in cited if item['field'] == field)

    mismatches = []
    missing = []
    for field, allowed in constraints.items():
        profile_key, label = ('school', '学校') if field == 'school' else _FIELDS[field]
        value = profile.get(profile_key)
        if value is None or value == '':
            missing.append(label)
        else:
            matches = value == allowed if field == 'school' else _matches(field, value, allowed)
            if matches is None:
                missing.append(label + '（资料不够具体）')
            elif not matches:
                mismatches.append(label)
    if mismatches:
        result['status'] = 'irrelevant'
        result['reasons'].append('与明确受众限制不符：' + '、'.join(mismatches) + '。')
    elif missing:
        result['reasons'].append('缺少用于核对受众的个人资料：' + '、'.join(missing) + '。')
        warnings.append('个人资料未填写：' + '、'.join(missing) + '。')
    elif not profile:
        result['reasons'].append('尚无个人资料，无法确认受众匹配。')
        warnings.append('个人资料缺失。')
    elif not any(field in constraints for field in _FIELDS) and not broad_audience:
        result['reasons'].append('未识别到明确的受众范围，保留待确认。')
        warnings.append('未识别到明确受众；未据此判为无关。')
    elif uncertain:
        result['reasons'].append('已知受众条件未发现冲突，但信息仍需确认。')
    else:
        result['status'] = 'relevant'
        result['reasons'].append('个人资料符合已明确的受众范围；未评估完整报名资格。')
    result['warnings'] = _unique(warnings)
    return result
