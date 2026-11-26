package campus.app.core.session

import campus.app.core.network.ApiResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 会话视图，对应契约 SessionView：
 * user.id、user.email、expires_at、csrf_token。
 * 注意 expires_at 是 Unix 秒，不是毫秒，也不是 ISO 字符串。
 */
data class SessionView(
    val userId: String,
    val email: String,
    val expiresAtEpochSeconds: Long,
    val csrfToken: String,
)

/**
 * 会话状态。
 *
 * 关键区别：网络失败不能当作会话已失效。
 * [Failed] 与 [LoggedOut] 是两个不同状态：前者可重试，后者才回登录页。
 */
sealed interface SessionState {
    /** 启动后先进入该状态，避免闪一下登录页。 */
    data object Loading : SessionState

    /** 服务端明确判定未登录 / 会话失效。 */
    data object LoggedOut : SessionState

    data class LoggedIn(val session: SessionView) : SessionState

    /** 网络或服务异常导致无法确认会话，保留可重试入口。 */
    data class Failed(val message: String) : SessionState
}

/**
 * 页面只依赖这个接口，不直接碰 Cookie 存储细节。
 */
interface SessionRepository {

    val state: StateFlow<SessionState>

    /** 启动时调用：先 Loading，再根据结果落到 LoggedIn / LoggedOut / Failed。 */
    suspend fun restore()

    suspend fun login(email: String, password: String): ApiResult<SessionView>

    suspend fun register(email: String, password: String): ApiResult<SessionView>

    /** 刷新返回原会话与固定到期时间，不续期。 */
    suspend fun refresh(): ApiResult<SessionView>

    suspend fun logout()
}

/**
 * 样例实现：不联网，用于页面开发与演示。
 * 输入任意有效格式的邮箱和 8 位以上密码即视为成功，不涉及真实账号。
 */
class FakeSessionRepository : SessionRepository {

    private val _state = MutableStateFlow<SessionState>(SessionState.Loading)
    override val state: StateFlow<SessionState> = _state.asStateFlow()

    override suspend fun restore() {
        _state.value = SessionState.LoggedOut
    }

    override suspend fun login(email: String, password: String): ApiResult<SessionView> {
        if (!email.contains("@") || password.length < 8) {
            return ApiResult.Failure(campus.app.core.network.ApiError.InvalidCredentials)
        }
        val view = SessionView(
            userId = "sample-user-a",
            email = email.trim().lowercase(),
            expiresAtEpochSeconds = System.currentTimeMillis() / 1000 + 30L * 24 * 3600,
            csrfToken = "sample-csrf",
        )
        _state.value = SessionState.LoggedIn(view)
        return ApiResult.Success(view)
    }

    override suspend fun register(email: String, password: String): ApiResult<SessionView> =
        login(email, password)

    override suspend fun refresh(): ApiResult<SessionView> {
        val current = _state.value
        return if (current is SessionState.LoggedIn) {
            ApiResult.Success(current.session)
        } else {
            ApiResult.Failure(campus.app.core.network.ApiError.SessionInvalid)
        }
    }

    override suspend fun logout() {
        _state.value = SessionState.LoggedOut
    }
}
