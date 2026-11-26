package campus.app.core.cache

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/** 缓存键必须按环境、账号、类别、契约版本与内容版本隔离。 */
class CacheKeyTest {

    private val env = "LOCAL:http://127.0.0.1:8000"
    private val otherEnv = "REAL:https://example.org"

    @Test
    fun `换环境或换账号时列表缓存键不同`() {
        val base = CacheKey.list(env, "user-a", "daily", "undergrad-app/2")
        assertNotEquals(base, CacheKey.list(otherEnv, "user-a", "daily", "undergrad-app/2"))
        assertNotEquals(base, CacheKey.list(env, "user-b", "daily", "undergrad-app/2"))
    }

    @Test
    fun `换类别或换契约版本时列表缓存键不同`() {
        val base = CacheKey.list(env, "user-a", "daily", "undergrad-app/2")
        assertNotEquals(base, CacheKey.list(env, "user-a", "financial_aid", "undergrad-app/2"))
        assertNotEquals(base, CacheKey.list(env, "user-a", "daily", "undergrad-app/3"))
        assertEquals(base, CacheKey.list(env, "user-a", "daily", "undergrad-app/2"))
    }

    @Test
    fun `详情缓存键包含通知与内容版本`() {
        val base = CacheKey.detail(env, "user-a", "n1", "c1", "f1")
        assertNotEquals(base, CacheKey.detail(env, "user-a", "n1", "c2", "f1"))
        assertNotEquals(base, CacheKey.detail(env, "user-a", "n1", "c1", "f2"))
        assertNotEquals(base, CacheKey.detail(env, "user-a", "n2", "c1", "f1"))
        assertNotEquals(base, CacheKey.detail(otherEnv, "user-a", "n1", "c1", "f1"))
    }

    @Test
    fun `关注状态合并键按环境账号通知隔离`() {
        val base = CacheKey.followState(env, "user-a", "n1")
        assertNotEquals(base, CacheKey.followState(env, "user-b", "n1"))
        assertNotEquals(base, CacheKey.followState(otherEnv, "user-a", "n1"))
        assertNotEquals(base, CacheKey.followState(env, "user-a", "n2"))
    }
}
