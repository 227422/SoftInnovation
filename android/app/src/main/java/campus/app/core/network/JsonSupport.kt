package campus.app.core.network

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * JSON 读取工具。
 *
 * 只用树形 API，不引入序列化编译器插件，避免改动构建链。
 * 所有取值都是"安全取值"：类型不符或缺失一律返回 null，
 * 由上层决定是"未知"还是"空"，绝不悄悄补默认值。
 */
object JsonKit {

    val json: Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    fun parseObject(text: String): JsonObject? = runCatching {
        json.parseToJsonElement(text).jsonObject
    }.getOrNull()

    fun parseElement(text: String): JsonElement? = runCatching {
        json.parseToJsonElement(text)
    }.getOrNull()

    fun number(value: Long): JsonPrimitive = JsonPrimitive(value)

    fun text(value: String): JsonPrimitive = JsonPrimitive(value)
}

fun JsonObject.raw(key: String): JsonElement? {
    val e = this[key] ?: return null
    return if (e is JsonNull) null else e
}

fun JsonObject.str(key: String): String? =
    raw(key)?.let { runCatching { it.jsonPrimitive.content }.getOrNull() }

/** 读取整数。JSON 整数、整数值的浮点写法（1.0）都接受；布尔与字符串数字不接受。 */
fun JsonObject.int(key: String): Int? {
    val primitive = raw(key) as? JsonPrimitive ?: return null
    if (primitive.isString) {
        // 目录 value 在旧实现里出现过字符串；契约要求整数，但读取时兼容字符串数字。
        return primitive.content.toIntOrNull()
    }
    return primitive.content.toIntOrNull() ?: primitive.content.toDoubleOrNull()?.takeIf { it % 1.0 == 0.0 }?.toInt()
}

/** 读取 64 位整数（版本、expires_at 等）。禁止经浮点数中转丢失精度。 */
fun JsonObject.long(key: String): Long? {
    val primitive = raw(key) as? JsonPrimitive ?: return null
    if (primitive.isString) return primitive.content.toLongOrNull()
    return primitive.content.toLongOrNull()
}

fun JsonObject.bool(key: String): Boolean? {
    val primitive = raw(key) as? JsonPrimitive ?: return null
    if (primitive.isString) return primitive.content.toBooleanStrictOrNull()
    return when (primitive.content) {
        "true" -> true
        "false" -> false
        else -> null
    }
}

fun JsonObject.obj(key: String): JsonObject? =
    raw(key)?.let { runCatching { it.jsonObject }.getOrNull() }

fun JsonObject.array(key: String): List<JsonElement> =
    (raw(key) as? JsonArray)?.toList() ?: emptyList()

fun JsonObject.strList(key: String): List<String> =
    array(key).mapNotNull { runCatching { it.jsonPrimitive.content }.getOrNull() }

fun JsonObject.objList(key: String): List<JsonObject> =
    array(key).mapNotNull { runCatching { it.jsonObject }.getOrNull() }

/** 详情/列表的条目数组固定叫 items；不猜测 data/notices 等旧键名。 */
fun JsonObject.items(): List<JsonObject> = objList("items")
