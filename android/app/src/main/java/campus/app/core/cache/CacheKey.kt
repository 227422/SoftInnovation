package campus.app.core.cache

/**
 * 本机缓存键（契约 08 第 7 节）。
 *
 * 至少包含：环境与规范化后端地址、用户、契约版本、类别/查询指纹；
 * 详情再含 notice_id 与展示依据的内容版本。
 * 换账号、换环境、通知改版之后，旧缓存不会被当成新结果。
 */
object CacheKey {

    fun list(
        envNamespace: String,
        userId: String,
        category: String,
        contractVersion: String,
    ): String = "feed|$envNamespace|$userId|$contractVersion|$category"

    fun syncList(envNamespace: String, userId: String, category: String): String =
        "sync|feed|$envNamespace|$userId|$category"

    fun detail(
        envNamespace: String,
        userId: String,
        noticeId: String,
        contentVersion: String?,
        factsVersion: String?,
    ): String = "detail|$envNamespace|$userId|$noticeId|${contentVersion ?: "-"}|${factsVersion ?: "-"}"

    fun syncDetail(envNamespace: String, userId: String, noticeId: String): String =
        "sync|detail|$envNamespace|$userId|$noticeId"

    fun follows(envNamespace: String, userId: String): String =
        "follows|$envNamespace|$userId"

    /** 关注状态合并记录的键：按环境 + 账号 + 通知隔离。 */
    fun followState(envNamespace: String, userId: String, noticeId: String): String =
        "follow.state|$envNamespace|$userId|$noticeId"
}
