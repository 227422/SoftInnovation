package campus.app.core.data

import campus.app.core.model.FollowState
import campus.app.core.storage.MemoryKeyValueStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 关注状态按版本合并（契约 08 第 6.3 节）：
 * 低版本不得覆盖高版本；同版本不翻转；按环境 + 账号 + 通知隔离。
 */
class FollowStoreTest {

    private val store = MemoryKeyValueStore()

    private fun followStore(user: String = "user-a", env: String = "LOCAL:http://127.0.0.1:8000") =
        FollowStore(store, env) { user }

    @Test
    fun `低版本关注状态不覆盖高版本`() {
        val follows = followStore()
        follows.record(FollowState("n1", starred = true, followedAt = "2026-11-09T21:00:00+08:00", version = 2))
        val merged = follows.merge(FollowState("n1", starred = false, followedAt = null, version = 0))
        assertTrue("迟到的 v0 不能取消 v1/v2 的星标", merged.starred)
        assertEquals(2L, merged.version)
        assertEquals("2026-11-09T21:00:00+08:00", merged.followedAt)
    }

    @Test
    fun `高版本覆盖低版本并持久化`() {
        val follows = followStore()
        follows.record(FollowState("n1", starred = false, version = 0))
        follows.record(FollowState("n1", starred = true, followedAt = "2026-11-09T21:00:00+08:00", version = 1))

        // 新实例模拟进程重启：从持久存储读回
        val reopened = followStore()
        val known = reopened.known("n1")!!
        assertTrue(known.starred)
        assertEquals(1L, known.version)
        assertEquals("2026-11-09T21:00:00+08:00", known.followedAt)
    }

    @Test
    fun `同版本不同状态时保守保留已知状态`() {
        val follows = followStore()
        follows.record(FollowState("n1", starred = true, followedAt = "2026-11-09T21:00:00+08:00", version = 3))
        val merged = follows.merge(FollowState("n1", starred = false, version = 3))
        assertTrue("同版本不应翻转界面状态", merged.starred)
    }

    @Test
    fun `不同账号与不同环境之间不共享关注状态`() {
        followStore("user-a").record(FollowState("n1", starred = true, version = 1))
        assertNull(followStore("user-b").known("n1"))
        assertNull(followStore("user-a", env = "REAL:https://example.org").known("n1"))
    }

    @Test
    fun `取消关注保留递增版本与空时间`() {
        val follows = followStore()
        follows.record(FollowState("n1", starred = true, followedAt = "2026-11-09T21:00:00+08:00", version = 1))
        follows.record(FollowState("n1", starred = false, followedAt = null, version = 2))
        val known = follows.known("n1")!!
        assertFalse(known.starred)
        assertNull(known.followedAt)
        assertEquals(2L, known.version)
    }
}
