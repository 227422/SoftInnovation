package campus.app.core.data

import campus.app.core.cache.CacheKey
import campus.app.core.model.FollowState
import campus.app.core.storage.KeyValueStore
import campus.app.core.network.JsonKit
import campus.app.core.network.bool
import campus.app.core.network.long
import campus.app.core.network.str
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 关注状态合并（契约 08 第 6.3 节）。
 *
 * 所有来源（列表、详情、关注页、PUT 响应、缓存、幂等重放）的 FollowState 都必须按
 * 环境 + 账号 + notice_id 单独比较 version：低版本不得覆盖已知高版本。
 * 例如先读到未关注的 v0，PUT 先返回已关注的 v1，随后迟到的 v0 只能更新其余字段，不能取消星标。
 */
class FollowStore(
    private val store: KeyValueStore,
    private val envNamespace: String,
    private val userIdProvider: () -> String?,
) {

    fun known(noticeId: String): FollowState? {
        val raw = store.getString(key(noticeId)) ?: return null
        val obj = JsonKit.parseObject(raw) ?: return null
        return FollowState(
            noticeId = obj.str("notice_id") ?: noticeId,
            starred = obj.bool("starred") ?: false,
            followedAt = obj.str("followed_at"),
            version = obj.long("version") ?: 0L,
        )
    }

    /** 合并并持久化；返回合并后的权威状态。 */
    fun record(incoming: FollowState): FollowState {
        if (incoming.noticeId.isBlank()) return incoming
        val merged = merge(incoming)
        store.putString(
            key(merged.noticeId),
            buildJsonObject {
                put("notice_id", merged.noticeId)
                put("starred", merged.starred)
                if (merged.followedAt == null) {
                    put("followed_at", kotlinx.serialization.json.JsonNull)
                } else {
                    put("followed_at", merged.followedAt)
                }
                put("version", merged.version)
            }.toString(),
        )
        return merged
    }

    fun merge(incoming: FollowState): FollowState {
        val known = known(incoming.noticeId) ?: return incoming
        return when {
            incoming.version > known.version -> incoming
            incoming.version < known.version -> known
            // 同版本不应出现不同状态；保守保留已知状态，避免界面无谓翻转。
            incoming.starred != known.starred -> known
            else -> incoming.copy(followedAt = incoming.followedAt ?: known.followedAt)
        }
    }

    /** 只把列表项里的关注状态换成合并后的权威值。 */
    fun mergePage(page: campus.app.core.model.NoticePage): campus.app.core.model.NoticePage =
        page.copy(
            items = page.items.map { item ->
                item.copy(follow = merge(item.follow))
            },
        )

    private fun key(noticeId: String): String =
        CacheKey.followState(envNamespace, userIdProvider() ?: "anonymous", noticeId)
}
