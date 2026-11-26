package campus.app.core.network

/**
 * 统一的调用结果。
 *
 * 网络失败（超时、断网）与业务失败（401/409/422）必须分开表达，
 * 因为契约要求"网络失败不等于空结果"，也不能把网络失败误报成密码错误。
 */
sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>
    data class Failure(val error: ApiError) : ApiResult<Nothing>
}

/**
 * 错误分类，对应 OpenAPI 中实际会返回的错误码（契约 08 第 4.1 节）。
 * 页面只使用这里的分类，不直接比较 HTTP 状态码或原始 code 字符串。
 */
sealed interface ApiError {

    /** 401 invalid_credentials：账号或密码错误。保留已输入邮箱，不清空。 */
    data object InvalidCredentials : ApiError

    /** 401 session_invalid：会话确认失效，唯一需要重新登录的情形。 */
    data object SessionInvalid : ApiError

    /** 403 csrf_invalid：安全令牌失效。保留草稿，不虚报成功、不当作密码错误。 */
    data object CsrfInvalid : ApiError

    /** 403 origin_forbidden：请求来源不在允许名单。 */
    data object OriginForbidden : ApiError

    /** 400 request_rejected：请求无法处理（含非法 UTF-8）。保留草稿，不当作登录失效。 */
    data object RequestRejected : ApiError

    /** 409 email_in_use：注册邮箱已被使用。 */
    data object EmailInUse : ApiError

    /** 409 version_conflict：版本冲突。保留草稿，重新读取权威版本，不自动覆盖。 */
    data object VersionConflict : ApiError

    /** 409 key_payload_conflict：同一幂等键配了不同内容，停止盲目重试。 */
    data object KeyPayloadConflict : ApiError

    /** 409 feed_changed：列表已变化，应重新请求第一页并替换分页结果。 */
    data object FeedChanged : ApiError

    /** 422 validation_error：字段不合法。保留输入，标出无效字段。 */
    data class Validation(val message: String, val fields: List<String> = emptyList()) : ApiError

    /** 422 major_not_available：所选专业不可用（目录联动已失效）。 */
    data object MajorNotAvailable : ApiError

    /** 404 school_not_supported：所选学校暂未支持。 */
    data object SchoolNotSupported : ApiError

    /** 404 college_not_available：所选学院不可用。 */
    data object CollegeNotAvailable : ApiError

    /** 404 notice_not_found：详情不可用。与"正文受限"分开。 */
    data object NoticeNotFound : ApiError

    /** 413 payload_too_large：提交内容过大。 */
    data object PayloadTooLarge : ApiError

    /** 415 json_required：请求未使用 JSON 提交。 */
    data object JsonRequired : ApiError

    /** 429 auth_rate_limited：认证请求过于频繁，需要退避。 */
    data object RateLimited : ApiError

    /** 无 HTTP 响应（断网、超时、连接失败）。可重试，不清草稿、不退出账号。 */
    data class NetworkUnavailable(val message: String) : ApiError

    /** 500 internal_error / 503 storage_unavailable：服务端暂时性故障，可重试。 */
    data class ServiceUnavailable(val message: String) : ApiError

    /** 计划中的 v2 接口尚未上线（S3/S4）。这不是网络故障，也不能回退到样例数据。 */
    data class ContractPending(val phase: String, val feature: String) : ApiError

    /** 其他未识别错误。记录 request_id 便于定位。 */
    data class Unknown(val code: String, val message: String, val requestId: String?) : ApiError

    /** 是否属于"会话已失效"这一唯一需要踢回登录的情形。 */
    val isSessionExpired: Boolean
        get() = this === SessionInvalid

    /** 是否属于网络类失败（可重试，且不应清空本地草稿）。 */
    val isNetworkFailure: Boolean
        get() = this is NetworkUnavailable

    /** 是否值得原样重试。 */
    val isRetryable: Boolean
        get() = this is NetworkUnavailable || this is ServiceUnavailable || this === RateLimited

    /** 是否属于版本/幂等冲突，需要重新读取后再提交。 */
    val isConflict: Boolean
        get() = this === VersionConflict || this === KeyPayloadConflict || this === FeedChanged
}

/**
 * 把后端的 {"error":{"code","message","request_id","details"}} 解码成 [ApiError]。
 * 所有 HTTP 失败都必须先经过这里，页面不得直接比较 HTTP 状态码。
 */
object ErrorDecoder {

    fun fromHttp(
        status: Int,
        code: String? = null,
        message: String? = null,
        requestId: String? = null,
        fields: List<String> = emptyList(),
    ): ApiError {
        val normalized = code?.trim()?.lowercase()
        return when {
            status == 400 -> ApiError.RequestRejected
            status == 401 && normalized == "invalid_credentials" -> ApiError.InvalidCredentials
            status == 401 -> ApiError.SessionInvalid
            status == 403 && normalized == "origin_forbidden" -> ApiError.OriginForbidden
            status == 403 && normalized == "csrf_invalid" -> ApiError.CsrfInvalid
            status == 403 -> ApiError.CsrfInvalid
            status == 404 && normalized == "school_not_supported" -> ApiError.SchoolNotSupported
            status == 404 && normalized == "college_not_available" -> ApiError.CollegeNotAvailable
            status == 404 && normalized == "notice_not_found" -> ApiError.NoticeNotFound
            // 未上线的 planned 路由与未知路由都返回 404 request_rejected，按"请求无法处理"归类。
            status == 404 && normalized == "request_rejected" -> ApiError.RequestRejected
            status == 404 -> ApiError.Unknown(normalized ?: "not_found", message ?: "资源不存在", requestId)
            status == 409 && normalized == "email_in_use" -> ApiError.EmailInUse
            status == 409 && normalized == "version_conflict" -> ApiError.VersionConflict
            status == 409 && normalized == "key_payload_conflict" -> ApiError.KeyPayloadConflict
            status == 409 && normalized == "feed_changed" -> ApiError.FeedChanged
            status == 409 -> ApiError.VersionConflict
            status == 413 -> ApiError.PayloadTooLarge
            status == 415 -> ApiError.JsonRequired
            status == 422 && normalized == "major_not_available" -> ApiError.MajorNotAvailable
            status == 422 -> ApiError.Validation(message ?: "输入内容不符合要求", fields)
            status == 429 -> ApiError.RateLimited
            status >= 500 -> ApiError.ServiceUnavailable(message ?: "服务暂时不可用，请稍后重试")
            else -> ApiError.Unknown(normalized ?: "http_$status", message ?: "未知错误", requestId)
        }
    }

    fun fromNetworkError(message: String?): ApiError =
        ApiError.NetworkUnavailable(message ?: "网络连接失败")
}
