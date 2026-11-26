package campus.app.core.network

import campus.app.core.session.AuthGeneration
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

/**
 * 带认证世代校验的 CookieJar 包装。
 *
 * 只有"由本客户端发起、且所属认证世代仍是当前世代"的请求，才允许：
 * - 写入响应里的 Set-Cookie；
 * - 读取并携带本地会话 Cookie。
 *
 * 这样 A 退出后迟到的删除 Cookie、A 的旧 401 清理都不会作用到 B 的会话上。
 * 请求线程外（没有记录世代）的调用一律拒绝，避免误写。
 */
class GenerationAwareCookieJar(
    private val delegate: CookieJar,
    private val authGeneration: AuthGeneration,
) : CookieJar {

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val generation = RequestGeneration.active() ?: return
        if (generation != authGeneration.current()) return
        delegate.saveFromResponse(url, cookies)
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val generation = RequestGeneration.active()
        if (generation != null && generation != authGeneration.current()) return emptyList()
        return delegate.loadForRequest(url)
    }
}
