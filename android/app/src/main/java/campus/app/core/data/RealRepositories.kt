package campus.app.core.data

import campus.app.core.cache.CacheKey
import campus.app.core.model.Category
import campus.app.core.model.FollowState
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticePage
import campus.app.core.model.PreferenceKind
import campus.app.core.model.Preferences
import campus.app.core.model.ProfileEdit
import campus.app.core.model.ProfileResponse
import campus.app.core.network.ApiClient
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.ContractStatus
import campus.app.core.network.JsonKit
import campus.app.core.network.Mappers
import campus.app.core.network.map
import campus.app.core.storage.KeyValueStore
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

/**
 * 真实资料/偏好实现（Env = LOCAL / REAL）。
 * 已实现接口按契约使用正文 expected_version；重试时由界面复用同一个幂等键。
 */
class RealProfileRepository(private val api: ApiClient) : ProfileRepository {

    override suspend fun schools(prefix: String?) = api.catalogSchools(prefix)

    override suspend fun colleges(schoolId: String) = api.catalogColleges(schoolId)

    override suspend fun majors(schoolId: String, collegeId: String) =
        api.catalogMajors(schoolId, collegeId)

    override suspend fun grades() = api.catalogGrades()

    override suspend fun load() = api.myProfile()

    override suspend fun save(edit: ProfileEdit, idempotencyKey: String): ApiResult<ProfileResponse> =
        api.saveProfile(edit, idempotencyKey).map { Mappers.profileResponse(it) }

    override suspend fun loadPreferences() = api.myPreferences()

    override suspend fun savePreferences(
        preferences: Preferences,
        idempotencyKey: String,
    ): ApiResult<Preferences> = api.savePreferences(
        courseIds = preferences.courseIds,
        skillIds = preferences.skillIds,
        goalIds = preferences.goalIds,
        interestIds = preferences.interestIds,
        expectedVersion = preferences.version,
        idempotencyKey = idempotencyKey,
    ).map { Mappers.preferences(it) }

    override suspend fun preferenceOptions(kind: PreferenceKind) = api.catalogPreferences(kind)

    override fun newIdempotencyKey(): String = UUID.randomUUID().toString()
}

/**
 * 真实通知/关注实现（Env = LOCAL / REAL）。
 *
 * 通知列表、详情、关注读写在共同契约中仍为 planned。
 * 因此这里不会"失败后自动回退样例数据"，而是返回 [ApiError.ContractPending]，
 * 由界面明确说明该功能等待后端上线。
 * 后端把对应操作改为 implemented 并交付真实响应后，改 [ContractStatus] 的开关即可接通。
 */
/** 一次取够再在本机筛选，避免分类筛选后翻页对不上。 */
private const val PAGE_FETCH_LIMIT = 100

class RealNoticeRepository(
    private val api: ApiClient,
    private val store: KeyValueStore,
    private val envNamespace: String,
    private val userIdProvider: () -> String?,
    private val followStore: FollowStore,
) : NoticeRepository {

    override val feedFeature: ContractFeature
        get() = ContractFeature(
            available = ContractStatus.NOTICE_FEED_IMPLEMENTED,
            phase = ContractStatus.noticeFeedPhase,
            name = "通知列表",
        )

    override val followFeature: ContractFeature
        get() = ContractFeature(
            available = ContractStatus.FOLLOWS_IMPLEMENTED,
            phase = ContractStatus.followsPhase,
            name = "我的关注",
        )

    override suspend fun feed(category: Category?, offset: Int, limit: Int): PageResult {
        if (!ContractStatus.NOTICE_FEED_IMPLEMENTED) {
            return PageResult.Failed(ApiError.ContractPending("S3", "通知列表"))
        }
        // 后端按「跟你有没有关系」整体排序，不认分类；
        // 所以一次取够，分类筛选放在本机做，翻页也按筛选后的结果算。
        return when (val result = api.notices(null, offset = 0, limit = PAGE_FETCH_LIMIT)) {
            is ApiResult.Success -> {
                val raw = result.value
                val page = Mappers.appPage(raw)
                store.putString(cacheKey(), raw.toString())
                store.putString(syncKey(), now())
                PageResult.Fresh(slice(page, category, offset, limit))
            }

            is ApiResult.Failure -> {
                if (offset == 0 && isRetryableFailure(result.error)) {
                    cachedPage()?.let { page ->
                        PageResult.Cached(slice(page, category, offset, limit), store.getString(syncKey()))
                    } ?: PageResult.Failed(result.error)
                } else {
                    PageResult.Failed(result.error)
                }
            }
        }
    }

    /** 按分类筛选后再切分页；分类为空表示不筛。 */
    private fun slice(page: NoticePage, category: Category?, offset: Int, limit: Int): NoticePage {
        val items = if (category == null) page.items else page.items.filter { it.category == category }
        return page.copy(items = items.drop(offset).take(limit), total = items.size, offset = offset, limit = limit)
    }

    override suspend fun follows(offset: Int, limit: Int): PageResult {
        if (!ContractStatus.FOLLOWS_IMPLEMENTED) {
            return PageResult.Failed(ApiError.ContractPending("S4", "我的关注"))
        }
        return when (val result = api.follows(offset, limit)) {
            is ApiResult.Success -> {
                val raw = result.value
                val page = Mappers.appPage(raw)
                if (offset == 0) {
                    store.putString(followsCacheKey(), raw.toString())
                    store.putString(followsSyncKey(), now())
                }
                PageResult.Fresh(followStore.mergePage(page))
            }

            is ApiResult.Failure -> {
                if (offset == 0 && isRetryableFailure(result.error)) {
                    cachedFollows()?.let { page ->
                        PageResult.Cached(page, store.getString(followsSyncKey()))
                    } ?: PageResult.Failed(result.error)
                } else {
                    PageResult.Failed(result.error)
                }
            }
        }
    }

    override suspend fun detail(noticeId: String): DetailResult {
        if (!ContractStatus.NOTICE_DETAIL_IMPLEMENTED) {
            return DetailResult.Failed(ApiError.ContractPending("S3", "通知详情"))
        }
        return when (val result = api.noticeDetail(noticeId)) {
            is ApiResult.Success -> {
                val raw = result.value
                val detail = Mappers.appDetail(raw)
                    ?: return DetailResult.Failed(
                        ApiError.Unknown("bad_detail", "详情结构不完整", null),
                    )
                store.putString(detailKey(noticeId), raw.toString())
                store.putString(detailSyncKey(noticeId), now())
                DetailResult.Fresh(mergeFollow(detail))
            }

            is ApiResult.Failure -> {
                if (isRetryableFailure(result.error)) {
                    cachedDetail(noticeId)?.let { detail ->
                        DetailResult.Cached(detail, store.getString(detailSyncKey(noticeId)))
                    } ?: DetailResult.Failed(result.error)
                } else {
                    DetailResult.Failed(result.error)
                }
            }
        }
    }

    override suspend fun setFollow(
        noticeId: String,
        starred: Boolean,
        expectedVersion: Long,
        idempotencyKey: String,
    ): ApiResult<FollowState> {
        if (!ContractStatus.FOLLOW_WRITE_IMPLEMENTED) {
            return ApiResult.Failure(ApiError.ContractPending("S4", "关注"))
        }
        return when (val result = api.putFollow(noticeId, starred, expectedVersion, idempotencyKey)) {
            is ApiResult.Success -> ApiResult.Success(followStore.record(Mappers.follow(result.value, noticeId)))
            is ApiResult.Failure -> result
        }
    }

    override fun cachedFeed(category: Category?): NoticePage? {
        val page = cachedPage() ?: return null
        val items = if (category == null) page.items else page.items.filter { it.category == category }
        return page.copy(items = items, total = items.size)
    }

    private fun cachedPage(): NoticePage? {
        val raw = store.getString(cacheKey()) ?: return null
        val obj = JsonKit.parseObject(raw) ?: return null
        return followStore.mergePage(Mappers.appPage(obj))
    }

    override fun cachedDetail(noticeId: String): NoticeDetail? {
        val raw = store.getString(detailKey(noticeId)) ?: return null
        val obj = JsonKit.parseObject(raw) ?: return null
        return Mappers.appDetail(obj)?.let { mergeFollow(it) }
    }

    override fun newIdempotencyKey(): String = UUID.randomUUID().toString()

    // ------------------------------------------------------------ 内部

    private fun isRetryableFailure(error: ApiError): Boolean =
        error.isNetworkFailure || error is ApiError.ServiceUnavailable

    private fun mergeFollow(detail: NoticeDetail): NoticeDetail =
        detail.copy(item = detail.item.copy(follow = followStore.merge(detail.item.follow)))

    private fun cachedFollows(): NoticePage? {
        val raw = store.getString(followsCacheKey()) ?: return null
        val obj = JsonKit.parseObject(raw) ?: return null
        return followStore.mergePage(Mappers.appPage(obj))
    }

    private fun cacheKey(): String =
        CacheKey.list(envNamespace, userId(), "all", ContractStatus.VERSION)

    private fun syncKey(): String = CacheKey.syncList(envNamespace, userId(), "all")

    private fun followsCacheKey(): String = CacheKey.follows(envNamespace, userId())

    private fun followsSyncKey(): String = "sync|${followsCacheKey()}"

    private fun detailKey(noticeId: String): String =
        CacheKey.detail(envNamespace, userId(), noticeId, null, null)

    private fun detailSyncKey(noticeId: String): String =
        CacheKey.syncDetail(envNamespace, userId(), noticeId)

    private fun userId(): String = userIdProvider() ?: "anonymous"

    private fun now(): String = OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
}
