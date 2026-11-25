"""Chinese Markdown view of the JSON contract; no independent decisions."""

from html import escape
import json


RELEVANCE = {"relevant": "对象匹配", "possible": "可能相关，待确认", "irrelevant": "明确不匹配"}
ROUTING = {"feed": "通知列表", "review": "待确认区域", "archive": "归档", "knowledge": "知识资料", "excluded": "排除展示"}
URGENCY = {"expired": "已过期", "today": "今日截止", "soon": "即将截止", "upcoming": "尚有时间", "unknown": "未知"}
DEADLINE = {"known": "已识别", "unknown": "未知", "ambiguous": "存在歧义，待确认"}
BODY = {"full": "完整正文", "partial": "部分正文", "title_only": "仅有标题"}
PRECISION = {"date": "仅日期（原文未指定具体时分）", "minute": "精确到分钟"}
DOCUMENT = {"news": "新闻报道", "application": "申请或报名", "result": "结果公示", "arrangement": "办理安排", "policy": "制度办法", "update": "变更通知", "unknown": "待确认"}
SOURCE = {"title": "标题", "content": "正文", "input": "结构化输入"}
FIELD = {"document_kind": "文档性质", "notice_type": "事项", "category": "类别", "school": "学校", "grades": "年级", "cohorts": "入学年份", "colleges": "学院", "majors": "专业", "campuses": "校区", "degrees": "学历层次"}
ROLE = {"student": "学生", "department": "学院或部门", "unknown": "待确认对象"}


def _text(value):
    if value is None or value == "" or value == [] or value == {}:
        return "未提供"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    value = escape(str(value), quote=False).replace("\r", " ").replace("\n", "；")
    for character in ("\\", "`", "*", "_", "[", "]", "#", "|"):
        value = value.replace(character, "\\" + character)
    return value


def _label(mapping, value):
    return mapping.get(value, value or "未知")


def _list(lines, values, fallback="未提供"):
    for value in values or [fallback]:
        if isinstance(value, dict) and "text" in value:
            value = "{}：{}（来自{}）".format(_label(FIELD, value.get("field")), value["text"], _label(SOURCE, value.get("source")))
        lines.append("- " + _text(value))


def _constraints(values):
    parts = []
    for field, value in (values or {}).items():
        if isinstance(value, list):
            value = "、".join(str(item) for item in value)
        parts.append("{}：{}".format(_label(FIELD, field), value))
    return "；".join(parts) or "未提供"


def render_report(batch, *, fictional=False):
    """Return a readable report without treating absent data as a conclusion."""
    lines = ["# 校园通知分类报告", ""]
    if fictional:
        lines += ["> 演示数据全部为虚构，不代表任何学校现行通知。", ""]
    lines += ["计算时刻：{}；时区：{}。".format(_text(batch["generated_at"]), _text(batch["timezone"])), "",
              "规则版本：{}；输出格式版本：{}。".format(_text(batch["rules_version"]), _text(batch["schema_version"])), "",
              "有效通知 {} 条；处理失败 {} 条。等级和紧急程度分别展示；对象匹配不等于完整资格审核。".format(len(batch["results"]), len(batch["errors"])), ""]
    if batch["results"]:
        lines += ["## 结果总览", "", "| 序号 | 标题 | 类别 | 等级 | 截止 | 处理去向 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for item in batch["results"]:
            importance = item["importance"]
            level = "待确认" if importance["level"] is None else "第 {} 级".format(importance["level"])
            if importance.get("tentative"):
                level += "（初判）"
            deadline = item["deadline"]
            cutoff = _text(deadline.get("value")) if deadline.get("status") == "known" else "待确认"
            if deadline.get("precision") == "date":
                cutoff += "（仅日期，未指定具体时分）"
            lines.append("| {} | {} | {} | {} | {} | {} |".format(
                item["rank"], _text(item["title"]), _text(item["classification"].get("category_label")),
                level, cutoff, _label(ROUTING, item["routing"].get("status"))))
        lines.append("")
    for item in batch["results"]:
        classification = item["classification"]
        importance = item["importance"]
        relevance = item["relevance"]
        deadline = item["deadline"]
        routing = item["routing"]
        level = "待确认" if importance["level"] is None else "第 {} 级".format(importance["level"])
        if importance.get("tentative"):
            level += "（初判）"
        lines += ["## {}. {}".format(item["rank"], _text(item["title"])), "",
                  "- 编号：{}".format(_text(item["notice_id"])),
                  "- 来源：{}；原始地址：{}".format(_text(item.get("source")), _text(item.get("source_url"))),
                  "- 发布时间：{}；正文状态：{}".format(_text(item.get("published_at")), _text(_label(BODY, item.get("body_status")))),
                  "- 类别：{}".format(_text(classification.get("category_label"))),
                  "- 事项：{}；文档性质：{}".format(_text(classification.get("type_label")), _text(_label(DOCUMENT, classification.get("document_kind")))),
                  "- 等级：{}；{}".format(level, _text(importance.get("label"))),
                  "- 时间：截止{}；{}；精度：{}".format(_label(DEADLINE, deadline.get("status")), _text(deadline.get("value")), _label(PRECISION, deadline.get("precision"))),
                  "- 紧急程度：{}；剩余小时：{}".format(_label(URGENCY, item["urgency"].get("status")), _text(item["urgency"].get("hours_remaining"))),
                  "- 受众：{}；明确条件：{}".format(_label(RELEVANCE, relevance.get("status")), _text(_constraints(relevance.get("constraints")))),
                  "- 路由：{}；{}".format(_label(ROUTING, routing.get("status")), _text(routing.get("reason"))),
                  "- 下游提醒候选：{}；已关注事项变更标记：{}（本程序不发送消息）".format("是" if routing.get("notify_eligible") else "否", "是" if routing.get("change_alert") else "否"),
                  "- 完整资格：未评估", "", "### 判断依据", "", "类别与事项：", ""]
        _list(lines, classification.get("evidence"))
        lines += ["", "重要等级：", ""]
        _list(lines, importance.get("reasons"))
        lines += ["", "受众匹配：", ""]
        _list(lines, relevance.get("reasons"))
        _list(lines, relevance.get("evidence"), "未提供额外受众证据")
        lines += ["", "时间依据：", "", "- {}".format(_text(deadline.get("evidence")))]
        if deadline.get("year_inferred"):
            lines.append("- 截止年份由发布日期语境推定，原文未写明年份。")
        if deadline.get("candidates"):
            lines += ["", "候选时间（不等于已经确认的学生截止）：", ""]
            for candidate in deadline["candidates"]:
                lines.append("- {}：{}；依据：{}（来自{}）".format(
                    _label(ROLE, candidate.get("role")), _text(candidate.get("value")),
                    _text(candidate.get("evidence")), _label(SOURCE, candidate.get("source"))))
        lines += ["", "### 未知与待确认", ""]
        unknowns = list(item.get("uncertainties") or [])
        unknowns += relevance.get("warnings") or []
        unknowns += deadline.get("warnings") or []
        if deadline.get("status") != "known":
            unknowns.append("学生截止时间尚未确认；发布时间或活动时间不自动视为截止。")
        _list(lines, list(dict.fromkeys(unknowns)), "当前输入未记录额外未知项；完整申请资格仍未评估。")
        lines.append("")
    if batch["errors"]:
        lines += ["## 处理失败的输入", "", "数组下标从 0 开始；以下条目未生成分类结果。", ""]
        for error in batch["errors"]:
            lines.append("- 下标 {}；编号 {}：{}".format(error["index"], _text(error.get("notice_id")), _text(error["message"])))
        lines.append("")
    return "\n".join(lines) + "\n"
