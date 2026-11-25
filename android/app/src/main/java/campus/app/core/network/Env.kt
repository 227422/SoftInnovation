package campus.app.core.network

/**
 * 运行环境。
 *
 * 契约要求：样例数据模式与真实服务模式必须由显式开关区分，
 * 禁止"后台请求失败后偷偷改用假数据"。因此这里只有三档，且互斥。
 */
enum class AppEnv(val isMock: Boolean) {
    MOCK(isMock = true),
    LOCAL(isMock = false),
    REAL(isMock = false),
}

object Env {

    /** 默认环境。切换由界面上的开发环境入口完成，容器会整体重建。 */
    /** 离线演示包（demo）不连后端，直接读内置快照。 */
    var current: AppEnv = if (campus.app.BuildConfig.OFFLINE_DEMO) AppEnv.MOCK else AppEnv.LOCAL

    /**
     * 本机后端的候选地址，按顺序试：
     * - 127.0.0.1：真机用 `adb reverse tcp:8000 tcp:8000` 转过来，模拟器也可能通；
     * - 10.0.2.2：安卓模拟器访问电脑的网关地址（部分模拟器不支持）。
     * 哪个先通就用哪个，之后一直用它。
     */
    val LOCAL_BASE_URLS: List<String> = listOf(
        "http://127.0.0.1:8000",
        "http://10.0.2.2:8000",
    )

    /** 主地址，仅用于环境标识与展示。 */
    val LOCAL_BASE_URL: String get() = LOCAL_BASE_URLS.first()

    fun baseUrlsOf(env: AppEnv): List<String> = when (env) {
        AppEnv.MOCK -> emptyList()
        AppEnv.LOCAL -> LOCAL_BASE_URLS
        AppEnv.REAL -> listOf(REAL_BASE_URL)
    }

    /** 正式服务地址，待后端部署 HTTPS 入口后填写并验证。 */
    const val REAL_BASE_URL: String = "https://example.invalid"

    fun baseUrlOf(env: AppEnv): String = baseUrlsOf(env).firstOrNull().orEmpty()

    /** 缓存/凭据隔离用的环境标识，包含规范化后的服务地址。 */
    fun storageNamespaceOf(env: AppEnv): String =
        "${env.name}:${baseUrlOf(env).trimEnd('/')}"
}
