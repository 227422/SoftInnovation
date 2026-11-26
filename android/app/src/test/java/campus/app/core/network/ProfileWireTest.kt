package campus.app.core.network

import campus.app.core.model.PreferenceKind
import campus.app.core.model.ProfileEdit
import kotlinx.coroutines.test.runTest
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * 真实接口的线格式（wire format）测试。
 *
 * 重点验证后端交接时明确指出的三处修复：
 * 1. 资料/偏好保存的版本放 JSON **正文** `expected_version`，而不是 X-Expected-Version 头；
 * 2. 资料响应按 `{completed, profile, version}` 外层解析；
 * 3. 年级目录 value 是整数；目录 message 可为 null。
 */
class ProfileWireTest {

    private lateinit var server: MockWebServer
    private lateinit var api: ApiClient

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        api = ApiClient(
            baseUrl = server.url("/").toString().trimEnd('/'),
            cookieJar = CookieJar.NO_COOKIES,
            csrfProvider = { "csrf-token-1" },
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `资料保存把 expected_version 放正文并带幂等键与 CSRF`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(
                    """
                    {"completed":true,"version":6,"profile":{
                      "school_id":"s1","school_name":"示例大学","college_id":"c1","college_name":"计算机学院",
                      "major_id":"m1","major_name":"软件工程","grade":2,"version":6,
                      "education_stage":"undergraduate","admission_year":2025,"major_group":null}}
                    """.trimIndent(),
                ),
        )

        val edit = ProfileEdit(
            schoolId = "s1",
            collegeId = "c1",
            majorId = "m1",
            grade = 2,
            admissionYear = 2025,
            admissionYearSpecified = true,
            educationStage = "undergraduate",
            expectedVersion = 5L,
        )
        val result = api.saveProfile(edit, idempotencyKey = "key-12345678")
        assertTrue(result is ApiResult.Success)

        val profile = Mappers.profileResponse((result as ApiResult.Success).value)
        assertEquals(true, profile.completed)
        assertEquals(6L, profile.version)
        assertEquals("软件工程", profile.profile!!.majorName)
        assertEquals(2, profile.profile!!.grade)
        assertEquals(2025, profile.profile!!.admissionYear)
        assertEquals("undergraduate", profile.profile!!.educationStage)
        assertNull("major_group 为 null 时必须保留 null", profile.profile!!.majorGroupName)

        val request = server.takeRequest()
        assertEquals("PATCH", request.method)
        assertEquals("/v1/me/profile", request.path)
        assertEquals("key-12345678", request.getHeader("Idempotency-Key"))
        assertEquals("csrf-token-1", request.getHeader("X-CSRF-Token"))
        assertNull("业务版本不再放请求头", request.getHeader("X-Expected-Version"))

        val body = JsonKit.parseObject(request.body.readUtf8())!!
        assertEquals(5L, body.long("expected_version"))
        assertEquals(2, body.int("grade"))
        assertEquals(2025, body.int("admission_year"))
        assertEquals("undergraduate", body.str("education_stage"))
        assertEquals("s1", body.str("school_id"))
    }

    @Test
    fun `清空入学年份时显式发送 null`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"completed":true,"version":2,"profile":null}"""))
        val edit = ProfileEdit(
            schoolId = "s1",
            collegeId = "c1",
            majorId = "m1",
            grade = 1,
            admissionYear = null,
            admissionYearSpecified = true,
            educationStage = null,
            expectedVersion = 1L,
        )
        api.saveProfile(edit, "key-abcdefgh")

        val body = JsonKit.parseObject(server.takeRequest().body.readUtf8())!!
        assertTrue("必须显式携带 admission_year:null", body.containsKey("admission_year"))
        assertTrue(body.raw("admission_year") == null)
        assertTrue("education_stage 省略而不是传 null", !body.containsKey("education_stage"))
    }

    @Test
    fun `偏好保存提交四组数组与独立版本`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"course_ids":[],"skill_ids":["skill-a"],"goal_ids":[],"interest_ids":[],"version":4}""",
            ),
        )
        val result = api.savePreferences(
            courseIds = emptyList(),
            skillIds = listOf("skill-a"),
            goalIds = emptyList(),
            interestIds = emptyList(),
            expectedVersion = 3L,
            idempotencyKey = "pref-key-123",
        )
        assertTrue(result is ApiResult.Success)
        val preferences = Mappers.preferences((result as ApiResult.Success).value)
        assertEquals(4L, preferences.version)
        assertEquals(listOf("skill-a"), preferences.skillIds)

        val request = server.takeRequest()
        assertEquals("/v1/me/preferences", request.path)
        assertEquals("PATCH", request.method)
        assertEquals("pref-key-123", request.getHeader("Idempotency-Key"))
        val body = JsonKit.parseObject(request.body.readUtf8())!!
        assertEquals(3L, body.long("expected_version"))
        assertTrue(body.containsKey("course_ids"))
        assertTrue(body.containsKey("skill_ids"))
        assertTrue(body.containsKey("goal_ids"))
        assertTrue(body.containsKey("interest_ids"))
    }

    @Test
    fun `资料读取按 completed profile version 外层解析`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"completed":false,"profile":null,"version":0}""",
            ),
        )
        val result = api.myProfile()
        val response = (result as ApiResult.Success).value
        assertEquals(false, response.completed)
        assertNull(response.profile)
        assertEquals(0L, response.version)
    }

    @Test
    fun `年级目录 value 为整数`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"items":[{"value":1,"label":"1年级"},{"value":2,"label":"2年级"}]}"""),
        )
        val grades = (api.catalogGrades() as ApiResult.Success).value
        assertEquals(2, grades.size)
        assertEquals(1, grades[0].value)
        assertEquals("2年级", grades[1].label)
    }

    @Test
    fun `目录 message 可以是 null 也可以是说明文字`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"items":[],"message":null}"""))
        val empty = (api.catalogPreferences(PreferenceKind.COURSE) as ApiResult.Success).value
        assertTrue(empty.items.isEmpty())
        assertNull(empty.message)

        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"items":[],"message":"课程目录尚待核验，可跳过"}"""),
        )
        val pending = (api.catalogPreferences(PreferenceKind.COURSE) as ApiResult.Success).value
        assertTrue(pending.message!!.contains("尚待核验"))
    }

    @Test
    fun `422 错误带字段详情`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(422).setBody(
                """
                {"error":{"code":"validation_error","message":"输入内容不符合要求","request_id":"r-1",
                 "details":[{"field":"body.expected_version","type":"missing"}]}}
                """.trimIndent(),
            ),
        )
        val result = api.saveProfile(
            ProfileEdit("s", "c", "m", 1, expectedVersion = 0L),
            "key-12345678",
        )
        assertTrue(result is ApiResult.Failure)
        val error = (result as ApiResult.Failure).error
        assertTrue(error is ApiError.Validation)
        assertEquals(listOf("body.expected_version"), (error as ApiError.Validation).fields)
    }

    @Test
    fun `退出返回 204 无正文且不解析 JSON`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(204)
                .setHeader("Set-Cookie", "campus_session=; Path=/; Max-Age=0"),
        )
        val result = api.logout()
        assertTrue(result is ApiResult.Success)
        val request = server.takeRequest()
        assertEquals("/v1/auth/logout", request.path)
        assertEquals(0L, request.body.size)
        assertEquals("csrf-token-1", request.getHeader("X-CSRF-Token"))
    }

    @Test
    fun `刷新会话返回原到期时间`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"user":{"id":"u-1","email":"a@b.c"},"expires_at":4102444800,"csrf_token":"c-2"}""",
            ),
        )
        val session = (api.refreshSession() as ApiResult.Success).value
        assertEquals("u-1", session.userId)
        assertEquals(4102444800L, session.expiresAtEpochSeconds)
        assertEquals("c-2", session.csrfToken)
        val request = server.takeRequest()
        assertEquals("/v1/auth/refresh", request.path)
        assertEquals("csrf-token-1", request.getHeader("X-CSRF-Token"))
    }

    @Test
    fun `列表按分类拼查询参数`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"items":[]}"""))
        api.notices("daily", offset = 20, limit = 20)
        val request = server.takeRequest()
        assertEquals("/v1/me/notices", request.requestUrl!!.encodedPath)
        assertEquals("daily", request.requestUrl!!.queryParameter("category"))
        assertEquals("20", request.requestUrl!!.queryParameter("offset"))
    }

    @Test
    fun `不传分类时不带分类参数`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"items":[]}"""))
        api.notices(null, offset = 0, limit = 50)
        val request = server.takeRequest()
        assertEquals(null, request.requestUrl!!.queryParameter("category"))
    }

    @Test
    fun `关注写入提交目标状态而不是 toggle`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"notice_id":"n1","starred":true,"followed_at":"2026-11-09T21:00:00+08:00","version":3}"""),
        )
        val state = (api.putFollow("n1", starred = true, expectedVersion = 2L, idempotencyKey = "follow-key-1")
            .map { Mappers.follow(it, "n1") } as ApiResult.Success).value
        assertTrue(state.starred)
        assertEquals(3L, state.version)
        val request = server.takeRequest()
        val body = JsonKit.parseObject(request.body.readUtf8())!!
        assertEquals(true, body.bool("starred"))
        assertEquals(2L, body.long("expected_version"))
        assertTrue("绝不提交 toggle", !body.containsKey("toggle"))
        assertEquals("follow-key-1", request.getHeader("Idempotency-Key"))
    }

    @Test
    fun `未知路由 404 不当作会话失效`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody(
                """{"error":{"code":"request_rejected","message":"未知路由","request_id":"r-2"}}""",
            ),
        )
        val result = api.notices("daily")
        assertTrue(result is ApiResult.Failure)
        val error = (result as ApiResult.Failure).error
        assertTrue(error !is ApiError.SessionInvalid)
        assertTrue(!error.isSessionExpired)
    }
}
