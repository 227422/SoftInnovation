package campus.app.core

import android.content.Context
import campus.app.core.data.FollowStore
import campus.app.core.data.OfflineNoticeRepository
import campus.app.core.data.MockProfileRepository
import campus.app.core.data.MockScenario
import campus.app.core.data.NoticeRepository
import campus.app.core.data.ProfileRepository
import campus.app.core.data.RealNoticeRepository
import campus.app.core.data.RealProfileRepository
import campus.app.core.network.ApiClient
import campus.app.core.network.AppEnv
import campus.app.core.network.Env
import campus.app.core.network.PersistentCookieJar
import campus.app.core.session.AuthGeneration
import campus.app.core.session.CsrfHolder
import campus.app.core.session.FakeSessionRepository
import campus.app.core.session.SessionRepository
import campus.app.core.session.SessionRepositoryImpl
import campus.app.core.session.SessionState
import campus.app.core.storage.KeyValueStore
import campus.app.core.storage.PrefsKeyValueStore
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * 依赖装配。
 *
 * 只此一处根据环境决定用样例数据还是真实接口，页面拿到的永远是同样的 Repository 接口。
 * 缓存、Cookie、CSRF、关注版本合并都按"环境 + 规范化服务地址 + 账号"隔离，
 * 换环境或换账号不会串数据。
 *
 * 这也是"禁止请求失败后偷偷改用假数据"的落点：降级只能通过显式切换环境发生。
 */
class AppContainer(
    context: Context,
    val env: AppEnv = Env.current,
) {

    val store: KeyValueStore = PrefsKeyValueStore(context)

    /** 环境标识（含规范化后端地址），用于隔离缓存与凭据。 */
    val envNamespace: String = Env.storageNamespaceOf(env)

    val csrf: CsrfHolder = CsrfHolder(store, "session.csrf.$envNamespace")

    val cookieJar: PersistentCookieJar = PersistentCookieJar(store, "cookie.$envNamespace")

    val authGeneration: AuthGeneration = AuthGeneration()

    /**
     * 上次连通的地址要记住：Cookie 是按主机名的，重启后如果换成另一个地址，
     * 会话就带不过去，表现为"一重启就掉登录"。
     */
    private val activeBaseKey: String = "active_base.$envNamespace"

    private val baseCandidates: List<String> = run {
        val all = Env.baseUrlsOf(env)
        val remembered = store.getString(activeBaseKey)?.takeIf { it.isNotBlank() }
        val first = remembered ?: all.firstOrNull().orEmpty()
        listOf(first) + all.filter { it != first }
    }

    private val api: ApiClient = ApiClient(
        baseUrl = baseCandidates.firstOrNull().orEmpty(),
        cookieJar = cookieJar,
        csrfProvider = { csrf.token },
        authGeneration = authGeneration,
        fallbackBaseUrls = baseCandidates.drop(1),
        onBaseResolved = { store.putString(activeBaseKey, it) },
    )

    lateinit var session: SessionRepository
        private set

    lateinit var profile: ProfileRepository
        private set

    lateinit var notice: NoticeRepository
        private set

    private val followStore = FollowStore(store, envNamespace) { userId() }

    init {
        if (env.isMock) {
            val scenario = MockScenario.load(context.applicationContext)
            session = FakeSessionRepository()
            profile = MockProfileRepository(scenario)
            // 通知用内置的真实抓取快照；身份目录仍取样例里的中南大学数据。
            notice = OfflineNoticeRepository(context.applicationContext)
        } else {
            session = SessionRepositoryImpl(api, cookieJar, csrf, authGeneration)
            profile = RealProfileRepository(api)
            notice = RealNoticeRepository(
                api = api,
                store = store,
                envNamespace = envNamespace,
                userIdProvider = { userId() },
                followStore = followStore,
            )
        }
    }

    private fun userId(): String? =
        (session.state.value as? SessionState.LoggedIn)?.session?.userId

    /** 当前契约版本（界面展示用）。 */
    val contractVersion: String = campus.app.core.network.ContractStatus.VERSION
}

val LocalAppContainer = staticCompositionLocalOf<AppContainer> {
    error("AppContainer 未提供：请在 AppRoot 中用 CompositionLocalProvider 注入")
}
