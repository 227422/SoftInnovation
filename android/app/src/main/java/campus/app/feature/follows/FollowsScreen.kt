package campus.app.feature.follows

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.data.PageResult
import campus.app.core.model.NoticeItem
import campus.app.core.model.NoticePage
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import campus.app.feature.common.MessageBox
import campus.app.feature.common.NoticeCard
import campus.app.feature.common.OfflineBanner
import campus.app.navigation.RequestGate
import kotlinx.coroutines.launch

/**
 * 我的关注：独立于首页类别与排序，按服务端关注时间从新到旧。
 *
 * 排序完全由后端/样例返回，前端不重排；取消关注提交目标状态（starred=false）
 * 与当前 follow.version，同一次逻辑操作的重试复用同一个幂等键。
 */
@Composable
fun FollowsScreen(
    onOpenNotice: (String) -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val gate = remember { RequestGate() }
    val followFeature = container.notice.followFeature

    var reloadKey by remember { mutableIntStateOf(0) }
    var state by remember { mutableStateOf<FollowsUiState>(FollowsUiState.Loading) }
    var actionMessage by remember { mutableStateOf<String?>(null) }
    var cancellingId by remember { mutableStateOf<String?>(null) }
    // 通知 ID → 幂等键。网络失败重试复用；成功、校验失败或版本冲突后移除。
    val pendingKeys = remember { mutableMapOf<String, String>() }

    LaunchedEffect(container, reloadKey) {
        if (!followFeature.available) {
            state = FollowsUiState.FeatureUnavailable
            return@LaunchedEffect
        }
        val token = gate.next()
        state = FollowsUiState.Loading
        val result = container.notice.follows()
        if (!gate.isCurrent(token)) return@LaunchedEffect
        state = when (result) {
            is PageResult.Fresh -> FollowsUiState.Content(result.page, offline = false, cachedAt = null)
            is PageResult.Cached -> FollowsUiState.Content(result.page, offline = true, cachedAt = result.cachedAt)
            is PageResult.Failed -> FollowsUiState.Failed(result.error)
        }
    }

    fun cancelFollow(item: NoticeItem) {
        if (cancellingId != null) return
        val key = pendingKeys.getOrPut(item.noticeId) { container.notice.newIdempotencyKey() }
        cancellingId = item.noticeId
        actionMessage = null
        scope.launch {
            val result = container.notice.setFollow(
                noticeId = item.noticeId,
                starred = false,
                expectedVersion = item.follow.version,
                idempotencyKey = key,
            )
            when (result) {
                is ApiResult.Success -> {
                    pendingKeys.remove(item.noticeId)
                    actionMessage = "已取消关注"
                    reloadKey += 1
                }

                is ApiResult.Failure -> {
                    val error = result.error
                    when {
                        error == ApiError.VersionConflict -> {
                            pendingKeys.remove(item.noticeId)
                            actionMessage = "关注状态已在其他设备更新，已重新读取列表"
                            reloadKey += 1
                        }

                        error is ApiError.Validation -> {
                            pendingKeys.remove(item.noticeId)
                            actionMessage = error.describe()
                        }

                        error == ApiError.KeyPayloadConflict -> {
                            pendingKeys.remove(item.noticeId)
                            actionMessage = error.describe()
                        }

                        error.isNetworkFailure || error is ApiError.ServiceUnavailable -> {
                            actionMessage = "结果待核对：请重试（不会重复提交）"
                        }

                        error.isSessionExpired -> actionMessage = "登录状态已失效，请重新登录"

                        else -> actionMessage = error.describe()
                    }
                }
            }
            cancellingId = null
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 4.dp, top = 6.dp, bottom = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "我的关注",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            Text(
                text = "刷新",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .clickable { reloadKey += 1 }
                    .padding(horizontal = 8.dp, vertical = 10.dp),
            )
        }

        actionMessage?.let {
            Text(
                text = it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
        }

        Box(modifier = Modifier.fillMaxWidth().weight(1f)) {
            when (val current = state) {
                FollowsUiState.Loading -> LoadingBox()

                FollowsUiState.FeatureUnavailable -> MessageBox(
                    title = followFeature.pendingMessage,
                    detail = "稍后再试",
                )

                is FollowsUiState.Content -> FollowsList(
                    content = current,
                    cancellingId = cancellingId,
                    onOpenNotice = onOpenNotice,
                    onCancel = { cancelFollow(it) },
                    onRetry = { reloadKey += 1 },
                )

                is FollowsUiState.Failed -> WhenFollowsFailed(
                    error = current.error,
                    onRetry = { reloadKey += 1 },
                )
            }
        }
    }
}

@Composable
private fun FollowsList(
    content: FollowsUiState.Content,
    cancellingId: String?,
    onOpenNotice: (String) -> Unit,
    onCancel: (NoticeItem) -> Unit,
    onRetry: () -> Unit,
) {
    val page = content.page
    if (page.items.isEmpty()) {
        if (content.offline) {
            MessageBox(
                title = "当前离线，暂无已加载的关注",
                detail = "缓存时间：${content.cachedAt ?: "未知"}",
                actionText = "重试",
                onAction = onRetry,
            )
        } else {
            MessageBox(
                title = "还没有关注任何通知",
                detail = "在通知详情页点「关注」即可收藏",
                actionText = "刷新",
                onAction = onRetry,
            )
        }
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(vertical = 8.dp),
    ) {
        if (content.offline) {
            item { OfflineBanner(content.cachedAt) }
        }
        items(page.items, key = { it.noticeId }) { item ->
            NoticeCard(
                item = item,
                onClick = { onOpenNotice(item.noticeId) },
                trailing = {
                    Text(
                        text = if (cancellingId == item.noticeId) "取消中…" else "取消关注",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .clickable(enabled = cancellingId == null) { onCancel(item) }
                            .padding(start = 12.dp, top = 4.dp, bottom = 4.dp),
                    )
                },
            )
        }
    }
}

@Composable
private fun WhenFollowsFailed(
    error: ApiError,
    onRetry: () -> Unit,
) {
    when {
        error is ApiError.ContractPending -> MessageBox(
            title = error.describe(),
            detail = "稍后再试",
            actionText = "重试",
            onAction = onRetry,
        )

        error.isSessionExpired -> MessageBox(
            title = "登录状态已失效，请重新登录",
            detail = "只有服务端确认会话失效时才需要重新登录",
            actionText = "重试",
            onAction = onRetry,
        )

        else -> MessageBox(
            title = error.describe(),
            detail = "请检查网络后重试",
            actionText = "重试",
            onAction = onRetry,
        )
    }
}

private sealed interface FollowsUiState {
    data object Loading : FollowsUiState

    data object FeatureUnavailable : FollowsUiState

    data class Content(
        val page: NoticePage,
        val offline: Boolean,
        val cachedAt: String?,
    ) : FollowsUiState

    data class Failed(val error: ApiError) : FollowsUiState
}
