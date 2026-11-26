"""Category refinements for product v3, without changing legacy v1/v2 rules."""

import re

from .product_context import reading_text, student_category_override
from .rule_baseline import classify_notice
from .rule_labels import Category

_PROGRAM = re.compile(r'科创班|实[验试]班|(?:拔尖|卓越)[^。；]{0,12}(?:培养班|培养计划|培养项目)|人才培养班')
_PROGRAM_STAGE = re.compile(r'招生|报名|选拔|录取|入围|面试|项目测试|考核|分流')
_STUDENT = re.compile(r'本科(?:生|学生)?|学生|同学|学员')
_COMPETITION = re.compile(r'竞赛|比赛|大赛|赛事')
_SPORT = re.compile(r'体育|体质|体能|运动会|田径|游泳|篮球|足球|排球|网球|羽毛球|乒乓球|定向越野|马拉松|长跑|跳绳')
_SPORT_EVENT = re.compile(r'比赛|大赛|竞赛|联赛|运动会|锦标赛|挑战赛|选拔赛|邀请赛|公开赛|接力赛')
_SPORT_WORK = re.compile(r'(?:科技|器材|会徽|海报|装备|产品|作品|标志|吉祥物).{0,10}设计|体育科技|作品(?:设计|征集|评选)')
_JUDGED_WORK = re.compile(r'(?:提交|征集|评审|评选).{0,18}(?:作品|设计方案|技术方案|研究成果)')
_ATHLETIC_RESULT = re.compile(r'运动员|运动成绩|跳远|跑步|田径项目|录取.{0,5}名次|(?:按|根据).{0,12}(?:用时|成绩|进球|积分).{0,9}(?:排名|录取|名次)')
_EXCLUSIVE_SPORT = re.compile(r'(?:本次(?:比赛|赛事)|参赛(?:对象|资格|人员))[^。；，,\n]{0,12}(?:仅限|仅面向)(?:本校|全校|在籍|在读|在校)*(?:研究生|硕士生|博士生|教职工)')
_UNDERGRAD_SPORT_ENTRY = re.compile(r'本科生(?:组|另设|可(?:以)?(?:报名|参赛|参加))|(?:面向|接受|欢迎)[^。；，,\n]{0,12}本科生')
_STAFF_PLAYERS = re.compile(r'(?:教职工|在职教师)[^。；，,\n]{0,10}(?:组队|报名参赛|组成代表队)|参赛(?:运动员|队员)[^。；，,\n]{0,12}(?:教职工|在职教师)')
_RESULT_NOTICE = re.compile(r'(?:结果|名单)公示|公示(?:结果|名单)|获奖公示')
_NEW_APPLICATION = re.compile(r'(?:报名|申请|申报)(?:通知|安排|更新|延期|入口|通道)')
_STUDENT_ENTRY = re.compile(
    r'(?:报名对象|参加对象)[:：]?[^。；\n]{0,24}(?:本科生|学生|同学|毕业生|师生)'
    r'|(?:面向|欢迎|招收|招募)[^。；\n]{0,24}(?:本科生|学生|同学|毕业生|师生)'
    r'[^。；,，\n]{0,12}(?:开放|报名|申请|参加|参与)'
    r'|(?:请|欢迎|可|须)[^。；\n]{0,32}(?:报名|提出异议|提出申诉|申请使用|预约场地)'
    r'|(?:本科生|学生|同学|毕业生)[^。；\n]{0,16}(?:可报名|可申请|可参加|自行报名|提交申请)'
    r'|报名(?:现已|即将|仍|继续|重新|再次)(?:开放|启动|开始)'
    r'|(?:报名|异议|申诉|复核)(?:时间|期限|截止|入口|方式)[:：]'
)
_DENIED_ENTRY = re.compile(r'不可|不能|不得|不再|不接受|无需|暂停|停止')
_UNIT_ORGANIZATION = re.compile(
    r'(?:各|各二级|有关|相关)(?:学院|单位|院系|部门)[^。；\n]{0,60}(?:组织|开展|邀请|制定)'
)
_ADMIN_REPORT = re.compile(r'工作台账|组织情况汇总|工作总结|材料报送|统一报送|活动筹备')
_EVENT_TOPIC = re.compile(r'活动|讲座|参观|培训|大会|竞赛|比赛|论坛|会议|分享会')
_RECAP_TITLE = re.compile(
    r'成功举办|圆满(?:举行|落幕|闭幕|结束)|顺利举办|载誉归来|喜报|赛后回顾|'
    r'活动回顾|工作纪实|来访交流|赴.*?调研|大会顺利召开|活动总结'
)
_PAST_EVENT = re.compile(
    r'(?:活动|讲座|参观|培训|大会|竞赛|比赛|论坛|会议)[^。；\n]{0,12}'
    r'(?:已(?:经)?(?:圆满|顺利)?(?:结束|举行|举办|闭幕)|圆满(?:结束|落幕)|落下帷幕)'
    r'|(?:举办了|举行了|开展了|参观了|走访了|召开了)[^。；\n]{0,30}'
    r'(?:活动|讲座|基地|培训|大会|竞赛|比赛|论坛|会议)'
)


def _has_student_entry(text: str) -> bool:
    return any(not _DENIED_ENTRY.search(match[0])
               and not re.search(r'不|无需|禁止', text[max(0, match.start() - 2):match.start()])
               for match in _STUDENT_ENTRY.finditer(text))


def classify_simple_notice(title: str, body: tuple[str, ...]) -> Category:
    """Apply narrowly scoped student-notice semantics before the legacy fallback."""
    title = reading_text(title)
    body = tuple(reading_text(part) for part in body)
    text = '\n'.join(body)
    active_notice = bool(_RESULT_NOTICE.search(title) or _NEW_APPLICATION.search(title)
                         or _has_student_entry(text))

    # A result or a new application remains actionable even when its title also
    # describes an ended activity. Other legacy exclusions still run unchanged.
    category_title = _RECAP_TITLE.sub('', title) if active_notice else title
    category = student_category_override(category_title, text) or classify_notice(category_title, body)
    if category == 'excluded':
        return category

    if not active_notice:
        if ('讲座' in title and _UNIT_ORGANIZATION.search(text) and _ADMIN_REPORT.search(text)):
            return 'excluded'
        if _EVENT_TOPIC.search(title) and _PAST_EVENT.search(text):
            return 'excluded'

    if category != 'financial_aid' and _SPORT.search(title) and _SPORT_EVENT.search(title):
        if '志愿者' in title and _has_student_entry(text):
            return 'daily'
        if '教职工' in title and _STAFF_PLAYERS.search(text) and not _UNDERGRAD_SPORT_ENTRY.search(text):
            return 'excluded'
        if _EXCLUSIVE_SPORT.search(text) and not _UNDERGRAD_SPORT_ENTRY.search(text):
            return 'excluded'
        if _SPORT_WORK.search(title) or _JUDGED_WORK.search(text):
            return 'research_innovation'
        if _ATHLETIC_RESULT.search(text):
            return 'daily'

    # The admission/testing of a teaching cohort is academic business; a
    # competition entered by that cohort is still a competition.
    if (_PROGRAM.search(title) and _PROGRAM_STAGE.search(title)
            and _STUDENT.search(title + text) and not _COMPETITION.search(title)):
        return 'daily'
    return category
