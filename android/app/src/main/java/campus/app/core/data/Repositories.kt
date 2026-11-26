package campus.app.core.data

import campus.app.core.model.CatalogPage
import campus.app.core.model.Category
import campus.app.core.model.FollowState
import campus.app.core.model.GradeOption
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticePage
import campus.app.core.model.PreferenceKind
import campus.app.core.model.Preferences
import campus.app.core.model.ProfileEdit
import campus.app.core.model.ProfileResponse
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult

/**
 * 一类通知的一页结果。
 *
 * 特意把"新数据"与"缓存数据"分成两种成功：
 * 契约要求离线时必须显示缓存时间和离线状态，不能冒充最新结果。
 */
sealed interface PageResult {
    data class Fresh(val page: NoticePage) : PageResult
    data class Cached(val page: NoticePage, val cachedAt: String?) : PageResult
    data class Failed(val error: ApiError) : PageResult
}

sealed interface DetailResult {
    data class Fresh(val detail: NoticeDetail) : DetailResult
    data class Cached(val detail: NoticeDetail, val cachedAt: String?) : DetailResult
    data class Failed(val error: ApiError) : DetailResult
}

/**
 * 某个接口在共同契约里的可用状态。
 * [available] 为 false 时，界面必须明确显示"接口计划于 [phase] 上线"，
 * 不得偷偷改用样例数据或旧接口。
 */
data class ContractFeature(
    val available: Boolean,
    val phase: String,
    val name: String,
) {
    val pendingMessage: String
        get() = "${name}接口尚未上线（后端计划 $phase 阶段实现），当前无法读取真实数据"
}

interface ProfileRepository {
    suspend fun schools(prefix: String? = null): ApiResult<CatalogPage>
    suspend fun colleges(schoolId: String): ApiResult<CatalogPage>
    suspend fun majors(schoolId: String, collegeId: String): ApiResult<CatalogPage>
    suspend fun grades(): ApiResult<List<GradeOption>>
    suspend fun load(): ApiResult<ProfileResponse>
    suspend fun save(edit: ProfileEdit, idempotencyKey: String): ApiResult<ProfileResponse>
    suspend fun loadPreferences(): ApiResult<Preferences>
    suspend fun savePreferences(preferences: Preferences, idempotencyKey: String): ApiResult<Preferences>
    suspend fun preferenceOptions(kind: PreferenceKind): ApiResult<CatalogPage>
    fun newIdempotencyKey(): String

    /**
     * 演示用：把本机样例身份恢复成"刚注册、还没填过"的状态。
     * 真实后端创建新账号后本来就返回 completed=false，因此默认为空实现。
     */
    fun resetForNewAccount() = Unit
}

interface NoticeRepository {
    val feedFeature: ContractFeature
    val followFeature: ContractFeature

    suspend fun feed(category: Category?, offset: Int = 0, limit: Int = 20): PageResult

    suspend fun detail(noticeId: String): DetailResult

    suspend fun follows(offset: Int = 0, limit: Int = 20): PageResult

    /** 关注/取消关注：提交目标状态（不是 toggle）。 */
    suspend fun setFollow(
        noticeId: String,
        starred: Boolean,
        expectedVersion: Long,
        idempotencyKey: String,
    ): ApiResult<FollowState>

    /** 只读缓存，不发请求。用于断网时先出内容。 */
    fun cachedFeed(category: Category?): NoticePage?

    fun cachedDetail(noticeId: String): NoticeDetail?

    fun newIdempotencyKey(): String
}
