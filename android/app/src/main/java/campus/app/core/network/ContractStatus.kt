package campus.app.core.network

/**
 * 共同契约的当前实现状态。
 *
 * 权威来源是后端仓库的 `docs/contracts/app-v2/implementation-status.json`：
 * 15 个 v1 操作（认证、目录、资料、偏好）已实现；v2 的列表、详情、覆盖、关注读、关注写
 * 仍是 planned（服务端会返回 404 request_rejected）。
 *
 * 后端把这几个操作改为 implemented 并把实现状态表交付后，把对应的 FLAG 改成 true，
 * 同时用真实响应跑一遍解析测试。**不允许在真实环境下失败后回退样例数据。**
 */
object ContractStatus {

    const val VERSION: String = "undergrad-app/2"

    /** GET /v2/me/notices（S3）。 */
    const val NOTICE_FEED_IMPLEMENTED: Boolean = true

    /** GET /v2/me/notices/{id}（S3）。 */
    const val NOTICE_DETAIL_IMPLEMENTED: Boolean = true

    /** GET /v2/me/follows（S4）。 */
    const val FOLLOWS_IMPLEMENTED: Boolean = true

    /** PUT /v2/me/notices/{id}/follow（S4）。 */
    const val FOLLOW_WRITE_IMPLEMENTED: Boolean = true

    val noticeFeedPhase: String get() = if (NOTICE_FEED_IMPLEMENTED) "" else "S3"
    val followsPhase: String get() = if (FOLLOWS_IMPLEMENTED) "" else "S4"
}
