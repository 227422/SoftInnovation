package campus.app.core.data

import android.content.Context
import campus.app.core.model.Category
import campus.app.core.model.FollowState
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticeItem
import campus.app.core.model.NoticePage
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.JsonKit
import campus.app.core.network.Mappers
import java.util.UUID

/**
 * 离线演示版的通知仓库。
 *
 * 数据来自 `assets/offline`：一份真实抓取结果的快照（列表 + 每条详情），
 * 格式与后端接口完全一致，因此解析仍走 [Mappers.appPage] / [Mappers.appDetail]。
 *
 * 不联网；关注状态只存在内存里，关掉 App 会回到初始状态。
 */
class OfflineNoticeRepository(private val context: Context) : NoticeRepository {

    override val feedFeature: ContractFeature
        get() = ContractFeature(available = true, phase = "OFFLINE", name = "通知列表")

    override val followFeature: ContractFeature
        get() = ContractFeature(available = true, phase = "OFFLINE", name = "我的关注")

    private val followStates = mutableMapOf<String, FollowState>()

    /** 快照只读一次，之后都走内存。 */
    private val allItems: List<NoticeItem> by lazy {
        val raw = readAsset("offline/feed.json") ?: return@lazy emptyList()
        val page = JsonKit.parseObject(raw)?.let { Mappers.appPage(it) }
        page?.items.orEmpty().map { it.copy(follow = followOf(it.noticeId)) }
    }

    override suspend fun feed(category: Category?, offset: Int, limit: Int): PageResult {
        val matched = if (category == null) allItems else allItems.filter { it.category == category }
        val page = NoticePage(
            items = matched.drop(offset).take(limit).map { it.copy(follow = followOf(it.noticeId)) },
            total = matched.size,
            offset = offset,
            limit = limit,
        )
        return PageResult.Fresh(page)
    }

    override suspend fun detail(noticeId: String): DetailResult {
        val raw = readAsset("offline/details/$noticeId.json")
            ?: return DetailResult.Failed(
                ApiError.Unknown("offline_missing", "这条通知没有离线副本", null),
            )
        val detail = JsonKit.parseObject(raw)?.let { Mappers.appDetail(it) }
            ?: return DetailResult.Failed(
                ApiError.Unknown("offline_broken", "离线副本解析失败", null),
            )
        return DetailResult.Fresh(detail.copy(item = detail.item.copy(follow = followOf(noticeId))))
    }

    override suspend fun follows(offset: Int, limit: Int): PageResult {
        // 关注的时间顺序：后关注的排前面。
        val starredIds = followStates.values
            .filter { it.starred }
            .sortedByDescending { it.version }
            .map { it.noticeId }
        val items = allItems
            .filter { it.noticeId in starredIds }
            .sortedBy { starredIds.indexOf(it.noticeId) }
            .map { it.copy(follow = followOf(it.noticeId)) }
        return PageResult.Fresh(
            NoticePage(items = items.drop(offset).take(limit), total = items.size, offset = offset, limit = limit),
        )
    }

    override suspend fun setFollow(
        noticeId: String,
        starred: Boolean,
        expectedVersion: Long,
        idempotencyKey: String,
    ): ApiResult<FollowState> {
        val current = followStates[noticeId]?.version ?: 0L
        if (expectedVersion != 0L && expectedVersion != current) {
            return ApiResult.Failure(ApiError.VersionConflict)
        }
        val next = FollowState(
            noticeId = noticeId,
            starred = starred,
            followedAt = null,
            version = current + 1,
        )
        followStates[noticeId] = next
        return ApiResult.Success(next)
    }

    override fun cachedFeed(category: Category?): NoticePage? {
        val matched = if (category == null) allItems else allItems.filter { it.category == category }
        return NoticePage(items = matched, total = matched.size)
    }

    override fun cachedDetail(noticeId: String): NoticeDetail? = null

    override fun newIdempotencyKey(): String = UUID.randomUUID().toString()

    private fun followOf(noticeId: String): FollowState =
        followStates[noticeId] ?: FollowState(noticeId = noticeId)

    private fun readAsset(path: String): String? = try {
        context.assets.open(path).bufferedReader().use { it.readText() }
    } catch (e: Exception) {
        null
    }
}
