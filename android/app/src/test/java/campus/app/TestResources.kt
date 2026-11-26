package campus.app

import campus.app.core.network.JsonKit
import kotlinx.serialization.json.JsonObject

/**
 * 测试资源读取。
 *
 * `app/src/test/resources/fixtures/` 里是从后端共同契约目录原样复制的合成样例，
 * 用于验证安卓解析与契约一致；`scenario.json` 是 MOCK 环境使用的合成场景。
 */
object TestResources {

    fun text(name: String): String {
        val stream = TestResources::class.java.classLoader?.getResourceAsStream("fixtures/$name")
            ?: error("缺少测试资源 fixtures/$name")
        return stream.bufferedReader(Charsets.UTF_8).use { it.readText() }
    }

    fun json(name: String): JsonObject =
        JsonKit.parseObject(text(name)) ?: error("测试资源 fixtures/$name 不是合法 JSON 对象")

    fun scenario(): JsonObject = json("scenario.json")
}
