package campus.app.core.data

import campus.app.TestResources
import campus.app.core.model.BodyStatus
import campus.app.core.model.Category
import campus.app.core.network.JsonKit
import campus.app.core.network.Mappers
import campus.app.core.network.int
import campus.app.core.network.obj
import campus.app.core.network.objList
import campus.app.core.network.str
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * MOCK 场景自检：`assets/mock/scenario.json` 的每个页面都必须按契约解析成功，
 * 并且覆盖首版要求的关键展示边界（四档收益、待确认收益、仅标题、有更新、关注顺序）。
 * 这里读取的是同一份文件的测试副本 `src/test/resources/fixtures/scenario.json`。
 */
class MockScenarioTest {

    private val root = TestResources.scenario()

    @Test
    fun `目录与资料按契约形状解析`() {
        val catalog = root.obj("catalog")!!
        val schools = Mappers.catalogPage(catalog.obj("schools")!!)
        assertEquals(1, schools.items.size)

        val grades = Mappers.grades(catalog.obj("grades")!!)
        assertEquals(4, grades.size)
        assertEquals(1, grades[0].value)

        val profile = Mappers.profileResponse(root.obj("profile")!!)
        assertTrue(profile.completed)
        assertEquals(3L, profile.version)
        assertEquals(2, profile.profile!!.grade)
        assertNull("样例中专业大类为待确认", profile.profile!!.majorGroupName)

        val preferences = Mappers.preferences(root.obj("preferences")!!)
        assertEquals(2L, preferences.version)
        assertEquals(2, preferences.skillIds.size)
    }

    @Test
    fun `三个 Tab 都有样例且数量符合场景定义`() {
        val feed = root.obj("feed")!!
        Category.tabs.forEach { category ->
            val page = Mappers.noticePage(feed.obj(category.wire)!!)
            assertTrue("${category.wire} 应有样例", page.items.isNotEmpty())
            assertEquals(
                when (category) {
                    Category.RESEARCH_INNOVATION -> 5
                    Category.FINANCIAL_AID -> 1
                    else -> 2
                },
                page.items.size,
            )
        }
    }

    @Test
    fun `科研样例按收益档顺序排列且每条都有日期标签`() {
        val page = Mappers.noticePage(root.obj("feed")!!.obj("research_innovation")!!)
        assertEquals(
            listOf("sample-001", "sample-002", "sample-003", "sample-004", "sample-005"),
            page.items.map { it.noticeId },
        )
        assertEquals(
            listOf("recommendation", "credit", "comprehensive", "volunteer", "none"),
            page.items.map { it.benefits.priorityTier.wire },
        )
        page.items.forEach { item ->
            assertTrue("${item.noticeId} 必须有日期标签", item.dateLabels.isNotEmpty())
            item.dateLabels.forEach { assertTrue(it.text.isNotBlank()) }
        }
    }

    @Test
    fun `首版关键边界样例齐全`() {
        val feed = root.obj("feed")!!
        val all = Category.tabs.flatMap { category ->
            Mappers.noticePage(feed.obj(category.wire)!!).items
        }
        assertTrue("需要一条仅标题", all.any { it.bodyStatus == BodyStatus.TITLE_ONLY })
        assertTrue("需要一条内容有更新", all.any { it.hasUpdate })
        assertTrue("需要一条收益待确认", all.any { it.hasPendingBenefit })
        assertTrue("需要一条期限未注明", all.any { item -> item.dateLabels.any { it.text.contains("期限未注明") } })
        assertTrue("需要一条时间待确认", all.any { item -> item.dateLabels.any { it.text.contains("时间待确认") } })
        assertTrue("需要一条结果公示状态", all.any { item -> item.statusLabels.isNotEmpty() })
        assertTrue("需要一条四档之外的收益待确认", all.any { it.benefits.priorityTier.wire == "none" })
    }

    @Test
    fun `每条样例的详情都能解析且 notice_id 一致`() {
        val details = root.obj("details")!!
        assertEquals(8, details.keys.size)
        details.keys.forEach { id ->
            val detail = checkNotNull(Mappers.detail(details.obj(id)!!)) { "$id 解析失败" }
            assertEquals(id, detail.item.noticeId)
            assertEquals(id, detail.item.follow.noticeId.ifBlank { id })
            assertTrue("${id} 缺少来源", detail.sources.isNotEmpty() || detail.sourceUrl != null)
        }
        val titleOnly = Mappers.detail(details.obj("sample-008")!!)!!
        assertNull(titleOnly.body)
        assertTrue(titleOnly.item.bodyIncomplete)

        val updated = Mappers.detail(details.obj("sample-007")!!)!!
        assertTrue(updated.item.hasUpdate)
    }

    @Test
    fun `关注样例按关注时间倒序且使用关注排序标识`() {
        val page = Mappers.noticePage(root.obj("follows")!!)
        assertEquals("follow-time-v1", page.rankingStrategyVersion)
        assertEquals(listOf("sample-001", "sample-006"), page.items.map { it.noticeId })
        page.items.forEach { assertTrue(it.follow.starred) }
        assertEquals(2, page.total)
    }

    @Test
    fun `样例场景自身是合法的 JSON 且标注为合成`() {
        assertTrue(root["synthetic"].toString() == "true")
        assertEquals("undergrad-app/2", root.str("contract_version"))
        assertEquals(8, root.obj("details")!!.keys.size)
    }
}
