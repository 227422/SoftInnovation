"""Small evidence-based gate for unambiguously staff-only administrative work.

This is independent of content category and individual audience matching. A
mention of teachers, teaching or students alone never proves an exclusion.
"""
import re

VERSION = '1.0'
_STUDENT_TITLE = re.compile(r'学生|同学|师生|毕业生|奖学金|教师资格(?:考试|证考试)')
_STUDENT_ACTION = re.compile(
    r'(?:面向|欢迎|适用(?:于|对象)|申请对象)[^。；\n]{0,25}(?:学生|同学|毕业生|师生)'
    r'|(?:学生|同学|毕业生)[^。；\n]{0,15}(?:均可|可以|可申请|可报名|报名截止|申请截止)')
_STAFF_TRAVEL = re.compile(r'(?:教职工|职工|教师)[^。；\n]{0,12}(?:出国|出境|出访)[^。；\n]{0,12}(?:表格|手续|审批|交接|管理办法)')
_CLASSROOM_ENTRY = re.compile(r'课堂教学准入')
_TEACHER_APPLICATION = re.compile(r'教师\s*申请(?:授课|新上[^。；\n]{0,10}课程)|已获得[^。；\n]{0,15}教师资格证的教师')
_SYLLABUS_TEMPLATE = re.compile(r'教学大纲(?:格式|模板)')


def assess_student_scope(notice):
    """Return exclusion evidence, or no exclusion; never infer positive eligibility."""
    title = notice.get('title', '')
    content = notice.get('content', '') if notice.get('body_status') != 'title_only' else ''
    result = {'rules_version': VERSION, 'status': 'not_excluded',
              'reason': '未命中明确仅职工办理的事项；学生相关性仍由对象匹配判断', 'evidence': []}
    # Explicit student/joint involvement takes precedence over staff-work words.
    # Conflicting or mixed notices stay reviewable rather than dropping students.
    if _STUDENT_TITLE.search(title) or _STUDENT_ACTION.search(content):
        return result
    travel = _STAFF_TRAVEL.search(title)
    entry, teacher = _CLASSROOM_ENTRY.search(title), _TEACHER_APPLICATION.search(content)
    template = _SYLLABUS_TEMPLATE.search(title)
    if travel:
        reason = '明确为职工出国/出访手续或工作交接材料'
        evidence = [{'source': 'title', 'quote': travel.group(0)}]
    elif entry and teacher:
        reason = '明确为教师申请授课的课堂教学准入流程'
        evidence = [{'source': 'title', 'quote': entry.group(0)},
                    {'source': 'content', 'quote': teacher.group(0)}]
    elif template and all(word in content for word in ('大纲制订', '大纲审核', '大纲批准')):
        reason = '教学大纲编制审核模板，属于教学管理工作材料'
        evidence = [{'source': 'title', 'quote': template.group(0)}] + [
            {'source': 'content', 'quote': word} for word in ('大纲制订', '大纲审核', '大纲批准')]
    else:
        return result
    return {'rules_version': VERSION, 'status': 'excluded', 'reason': reason, 'evidence': evidence}


def apply_student_scope(notice, result):
    """Apply this shared content gate to one freshly computed rule result."""
    scope = assess_student_scope(notice)
    result['student_scope'] = scope
    if scope['status'] == 'excluded':
        result['routing'] = {'status': 'excluded', 'reason': scope['reason'],
                             'notify_eligible': False, 'change_alert': False}
        result['relevance']['status'] = 'irrelevant'
        result['relevance']['reasons'].append(scope['reason'])
    return scope
