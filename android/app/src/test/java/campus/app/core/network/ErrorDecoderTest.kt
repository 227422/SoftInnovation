package campus.app.core.network

import campus.app.core.ui.describe
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 错误码解码：覆盖契约里实际会出现的错误，确保会话失效、网络失败、接口未上线分类正确。
 */
class ErrorDecoderTest {

    @Test
    fun `401 invalid_credentials 是密码错误，不是会话失效`() {
        val error = ErrorDecoder.fromHttp(401, "invalid_credentials", "邮箱或密码错误")
        assertTrue(error is ApiError.InvalidCredentials)
        assertFalse(error.isSessionExpired)
    }

    @Test
    fun `401 session_invalid 才是需要重新登录`() {
        val error = ErrorDecoder.fromHttp(401, "session_invalid", "会话无效或已到期")
        assertTrue(error is ApiError.SessionInvalid)
        assertTrue(error.isSessionExpired)
    }

    @Test
    fun `403 csrf_invalid 不当作密码错误`() {
        val error = ErrorDecoder.fromHttp(403, "csrf_invalid", "安全校验失败")
        assertTrue(error is ApiError.CsrfInvalid)
        assertFalse(error.isSessionExpired)
    }

    @Test
    fun `409 version_conflict 保留冲突语义且可重读`() {
        val error = ErrorDecoder.fromHttp(409, "version_conflict", "状态已更新")
        assertTrue(error is ApiError.VersionConflict)
        assertTrue(error.isConflict)
        assertFalse(error.isRetryable)
    }

    @Test
    fun `409 key_payload_conflict 与 feed_changed 分开`() {
        assertTrue(ErrorDecoder.fromHttp(409, "key_payload_conflict") is ApiError.KeyPayloadConflict)
        assertTrue(ErrorDecoder.fromHttp(409, "feed_changed") is ApiError.FeedChanged)
        assertTrue(ErrorDecoder.fromHttp(409, "email_in_use") is ApiError.EmailInUse)
    }

    @Test
    fun `422 解析字段名用于提示`() {
        val error = ErrorDecoder.fromHttp(
            status = 422,
            code = "validation_error",
            message = "输入内容不符合要求",
            fields = listOf("school_id", "grade"),
        )
        assertTrue(error is ApiError.Validation)
        assertEquals(listOf("school_id", "grade"), (error as ApiError.Validation).fields)
    }

    @Test
    fun `422 major_not_available 单独识别`() {
        assertTrue(ErrorDecoder.fromHttp(422, "major_not_available") is ApiError.MajorNotAvailable)
    }

    @Test
    fun `404 区分学校、学院与通知`() {
        assertTrue(ErrorDecoder.fromHttp(404, "school_not_supported") is ApiError.SchoolNotSupported)
        assertTrue(ErrorDecoder.fromHttp(404, "college_not_available") is ApiError.CollegeNotAvailable)
        assertTrue(ErrorDecoder.fromHttp(404, "notice_not_found") is ApiError.NoticeNotFound)
    }

    @Test
    fun `413 415 400 分别映射`() {
        assertTrue(ErrorDecoder.fromHttp(413) is ApiError.PayloadTooLarge)
        assertTrue(ErrorDecoder.fromHttp(415) is ApiError.JsonRequired)
        assertTrue(ErrorDecoder.fromHttp(400, "request_rejected") is ApiError.RequestRejected)
    }

    @Test
    fun `429 与 5xx 分类不同`() {
        assertTrue(ErrorDecoder.fromHttp(429, "auth_rate_limited") is ApiError.RateLimited)
        assertTrue(ErrorDecoder.fromHttp(500, "internal_error") is ApiError.ServiceUnavailable)
        assertTrue(ErrorDecoder.fromHttp(503, "storage_unavailable") is ApiError.ServiceUnavailable)
    }

    @Test
    fun `503 属于可重试故障，但不属于网络失败`() {
        val error = ErrorDecoder.fromHttp(503, "storage_unavailable")
        assertFalse("503 不能当会话失效", error.isSessionExpired)
        assertTrue(error.isRetryable)
        assertFalse(error.isNetworkFailure)
        val network = ErrorDecoder.fromNetworkError("timeout")
        assertTrue(network.isNetworkFailure)
        assertTrue(network.isRetryable)
    }

    @Test
    fun `错误文案区分密码错误、会话失效与接口未上线`() {
        val credential = ErrorDecoder.fromHttp(401, "invalid_credentials").describe()
        val session = ErrorDecoder.fromHttp(401, "session_invalid").describe()
        val network = ErrorDecoder.fromNetworkError("timeout").describe()
        val pending = ApiError.ContractPending("S3", "通知列表").describe()
        assertNotEquals(credential, session)
        assertNotEquals(session, network)
        assertTrue(pending.contains("尚未上线"))
    }
}
