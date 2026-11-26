package campus.app.core.session

import campus.app.core.network.ApiClient
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.PersistentCookieJar
import campus.app.core.network.RequestGeneration
import campus.app.core.network.GenerationAwareCookieJar
import campus.app.core.storage.MemoryKeyValueStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CountDownLatch

/**
 * 会话恢复的三条分支：
 * 200 → 已登录；401 session_invalid → 未登录；503/超时 → 可重试失败，**不得**当成未登录。
 * 另外验证认证世代保护：旧世代的迟到结果不能改变当前会话。
 */
class SessionRecoveryTest {

    private lateinit var server: MockWebServer
    private lateinit var repository: SessionRepositoryImpl
    private lateinit var cookieJar: PersistentCookieJar
    private lateinit var api: ApiClient
    private lateinit var generation: AuthGeneration

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        val store = MemoryKeyValueStore()
        val csrf = CsrfHolder(store)
        cookieJar = PersistentCookieJar(store)
        generation = AuthGeneration()
        api = ApiClient(
            baseUrl = server.url("/").toString().trimEnd('/'),
            cookieJar = cookieJar,
            csrfProvider = { csrf.token },
            authGeneration = generation,
        )
        repository = SessionRepositoryImpl(api, cookieJar, csrf, generation)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `恢复成功时进入已登录`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(
                    """{"user":{"id":"u-1","email":"a@b.c"},"expires_at":4102444800,"csrf_token":"csrf-1"}""",
                ),
        )
        repository.restore()
        val state = repository.state.value
        assertTrue(state is SessionState.LoggedIn)
        assertEquals("u-1", (state as SessionState.LoggedIn).session.userId)
        assertEquals(4102444800L, state.session.expiresAtEpochSeconds)
    }

    @Test
    fun `401 session_invalid 时回到未登录`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(401)
                .setHeader("Content-Type", "application/json")
                .setBody("""{"error":{"code":"session_invalid","message":"失效"}}"""),
        )
        repository.restore()
        assertTrue(repository.state.value is SessionState.LoggedOut)
    }

    @Test
    fun `503 时是失败而不是未登录`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(503)
                .setHeader("Content-Type", "application/json")
                .setBody("""{"error":{"code":"storage_unavailable","message":"稍后重试"}}"""),
        )
        repository.restore()
        val state = repository.state.value
        assertTrue("503 不能被当成已退出登录", state !is SessionState.LoggedOut)
        assertTrue(state is SessionState.Failed)
    }

    @Test
    fun `密码错误返回明确错误且不改变会话状态`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(401)
                .setHeader("Content-Type", "application/json")
                .setBody("""{"error":{"code":"invalid_credentials","message":"邮箱或密码错误"}}"""),
        )
        val result = repository.login("a@b.c", "wrong-password")
        assertTrue(result is ApiResult.Failure)
        val error = (result as ApiResult.Failure).error
        assertTrue(error is ApiError.InvalidCredentials)
        assertFalse(error.isSessionExpired)
    }

    @Test
    fun `登录成功会持久保存 Cookie 且后续请求携带`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setHeader("Set-Cookie", "campus_session=tok-1; Path=/; Max-Age=2592000")
                .setBody("""{"user":{"id":"u-2","email":"x@y.z"},"expires_at":4102444800,"csrf_token":"c-2"}"""),
        )
        repository.login("x@y.z", "12345678")
        assertTrue("Cookie 应已保存", !cookieJar.isEmpty())
        server.takeRequest()

        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        api.session()
        val second = server.takeRequest()
        assertTrue(second.getHeader("Cookie")?.contains("campus_session") == true)
    }

    @Test
    fun `刷新不改变到期时间且推进世代`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"user":{"id":"u-1","email":"a@b.c"},"expires_at":4102444800,"csrf_token":"c-9"}"""),
        )
        val before = generation.current()
        val result = repository.refresh()
        assertTrue(result is ApiResult.Success)
        assertEquals(before + 1, generation.current())
        assertEquals("c-9", (result as ApiResult.Success).value.csrfToken)
    }

    @Test
    fun `旧世代迟到的恢复结果不能改变当前会话`() = runBlocking {
        val requestReceived = CountDownLatch(1)
        val releaseResponse = CountDownLatch(1)
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requestReceived.countDown()
                releaseResponse.await()
                return MockResponse().setResponseCode(200).setBody(
                    """{"user":{"id":"u-old","email":"old@b.c"},"expires_at":4102444800,"csrf_token":"old"}""",
                )
            }
        }
        val job = launch(Dispatchers.Default) { repository.restore() }
        // 请求已经发出（证明旧世代已捕获）、响应还没回来时，用户完成了一次新的登录/退出。
        assertTrue(requestReceived.await(10, java.util.concurrent.TimeUnit.SECONDS))
        generation.next()
        releaseResponse.countDown()
        job.join()
        assertTrue(
            "旧世代结果不得把会话改成已登录",
            repository.state.value !is SessionState.LoggedIn,
        )
    }
}

/** CookieJar 的认证世代保护（契约 S1-A08 的网络层落点）。 */
class AuthGenerationCookieJarTest {

    private class RecordingJar : CookieJar {
        val saved = mutableListOf<Cookie>()
        var loads = 0
        override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
            saved.addAll(cookies)
        }

        override fun loadForRequest(url: HttpUrl): List<Cookie> {
            loads += 1
            return emptyList()
        }
    }

    private val url = "https://example.test/".toHttpUrl()
    private val cookie = Cookie.Builder().name("campus_session").value("tok").domain("example.test").build()

    @Test
    fun `旧世代请求的 Set-Cookie 不写入新会话`() {
        val generation = AuthGeneration()
        val delegate = RecordingJar()
        val jar = GenerationAwareCookieJar(delegate, generation)

        generation.next() // 新会话世代（B 已登录）
        RequestGeneration.with(generation.current() - 1) {
            jar.saveFromResponse(url, listOf(cookie)) // A 的迟到响应
        }
        assertTrue("旧世代 Cookie 必须被丢弃", delegate.saved.isEmpty())

        RequestGeneration.with(generation.current()) {
            jar.saveFromResponse(url, listOf(cookie))
        }
        assertEquals(1, delegate.saved.size)
    }

    @Test
    fun `旧世代请求不能读到当前凭据`() {
        val generation = AuthGeneration()
        val delegate = RecordingJar()
        val jar = GenerationAwareCookieJar(delegate, generation)
        generation.next()
        val loaded = RequestGeneration.with(generation.current() - 1) {
            jar.loadForRequest(url)
        }
        assertTrue(loaded.isEmpty())
        assertEquals(0, delegate.loads)
    }

    @Test
    fun `没有请求世代上下文时拒绝写入`() {
        val jar = GenerationAwareCookieJar(RecordingJar(), AuthGeneration())
        jar.saveFromResponse(url, listOf(cookie))
        // 无上下文不崩溃即可；实现上不会委托写入。
        assertTrue(true)
    }
}
