package campus.app.core.session

/**
 * 认证世代。
 *
 * 契约 S1-A08 / 08 第 7 节要求：A 退出后 B 登录，A 的退出响应、401 或旧登录响应迟到时，
 * 不能删除或替换 B 的 Cookie、CSRF 和会话。只在页面丢弃响应不够，
 * 还必须在网络层丢弃旧世代请求带来的凭据副作用。
 *
 * 每次登录/退出都会 [next] 使旧世代失效；请求发起时记录当时代次，
 * CookieJar 只接受与当前世代一致的 Set-Cookie，页面只接受与当前世代一致的结果。
 */
class AuthGeneration {

    private var value: Int = 0

    @Synchronized
    fun current(): Int = value

    /** 开始一次新的认证动作，返回新世代。 */
    @Synchronized
    fun next(): Int {
        value += 1
        return value
    }
}
