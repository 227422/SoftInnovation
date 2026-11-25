"""V3 interpretation of people descriptions in schedule class columns."""

import re

from .product_labels import ProductScope

_PEOPLE = r'(?:本科生|硕士研究生|博士研究生|研究生|毕业生|留学生|学生|考生|同学|人员)'
_DESCRIPTION = re.compile(_PEOPLE + r'$')
_LIST_ITEM = re.compile(r'^\s*(?:[（(]?[\d一二三四五六七八九十]+[）).．、])\s*')
_DETAILS = re.compile(r'\d+\s*(?:学分|分|小时)|(?:英语|外语|大学英语)[四六]级|身份证|证件|申请材料')
_CORE = re.compile(r'((?:非)?\d{4}[级届](?:全日制|普通|在籍|在校)*' + _PEOPLE + r'|' + _PEOPLE + r')$')


def normalize_table_scope(scope: ProductScope) -> ProductScope:
    """Keep row pairings while separating described audiences from class names.

    Legacy table parsing owns the layout. This only changes v3's interpretation
    of a class cell; its original row evidence remains intact on the date label.
    """
    groups = []
    for group in scope.audience_groups:
        name = group.class_name
        if not name or not _DESCRIPTION.search(name):
            groups.append(group)
            continue
        for item in re.split(r'[；;\n]', name):
            item = _LIST_ITEM.sub('', item).strip()
            if not item:
                continue
            if _DESCRIPTION.search(item):
                audience = item
                # Numeric/material requirements stay in the row evidence.
                # Cohort negation and population descriptions remain explicit.
                if _DETAILS.search(item) and (core := _CORE.search(item)):
                    audience = core[1]
                groups.append(group.model_copy(update={'audience': audience, 'class_name': None}))
            else:
                groups.append(group.model_copy(update={'class_name': item}))
    return scope.model_copy(update={'audience_groups': tuple(dict.fromkeys(groups))})
