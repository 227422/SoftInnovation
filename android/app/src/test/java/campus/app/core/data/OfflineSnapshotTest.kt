package campus.app.core.data

import campus.app.core.network.JsonKit
import campus.app.core.network.Mappers
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 离线演示包依赖 `assets/offline` 下的快照；这里直接读文件确认格式可用。
 *
 * 单元测试的工作目录是模块根目录，所以按相对路径读取即可。
 */
class OfflineSnapshotTest {

    private val assets = File("src/main/assets/offline")

    @Test
    fun `快照列表能解析出全部通知`() {
        val raw = File(assets, "feed.json").readText()
        val page = Mappers.appPage(JsonKit.parseObject(raw)!!)
        assertEquals(11, page.total)
        assertTrue(page.items.all { it.noticeId.isNotBlank() })
        assertTrue(page.items.all { it.title.isNotBlank() })
        assertTrue(page.items.all { it.category != campus.app.core.model.Category.UNKNOWN })
    }

    @Test
    fun `每条通知都有对应的详情副本`() {
        val raw = File(assets, "feed.json").readText()
        val page = Mappers.appPage(JsonKit.parseObject(raw)!!)
        page.items.forEach { item ->
            val detailFile = File(assets, "details/${item.noticeId}.json")
            assertTrue("缺少详情副本：${item.noticeId}", detailFile.exists())
            val detail = Mappers.appDetail(JsonKit.parseObject(detailFile.readText())!!)
            assertTrue("详情解析失败：${item.noticeId}", detail != null)
            assertEquals(item.title, detail!!.item.title)
        }
    }
}
