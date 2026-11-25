package campus.app.core.network

import campus.app.core.ui.describe
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 用**真实后端服务**（undergrad-app/2，已实现 15 个 v1 操作）产生的脱敏响应验证解析。
 *
 * 响应由后端联调脚本实际 HTTP 请求取得，Cookie/CSRF 已脱敏；
 * 证明安卓解析与真实服务一致，而不只是与合成样例一致。
 * 来源与版本记录见 `docs/verification/`（后端仓库）。
 */
class RealBackendResponseTest {

    private fun real(name: String): JsonObject {
        val stream = javaClass.classLoader?.getResourceAsStream("real/$name")
            ?: error("缺少真实响应资源 real/$name")
        val text = stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        return JsonKit.parseObject(text) ?: error("real/$name 不是合法 JSON")
    }

    @Test
    fun `真实会话响应解析 user expires_at csrf_token`() {
        val session = Mappers.session(real("session.json"))
        assertTrue(session != null)
        assertTrue(session!!.userId.isNotBlank())
        assertTrue(session.email.contains("@"))
        assertTrue("expires_at 是整数 Unix 秒", session.expiresAtEpochSeconds > 1_600_000_000L)
        assertTrue(session.csrfToken.isNotBlank())
    }

    @Test
    fun `真实未填资料是 completed false profile null version 0`() {
        val response = Mappers.profileResponse(real("profile-empty.json"))
        assertFalse(response.completed)
        assertNull(response.profile)
        assertEquals(0L, response.version)
    }

    @Test
    fun `真实已保存资料按外层结构与整数年级解析`() {
        val response = Mappers.profileResponse(real("profile-after-save.json"))
        assertTrue(response.completed)
        val profile = response.profile!!
        assertEquals("csu", profile.schoolId)
        assertEquals(2, profile.grade)
        assertEquals("undergraduate", profile.educationStage)
        assertEquals(2026, profile.admissionYear)
        assertNull("当前无法唯一确认专业大类，必须保持 null", profile.majorGroupName)
        assertEquals(response.version, profile.version)
    }

    @Test
    fun `真实年级目录 value 是 1 到 8 的整数`() {
        val grades = Mappers.grades(real("grades.json"))
        assertEquals(8, grades.size)
        assertEquals(listOf(1, 2, 3, 4, 5, 6, 7, 8), grades.map { it.value })
        grades.forEach { assertTrue(it.label.isNotBlank()) }
    }

    @Test
    fun `真实学校目录带 message 与合成外的真实元数据`() {
        val page = Mappers.catalogPage(real("schools.json"))
        assertTrue(page.items.isNotEmpty())
        assertEquals("csu", page.items[0].id)
        assertNull("当前 message 为 null", page.message)
    }

    @Test
    fun `真实偏好初始为空且版本为 0`() {
        val preferences = Mappers.preferences(real("preferences-empty.json"))
        assertTrue(preferences.courseIds.isEmpty())
        assertTrue(preferences.skillIds.isEmpty())
        assertEquals(0L, preferences.version)
    }

    @Test
    fun `真实保存后的偏好带独立版本`() {
        val preferences = Mappers.preferences(real("preferences-saved.json"))
        assertTrue(preferences.version >= 1L)
        assertTrue(preferences.skillIds.isNotEmpty())
    }

    @Test
    fun `真实刷新会话不改变到期时间`() {
        val session = Mappers.session(real("session.json"))
        val refreshed = Mappers.session(real("refresh.json"))
        assertTrue(refreshed != null)
        assertEquals(session!!.expiresAtEpochSeconds, refreshed!!.expiresAtEpochSeconds)
    }

    @Test
    fun `真实错误：缺正文版本是 422 并指出字段`() {
        val error = real("errors/missing-expected-version.json")
        val body = Mappers.errorEnvelope(error)
        val decoded = ErrorDecoder.fromHttp(
            status = 422,
            code = body.code,
            message = body.message,
            requestId = body.requestId,
            fields = body.fields,
        )
        assertTrue(decoded is ApiError.Validation)
        assertTrue((decoded as ApiError.Validation).fields.contains("body.expected_version"))
    }

    @Test
    fun `真实错误：版本冲突与登录凭据错误分开`() {
        val conflict = Mappers.errorEnvelope(real("errors/version-conflict.json"))
        assertTrue(
            ErrorDecoder.fromHttp(409, conflict.code, conflict.message, conflict.requestId) is ApiError.VersionConflict,
        )
        val credentials = Mappers.errorEnvelope(real("errors/invalid-credentials.json"))
        assertTrue(
            ErrorDecoder.fromHttp(401, credentials.code, credentials.message, credentials.requestId)
                is ApiError.InvalidCredentials,
        )
        val sessionInvalid = Mappers.errorEnvelope(real("errors/session-invalid-after-logout.json"))
        assertTrue(
            ErrorDecoder.fromHttp(401, sessionInvalid.code, sessionInvalid.message, sessionInvalid.requestId).isSessionExpired,
        )
    }

    @Test
    fun `真实 planned 路由返回 request_rejected 而不是会话失效`() {
        listOf("planned-notices.json", "planned-notice-detail.json", "planned-follows.json", "planned-follow-write.json", "planned-coverage.json")
            .forEach { file ->
                val body = Mappers.errorEnvelope(real("errors/$file"))
                val decoded = ErrorDecoder.fromHttp(404, body.code, body.message, body.requestId)
                assertTrue("$file 不应被当作会话失效", !decoded.isSessionExpired)
                assertEquals("$file 是 request_rejected", ApiError.RequestRejected, decoded)
            }
    }

    @Test
    fun `真实错误按状态码与 code 分类且文案对用户可读`() {
        val cases = mapOf(
            "errors/email-in-use.json" to 409,
            "errors/school-not-supported.json" to 404,
            "errors/major-not-available.json" to 422,
            "errors/rate-limited.json" to 429,
            "errors/csrf-invalid.json" to 403,
        )
        cases.forEach { (file, status) ->
            val body = Mappers.errorEnvelope(real(file))
            val decoded = ErrorDecoder.fromHttp(status, body.code, body.message, body.requestId)
            assertTrue("$file 未识别为已知分类：$decoded", decoded !is ApiError.Unknown)
            assertTrue(decoded.describe().isNotBlank())
        }
        assertTrue(
            ErrorDecoder.fromHttp(409, "email_in_use") is ApiError.EmailInUse,
        )
        assertTrue(
            ErrorDecoder.fromHttp(403, "csrf_invalid") is ApiError.CsrfInvalid,
        )
    }
}
