package campus.app.integration

import campus.app.core.data.RealProfileRepository
import campus.app.core.model.PreferenceKind
import campus.app.core.model.ProfileEdit
import campus.app.core.model.ProfileResponse
import campus.app.core.model.Preferences
import campus.app.core.network.ApiClient
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.PersistentCookieJar
import campus.app.core.session.AuthGeneration
import campus.app.core.session.CsrfHolder
import campus.app.core.session.SessionRepositoryImpl
import campus.app.core.session.SessionState
import campus.app.core.storage.MemoryKeyValueStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import java.util.UUID

/**
 * 真实后端端到端集成测试（默认跳过）。
 *
 * 运行方式（后端在 127.0.0.1:8000 启动后）：
 * ```
 * gradlew.bat :app:testDebugUnitTest --tests "campus.app.integration.RealServerIntegrationTest" \
 *   -Dcampus.backend.url=http://127.0.0.1:8000 -Dorg.gradle.configuration-cache=false
 * ```
 * 不传 `campus.backend.url` 时整类跳过，普通 `testDebugUnitTest` 不依赖网络。
 *
 * 验证的是安卓**真实的网络层代码**（ApiClient + 会话 + Cookie/CSRF + 资料/偏好）与真实服务互通，
 * 而不是只测 MockWebServer。使用合成账号，不涉及真实学生数据。
 */
class RealServerIntegrationTest {

    private val baseUrl: String = System.getProperty("campus.backend.url").orEmpty()

    @Before
    fun requireBackend() {
        assumeTrue(
            "未传入 campus.backend.url，跳过真实后端集成测试",
            baseUrl.isNotBlank(),
        )
    }

    private data class Harness(
        val api: ApiClient,
        val session: SessionRepositoryImpl,
        val cookieJar: PersistentCookieJar,
        val csrf: CsrfHolder,
        val profile: RealProfileRepository,
    )

    private fun harness(): Harness {
        val store = MemoryKeyValueStore()
        val csrf = CsrfHolder(store)
        val cookieJar = PersistentCookieJar(store)
        val generation = AuthGeneration()
        val api = ApiClient(
            baseUrl = baseUrl,
            cookieJar = cookieJar,
            csrfProvider = { csrf.token },
            authGeneration = generation,
        )
        return Harness(
            api = api,
            session = SessionRepositoryImpl(api, cookieJar, csrf, generation),
            cookieJar = cookieJar,
            csrf = csrf,
            profile = RealProfileRepository(api),
        )
    }

    @Test
    fun `真实后端完成注册 会话 目录 资料 偏好 刷新 退出主链`() = runBlocking {
        val h = harness()
        val email = "android-it-${System.currentTimeMillis()}-${UUID.randomUUID().toString().take(8)}@example.com"
        val password = "integration-pass-123"

        // 1. 注册：201 + Set-Cookie + SessionView
        val registered = h.session.register(email, password)
        assertTrue("注册失败：$registered", registered is ApiResult.Success)
        val sessionView = (registered as ApiResult.Success).value
        assertTrue(sessionView.userId.isNotBlank())
        assertEquals(email, sessionView.email)
        assertTrue("必须持久保存会话 Cookie", !h.cookieJar.isEmpty())
        assertTrue("CSRF 令牌必须已保存", h.csrf.token != null)
        assertTrue(sessionView.expiresAtEpochSeconds > 1_600_000_000L)
        println("[IT] register ok userId=${sessionView.userId}")

        // 2. 新账号资料未填：completed=false / profile=null / version=0
        val empty = (h.profile.load() as ApiResult.Success).value
        assertEquals(ProfileResponse(completed = false, profile = null, version = 0L), empty)
        println("[IT] profile empty ok")

        // 3. 目录：学校 → 学院 → 专业 → 年级 → 偏好目录
        val schools = (h.profile.schools() as ApiResult.Success).value
        assertTrue("学校目录为空", schools.items.isNotEmpty())
        val school = schools.items.first()
        val colleges = (h.profile.colleges(school.id) as ApiResult.Success).value
        assertTrue("学院目录为空", colleges.items.isNotEmpty())
        val college = colleges.items.first()
        val majors = (h.profile.majors(school.id, college.id) as ApiResult.Success).value
        assertTrue("专业目录为空", majors.items.isNotEmpty())
        val major = majors.items.first()
        val grades = (h.profile.grades() as ApiResult.Success).value
        assertTrue("年级数量小于 1", grades.isNotEmpty())
        val grade = grades.first().value
        assertTrue("年级 value 必须是 1—8 的整数", grade in 1..8)
        println("[IT] catalog ok school=${school.name} college=${college.name} major=${major.name} grade=$grade")

        // 4. 偏好目录：课程可能为空且有 message；技能/目标/兴趣有选项
        val courseCatalog = (h.profile.preferenceOptions(PreferenceKind.COURSE) as ApiResult.Success).value
        println("[IT] course catalog size=${courseCatalog.items.size} message=${courseCatalog.message}")
        val skillCatalog = (h.profile.preferenceOptions(PreferenceKind.SKILL) as ApiResult.Success).value
        assertTrue("技能目录为空", skillCatalog.items.isNotEmpty())
        val skillId = skillCatalog.items.first().id

        // 5. 保存资料：版本放正文 expected_version=0
        val edit = ProfileEdit(
            schoolId = school.id,
            collegeId = college.id,
            majorId = major.id,
            grade = grade,
            admissionYear = 2026,
            admissionYearSpecified = true,
            educationStage = "undergraduate",
            expectedVersion = 0L,
        )
        val saved = h.profile.save(edit, h.profile.newIdempotencyKey())
        assertTrue("保存资料失败：$saved", saved is ApiResult.Success)
        val savedProfile = (saved as ApiResult.Success).value
        assertTrue(savedProfile.completed)
        assertEquals(1L, savedProfile.version)
        assertEquals(school.name, savedProfile.profile!!.schoolName)
        assertEquals(grade, savedProfile.profile!!.grade)
        assertEquals("undergraduate", savedProfile.profile!!.educationStage)
        println("[IT] profile saved version=${savedProfile.version}")

        // 6. 重读资料与版本一致
        val reread = (h.profile.load() as ApiResult.Success).value
        assertEquals(savedProfile.version, reread.version)
        assertEquals(savedProfile.profile!!.majorId, reread.profile!!.majorId)

        // 7. 版本冲突：用旧版本保存必须 409 version_conflict，不修改服务端
        val stale = h.profile.save(edit, h.profile.newIdempotencyKey())
        assertTrue("旧版本保存应失败", stale is ApiResult.Failure)
        assertTrue(
            "应为 version_conflict，实际 ${(stale as ApiResult.Failure).error}",
            stale.error == ApiError.VersionConflict,
        )
        println("[IT] version conflict ok")

        // 8. 偏好：初始 version=0，保存后 version 递增；资料版本不受影响
        val initialPreferences = (h.profile.loadPreferences() as ApiResult.Success).value
        assertEquals(0L, initialPreferences.version)
        val toSave = Preferences(
            courseIds = emptyList(),
            skillIds = listOf(skillId),
            goalIds = emptyList(),
            interestIds = emptyList(),
            version = initialPreferences.version,
        )
        val savedPreferences = h.profile.savePreferences(toSave, h.profile.newIdempotencyKey())
        assertTrue("保存偏好失败：$savedPreferences", savedPreferences is ApiResult.Success)
        val preferences = (savedPreferences as ApiResult.Success).value
        assertEquals(1L, preferences.version)
        assertEquals(listOf(skillId), preferences.skillIds)
        assertEquals(
            "偏好保存不改变资料版本",
            savedProfile.version,
            (h.profile.load() as ApiResult.Success).value.version,
        )
        println("[IT] preferences saved version=${preferences.version}")

        // 9. 刷新会话：不续期，返回原到期时间
        val refreshed = h.session.refresh()
        assertTrue("刷新失败：$refreshed", refreshed is ApiResult.Success)
        assertEquals(
            sessionView.expiresAtEpochSeconds,
            (refreshed as ApiResult.Success).value.expiresAtEpochSeconds,
        )
        println("[IT] refresh ok")

        // 10. 退出：204，本地 Cookie/CSRF 清理，之后会话失效
        h.session.logout()
        assertTrue(h.cookieJar.isEmpty())
        assertTrue(h.csrf.token == null)
        assertTrue(h.session.state.value is SessionState.LoggedOut)
        val afterLogout = h.session.restore()
        assertTrue(
            "退出后恢复应回到未登录，实际 $afterLogout 状态 ${h.session.state.value}",
            h.session.state.value is SessionState.LoggedOut,
        )
        println("[IT] logout ok")

        // 11. 历史真实响应：计划中的 v2 路由返回 request_rejected，不得被当作会话失效
        val v2 = h.api.notices("daily")
        assertTrue(v2 is ApiResult.Failure)
        assertNotEquals(ApiError.SessionInvalid, (v2 as ApiResult.Failure).error)
        println("[IT] v2 planned route classified as ${v2.error}")
    }

    @Test
    fun `错误分类在真实服务上正确`() = runBlocking {
        val h = harness()
        val email = "android-it-err-${System.currentTimeMillis()}-${UUID.randomUUID().toString().take(8)}@example.com"
        val password = "integration-pass-456"
        assertTrue(h.session.register(email, password) is ApiResult.Success)

        // 资料保存缺少正确版本 → 422（字段含 body.expected_version）
        val invalid = h.profile.save(
            ProfileEdit("csu", "missing", "missing", 1, expectedVersion = 999L),
            h.profile.newIdempotencyKey(),
        )
        assertTrue("应失败", invalid is ApiResult.Failure)
        val error = (invalid as ApiResult.Failure).error
        assertTrue("应是 404/422 类目录错误，实际 $error", error !is ApiError.SessionInvalid)

        // 偏好重复 ID → 422 validation_error
        val duplicate = h.profile.savePreferences(
            Preferences(skillIds = listOf("a", "a")),
            h.profile.newIdempotencyKey(),
        )
        assertTrue(duplicate is ApiResult.Failure)
        assertTrue(
            "重复 ID 应是校验错误，实际 ${(duplicate as ApiResult.Failure).error}",
            duplicate.error is ApiError.Validation,
        )

        h.session.logout()
    }
}
