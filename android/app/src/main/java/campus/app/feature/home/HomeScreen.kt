package campus.app.feature.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.data.PageResult
import campus.app.core.model.NoticePage
import campus.app.core.model.PreferenceKind
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import campus.app.feature.common.MessageBox
import campus.app.feature.common.NoticeListContent
import campus.app.navigation.RequestGate

/** 首页主列表当前使用的内容源；标题会换成用户选择的目标。 */

/**
 * 首页：标题是用户选择的目标，下面只有一列与之相关的通知。
 *
 * 顺序完全按后端返回，不本机重排；每次刷新都重新请求，
 * 并用 [RequestGate] 保证只有最后一次请求能更新界面。
 */
@Composable
fun HomeScreen(
    onOpenNotice: (String) -> Unit,
    onOpenMore: () -> Unit,
) {
    val container = LocalAppContainer.current
    val gate = remember { RequestGate() }
    val feedFeature = container.notice.feedFeature

    var reloadKey by remember { mutableIntStateOf(0) }
    var state by remember { mutableStateOf<HomeUiState>(HomeUiState.Loading) }
    var goalLabels by remember { mutableStateOf<List<String>>(emptyList()) }

    // 标题用用户选过的目标：只有一个时直接用它的名字；
    // 多选时内容本来就是几类合并，用中性说法更准确。
    LaunchedEffect(container) {
        val preferences = (container.profile.loadPreferences() as? ApiResult.Success)?.value
        val goalIds = preferences?.goalIds.orEmpty()
        if (goalIds.isEmpty()) return@LaunchedEffect
        val options = (container.profile.preferenceOptions(PreferenceKind.GOAL) as? ApiResult.Success)?.value
        goalLabels = options?.items.orEmpty()
            .filter { it.id in goalIds }
            .map { it.name }
    }

    LaunchedEffect(container, reloadKey) {
        if (!feedFeature.available) {
            state = HomeUiState.FeatureUnavailable
            return@LaunchedEffect
        }
        val token = gate.next()
        state = HomeUiState.Loading
        val result = container.notice.feed(category = null)
        if (!gate.isCurrent(token)) return@LaunchedEffect
        state = when (result) {
            is PageResult.Fresh -> HomeUiState.Content(result.page)
            is PageResult.Cached -> HomeUiState.Cached(result.page, result.cachedAt)
            is PageResult.Failed -> HomeUiState.Failed(result.error)
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
                text = goalLabels.singleOrNull() ?: "为你推荐",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.widthIn(max = 132.dp),
            )
            Spacer(Modifier.width(10.dp))
            HeaderAction("奖助与日常通知", onOpenMore)
            Spacer(Modifier.weight(1f))
            HeaderAction("刷新") { reloadKey += 1 }
        }

        Box(modifier = Modifier.fillMaxWidth().weight(1f)) {
            when (val current = state) {
                HomeUiState.Loading -> LoadingBox()

                HomeUiState.FeatureUnavailable -> MessageBox(
                    title = feedFeature.pendingMessage,
                    detail = "稍后再试",
                )

                is HomeUiState.Content -> NoticeListContent(
                    items = current.page.items,
                    offline = false,
                    cachedAt = null,
                    onOpenNotice = onOpenNotice,
                    onRetry = { reloadKey += 1 },
                )

                is HomeUiState.Cached -> NoticeListContent(
                    items = current.page.items,
                    offline = true,
                    cachedAt = current.cachedAt,
                    onOpenNotice = onOpenNotice,
                    onRetry = { reloadKey += 1 },
                )

                is HomeUiState.Failed -> WhenFeedFailed(
                    error = current.error,
                    onRetry = { reloadKey += 1 },
                )
            }
        }
    }
}

/** 顶栏的一个文字动作，紧凑排列，避免按钮把标题挤掉。 */
@Composable
private fun HeaderAction(text: String, onClick: () -> Unit) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 10.dp),
    )
}

/** 列表失败：会话失效、接口计划中与普通可重试失败分开说明。 */
@Composable
private fun WhenFeedFailed(
    error: ApiError,
    onRetry: () -> Unit,
) {
    when {
        error.isSessionExpired -> MessageBox(
            title = "登录状态已失效，请重新登录",
            detail = "只有服务端确认会话失效时才需要重新登录",
            actionText = "重试",
            onAction = onRetry,
        )

        error is ApiError.ContractPending -> MessageBox(
            title = error.describe(),
            detail = "稍后再试",
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

/** 首页列表状态。空列表由 [NoticeListContent] 统一呈现为空结果，不在这里另造错误。 */
private sealed interface HomeUiState {
    data object Loading : HomeUiState

    data object FeatureUnavailable : HomeUiState

    data class Content(val page: NoticePage) : HomeUiState

    data class Cached(val page: NoticePage, val cachedAt: String?) : HomeUiState

    data class Failed(val error: ApiError) : HomeUiState
}
