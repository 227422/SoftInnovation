package campus.app.core.session

import campus.app.core.storage.KeyValueStore

/**
 * CSRF 令牌持有者。
 *
 * 单独抽出来是为了打破循环依赖：ApiClient 需要在写请求时读令牌，而令牌由 SessionRepository 写入。
 * 令牌按环境（含规范化后端地址）隔离，避免切换环境后把旧令牌带给新服务。
 */
class CsrfHolder(
    private val store: KeyValueStore,
    private val key: String = "session.csrf",
) {

    var token: String? = store.getString(key)
        private set

    fun update(value: String?) {
        token = value?.takeIf { it.isNotBlank() }
        if (token == null) store.remove(key) else store.putString(key, token)
    }

    fun clear() = update(null)
}
