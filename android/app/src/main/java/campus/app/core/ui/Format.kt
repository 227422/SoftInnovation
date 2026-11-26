package campus.app.core.ui

import campus.app.core.model.TimeWindowRow

/**
 * 时间显示。
 *
 * 后端给的是 ISO 8601 日期（YYYY-MM-DD）或带时区时刻（...T HH:mm +08:00），
 * 界面统一显示北京时间。**只做格式转换，不做"是否已截止"的推算**：
 * 截止状态由后端给的 state / date_labels 决定。
 */
object DateDisplay {

    private val datePattern = Regex("""^(\d{4})-(\d{2})-(\d{2})$""")
    private val dateTimePattern = Regex("""^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})""")

    /** "2026-11-08" → "2026年11月8日"；"2026-11-12T17:00:00+08:00" → "2026年11月12日 17:00"。 */
    fun format(raw: String?): String? {
        val value = raw?.trim().orEmpty()
        if (value.isEmpty()) return null
        datePattern.matchEntire(value)?.let { match ->
            val (year, month, day) = match.destructured
            return "${year}年${month.toInt()}月${day.toInt()}日"
        }
        dateTimePattern.find(value)?.let { match ->
            val (year, month, day, hour, minute) = match.destructured
            return "${year}年${month.toInt()}月${day.toInt()}日 ${hour}:${minute}"
        }
        return value
    }

    /** 发布时间：日期显示到日，带时刻显示到分钟。 */
    fun published(raw: String?): String = format(raw) ?: "发布时间未知"

    /** 时间窗口的起止描述，保留原文明示的单端与精度。 */
    fun window(w: TimeWindowRow): String {
        val start = format(w.start)
        val end = format(w.end)
        return when {
            w.explicitLongTerm -> "长期有效"
            start != null && end != null -> "$start 至 $end"
            end != null -> "截至 $end"
            start != null -> "自 $start"
            w.verified -> "时间未注明"
            else -> "时间待确认"
        }
    }
}
