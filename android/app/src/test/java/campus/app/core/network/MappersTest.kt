package campus.app.core.network

import campus.app.TestResources
import campus.app.core.model.AccessReason
import campus.app.core.model.Applicability
import campus.app.core.model.AttachmentStatus
import campus.app.core.model.BenefitType
import campus.app.core.model.BenefitVerificationState
import campus.app.core.model.BodyStatus
import campus.app.core.model.Category
import campus.app.core.model.DateGroup
import campus.app.core.model.EligibilityState
import campus.app.core.model.LifecycleState
import campus.app.core.model.PriorityTier
import campus.app.core.model.WindowKind
import campus.app.core.model.WindowState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 用后端共同契约里的**原样合成样例**验证 JSON → 模型映射。
 *
 * 两条不许退让的规则：
 * - 未知值落到 UNKNOWN / null，不用 0 或空串冒充；
 * - 字段缺失时保持为空，不伪造内容。
 */
class MappersTest {

    @Test
    fun `首页列表按契约解析并保留未知与待确认`() {
        val page = Mappers.noticePage(TestResources.json("feed-page.json"))
        assertEquals("undergrad-app/2", page.contractVersion)
        assertEquals(1, page.total)
        assertEquals(1, page.items.size)

        val item = page.items[0]
        assertEquals("sample-title-only", item.noticeId)
        assertEquals(Category.UNKNOWN, item.category)
        assertTrue("契约允许 unknown 作为待确认容器", item.categoryPending)
        assertEquals(BodyStatus.TITLE_ONLY, item.bodyStatus)
        assertEquals(AccessReason.LOGIN_REQUIRED, item.accessReason)
        assertEquals(LifecycleState.UNKNOWN, item.lifecycle.state)
        assertTrue(item.lifecycle.homeVisible)
        assertEquals(0L, item.follow.version)
        assertFalse(item.follow.starred)
        assertEquals("sample-title-facts-1", item.evaluationContext.factsVersion)
        assertEquals(1, item.uncertainties.size)
    }

    @Test
    fun `日期标签保留分组与文本，不由前端解析`() {
        val item = Mappers.noticePage(TestResources.json("follow-page.json")).items[0]
        assertEquals(1, item.dateLabels.size)
        val label = item.dateLabels[0]
        assertEquals(DateGroup.HANDLING, label.group)
        assertEquals("报名已截止（10月10日 17:00）", label.text)
        assertEquals(WindowState.CLOSED, label.state)
        assertEquals("报名已截止（10月10日 17:00）", item.dateLabelsByGroup().first().second[0].text)
    }

    @Test
    fun `收益不只给标签，还保留类型与适用性`() {
        val page = Mappers.noticePage(TestResources.json("follow-page.json"))
        val benefits = page.items[0].benefits
        assertEquals(PriorityTier.VOLUNTEER, benefits.priorityTier)
        assertEquals(2, benefits.items.size)
        val volunteer = benefits.items[0]
        assertEquals(BenefitType.VOLUNTEER_HOURS, volunteer.type)
        assertEquals(BenefitVerificationState.CONFIRMED, volunteer.verification)
        assertEquals(Applicability.APPLICABLE, volunteer.applicability)
        assertTrue(volunteer.confirmedForUser)
        val credit = benefits.items[1]
        assertEquals(BenefitType.INNOVATION_CREDIT, credit.type)
        assertEquals(BenefitVerificationState.PENDING, credit.verification)
        assertEquals(Applicability.UNKNOWN, credit.applicability)
        assertFalse("待确认/未知适用的收益不能当作已确认", credit.confirmedForUser)
    }

    @Test
    fun `面向群体与文件状态独立解析`() {
        val item = Mappers.noticePage(TestResources.json("follow-page.json")).items[0]
        assertEquals(1, item.audienceLabels.size)
        assertEquals("虚构大学本科生", item.audienceLabels[0].text)
        assertTrue(item.statusLabels.isEmpty())
        assertEquals(EligibilityState.UNKNOWN, item.match.eligibility)
    }

    @Test
    fun `时间窗口保留用途、精度与核验状态`() {
        val item = Mappers.noticePage(TestResources.json("follow-page.json")).items[0]
        val window = item.timeWindows[0]
        assertEquals(WindowKind.REGISTRATION, window.kind)
        assertEquals("报名", window.kindText)
        assertEquals("2026-10-01", window.start)
        assertEquals("2026-10-10T17:00:00+08:00", window.end)
        assertTrue(window.verified)
        assertEquals(WindowState.CLOSED, window.state)
        assertEquals("虚构大学本科生", window.audienceText)
        assertTrue(window.studentAction)
    }

    @Test
    fun `正文部分取得时详情保留正文、分段、附件与政策证据`() {
        val detail = checkNotNull(Mappers.detail(TestResources.json("notice-detail-partial.json")))
        assertEquals(BodyStatus.PARTIAL, detail.item.bodyStatus)
        assertTrue(detail.body!!.contains("志愿时长"))
        assertEquals(1, detail.segments.size)
        assertEquals(2, detail.attachments.size)
        assertEquals(AttachmentStatus.RESTRICTED, detail.attachments[0].status)
        assertEquals(AttachmentStatus.FAILED, detail.attachments[1].status)
        assertEquals(1, detail.policyReferences.size)
        assertEquals("【合成】创新学分认定办法", detail.policyReferences[0].title)
        assertEquals(4, detail.evidenceRefs.size)
        // content_version 落后于 latest_version：必须能识别"展示的是旧版本"。
        assertTrue(detail.item.hasUpdate)
        assertTrue(detail.staleBody)
        assertEquals("【合成】虚构大学实验设计竞赛", detail.item.title)
    }

    @Test
    fun `仅标题时正文为 null 且不伪造正文`() {
        val detail = checkNotNull(Mappers.detail(TestResources.json("notice-detail-title-only.json")))
        assertNull(detail.body)
        assertTrue(detail.segments.isEmpty())
        assertEquals(BodyStatus.TITLE_ONLY, detail.item.bodyStatus)
        assertTrue(detail.item.bodyIncomplete)
        assertEquals(AccessReason.LOGIN_REQUIRED, detail.item.accessReason)
        assertFalse(detail.staleBody)
    }

    @Test
    fun `关注状态按 64 位版本解析`() {
        val follow = Mappers.follow(TestResources.json("follow-state.json"))
        assertEquals("sample-competition", follow.noticeId)
        assertTrue(follow.starred)
        assertEquals(2L, follow.version)
        assertEquals("2026-10-03T15:20:00+08:00", follow.followedAt)
    }

    @Test
    fun `错误信封解析出 code、message、request_id 与字段`() {
        val body = Mappers.errorEnvelope(TestResources.json("validation-error.json"))
        assertEquals("validation_error", body.code)
        assertTrue(body.message!!.isNotBlank())
        assertTrue(body.requestId!!.isNotBlank())
        assertTrue(body.fields.isNotEmpty())
    }

    @Test
    fun `未知类别与未知正文状态降级而不崩溃`() {
        val page = Mappers.noticePage(
            JsonKit.parseObject(
                """
                {"items":[
                  {"notice_id":"a","title":"A","category":"competition","body_status":"weird"},
                  {"notice_id":"b","title":"B","category":"policy"}
                ]}
                """.trimIndent(),
            )!!,
        )
        assertEquals(Category.UNKNOWN, page.items[0].category)
        assertEquals(BodyStatus.UNKNOWN, page.items[0].bodyStatus)
        assertEquals(Category.UNKNOWN, page.items[1].category)
        assertTrue("契约 unknown 自动成为待确认", page.items[1].categoryPending)
    }

    @Test
    fun `缺字段时保持空而不是补默认值`() {
        val page = Mappers.noticePage(JsonKit.parseObject("""{"items":[{"notice_id":"n1","title":"标题"}]}""")!!)
        val item = page.items[0]
        assertTrue(item.dateLabels.isEmpty())
        assertTrue(item.timeWindows.isEmpty())
        assertTrue(item.benefitLabels.isEmpty())
        assertTrue(item.audienceLabels.isEmpty())
        assertEquals(BodyStatus.UNKNOWN, item.bodyStatus)
        assertEquals(0, page.total)
        assertNotEquals("undergrad-app/2", page.contractVersion)
    }
}
