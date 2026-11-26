package campus.app.core.ui

import campus.app.core.model.TimeWindowRow
import campus.app.core.model.WindowKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** 时间显示只做格式转换，不推算是否截止。 */
class DateDisplayTest {

    @Test
    fun `纯日期显示为中文日期`() {
        assertEquals("2026年11月8日", DateDisplay.format("2026-11-08"))
    }

    @Test
    fun `带时区时刻显示到分钟`() {
        assertEquals("2026年11月12日 17:00", DateDisplay.format("2026-11-12T17:00:00+08:00"))
    }

    @Test
    fun `空值保持为空`() {
        assertNull(DateDisplay.format(null))
        assertNull(DateDisplay.format("  "))
    }

    @Test
    fun `窗口起止按单端与区间显示`() {
        val range = TimeWindowRow(id = "w1", kind = WindowKind.REGISTRATION, start = "2026-11-10", end = "2026-11-20")
        assertEquals("2026年11月10日 至 2026年11月20日", DateDisplay.window(range))

        val deadline = TimeWindowRow(id = "w2", kind = WindowKind.SUBMISSION, end = "2026-11-25")
        assertEquals("截至 2026年11月25日", DateDisplay.window(deadline))

        val startOnly = TimeWindowRow(id = "w3", kind = WindowKind.EVENT, start = "2026-12-06")
        assertEquals("自 2026年12月6日", DateDisplay.window(startOnly))
    }

    @Test
    fun `明示长期与待确认分开显示`() {
        val longTerm = TimeWindowRow(id = "w4", explicitLongTerm = true)
        assertEquals("长期有效", DateDisplay.window(longTerm))

        val uncertain = TimeWindowRow(id = "w5", verified = false)
        assertEquals("时间待确认", DateDisplay.window(uncertain))

        val noDeadline = TimeWindowRow(id = "w6", verified = true)
        assertEquals("时间未注明", DateDisplay.window(noDeadline))
    }
}
