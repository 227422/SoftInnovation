package campus.app.core.network

/**
 * 记录"当前线程正在执行哪一代认证请求"。
 *
 * OkHttp 的同步 [okhttp3.Call.execute] 在同一条调用线程上执行拦截器链，
 * 因此 CookieJar 回调可以读到本次请求所属的认证世代，
 * 从而在写入/读取 Cookie 前完成世代校验（而不是等页面再丢弃响应）。
 */
object RequestGeneration {

    private val holder = ThreadLocal<Int?>()

    fun <T> with(generation: Int, block: () -> T): T {
        val previous = holder.get()
        holder.set(generation)
        try {
            return block()
        } finally {
            if (previous == null) holder.remove() else holder.set(previous)
        }
    }

    fun active(): Int? = holder.get()
}
