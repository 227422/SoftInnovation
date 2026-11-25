package campus.app.core.session

import campus.app.core.network.ApiClient
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.PersistentCookieJar
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 真实会话实现。
 *
 * 关键行为（契约 08 第 4.1、7 节）：
 * - 启动：先 Loading，再请求 /v1/auth/session；
 * - 只有服务端明确 401 session_invalid 才回登录页；
 * - 网络失败（超时、断网、503）落到 [SessionState.Failed]，可重试，且不清 Cookie；
 * - 登录/退出各自推进认证世代；旧世代迟到的结果与 Set-Cookie 一律丢弃，
 *   避免 A 退出后 B 登录被 A 的迟到响应清掉；
 * - 不保存明文密码。
 */
class SessionRepositoryImpl(
    private val api: ApiClient,
    private val cookieJar: PersistentCookieJar,
    private val csrf: CsrfHolder,
    private val authGeneration: AuthGeneration,
) : SessionRepository {

    private val _state = MutableStateFlow<SessionState>(SessionState.Loading)
    override val state: StateFlow<SessionState> = _state.asStateFlow()

    override suspend fun restore() {
        _state.value = SessionState.Loading
        val generation = authGeneration.current()
        val result = api.restoreSession()
        if (authGeneration.current() != generation) return
        when (result) {
            is ApiResult.Success -> {
                csrf.update(result.value.csrfToken)
                _state.value = SessionState.LoggedIn(result.value)
            }

            is ApiResult.Failure -> {
                when {
                    result.error.isSessionExpired -> {
                        clearLocal()
                        _state.value = SessionState.LoggedOut
                    }

                    else -> {
                        // 无法确认会话：保留 Cookie，给出可重试状态，不误判为未登录
                        _state.value = SessionState.Failed(messageFor(result.error))
                    }
                }
            }
        }
    }

    override suspend fun login(email: String, password: String): ApiResult<SessionView> {
        val generation = authGeneration.next()
        val result = api.loginSession(email.trim().lowercase(), password)
        return applyAuthResult(generation, result)
    }

    override suspend fun register(email: String, password: String): ApiResult<SessionView> {
        val generation = authGeneration.next()
        val result = api.registerSession(email.trim().lowercase(), password)
        return applyAuthResult(generation, result)
    }

    override suspend fun refresh(): ApiResult<SessionView> {
        val generation = authGeneration.next()
        val result = api.refreshSession()
        return applyAuthResult(generation, result)
    }

    override suspend fun logout() {
        val generation = authGeneration.next()
        // 服务端撤销失败也要清本地，否则用户"退出不了"；但只在世代未变时清，
        // 避免把期间刚登录的新会话清掉。
        api.logout()
        if (authGeneration.current() != generation) return
        clearLocal()
        _state.value = SessionState.LoggedOut
    }

    private fun applyAuthResult(generation: Int, result: ApiResult<SessionView>): ApiResult<SessionView> {
        // 迟到的旧世代结果不得改变当前会话。
        if (authGeneration.current() != generation) return result
        if (result is ApiResult.Success) {
            csrf.update(result.value.csrfToken)
            _state.value = SessionState.LoggedIn(result.value)
        }
        return result
    }

    /** 切换账号 / 退出时必须同时清 Cookie 与 CSRF，避免串号。 */
    fun clearLocal() {
        cookieJar.clear()
        csrf.clear()
    }

    private fun messageFor(error: ApiError): String = when (error) {
        is ApiError.NetworkUnavailable -> "网络不可用，暂时无法确认登录状态，可重试"
        is ApiError.ServiceUnavailable -> "服务暂时不可用，请稍后重试"
        ApiError.RateLimited -> "操作过于频繁，请稍后再试"
        else -> "暂时无法确认登录状态，可重试"
    }
}
