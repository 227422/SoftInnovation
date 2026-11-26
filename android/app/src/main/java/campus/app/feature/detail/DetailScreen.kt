package campus.app.feature.detail

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import campus.app.core.LocalAppContainer
import campus.app.core.data.DetailResult
import campus.app.core.model.AccessReason
import campus.app.core.model.AttachmentInfo
import campus.app.core.model.FollowState
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticeItem
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.ui.DateDisplay
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import campus.app.feature.common.MessageBox
import campus.app.feature.common.OfflineBanner
import campus.app.feature.common.SectionTitle
import campus.app.navigation.RequestGate
import kotlinx.coroutines.launch

/**
 * 通知详情：标题 → 来源 → 时间与状态 → 正文 → 官方原文 → 附件，底部只有关注。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DetailScreen(
    noticeId: String,
    onBack: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val gate = remember { RequestGate() }
    val followFeature = container.notice.followFeature

    var reloadKey by remember { mutableIntStateOf(0) }
    var state by remember { mutableStateOf<DetailUiState>(DetailUiState.Loading) }
    var follow by remember { mutableStateOf<FollowState?>(null) }
    var followBusy by remember { mutableStateOf(false) }
    var followMessage by remember { mutableStateOf<String?>(null) }
    // 同一个逻辑操作的幂等键：网络失败重试时复用，成功后清空，版本/校验冲突后换新键。
    var pendingKey by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(container, noticeId, reloadKey) {
        val token = gate.next()
        state = DetailUiState.Loading
        followMessage = null
        pendingKey = null
        val result = container.notice.detail(noticeId)
        if (!gate.isCurrent(token)) return@LaunchedEffect
        when (result) {
            is DetailResult.Fresh -> {
                state = DetailUiState.Content(result.detail, offline = false, cachedAt = null)
                follow = result.detail.item.follow
            }

            is DetailResult.Cached -> {
                state = DetailUiState.Content(result.detail, offline = true, cachedAt = result.cachedAt)
                follow = result.detail.item.follow
            }

            is DetailResult.Failed -> state = DetailUiState.Failed(result.error)
        }
    }

    fun toggleFollow() {
        if (followBusy) return
        val current = follow ?: (state as? DetailUiState.Content)?.detail?.item?.follow ?: return
        val target = !current.starred
        val key = pendingKey ?: container.notice.newIdempotencyKey().also { pendingKey = it }
        followBusy = true
        followMessage = null
        scope.launch {
            val result = container.notice.setFollow(
                noticeId = noticeId,
                starred = target,
                expectedVersion = current.version,
                idempotencyKey = key,
            )
            when (result) {
                is ApiResult.Success -> {
                    follow = result.value
                    pendingKey = null
                    followMessage = if (result.value.starred) "已关注" else "已取消关注"
                }

                is ApiResult.Failure -> {
                    val error = result.error
                    when {
                        error == ApiError.VersionConflict -> {
                            pendingKey = null
                            when (val refreshed = container.notice.detail(noticeId)) {
                                is DetailResult.Fresh -> {
                                    state = DetailUiState.Content(refreshed.detail, offline = false, cachedAt = null)
                                    follow = refreshed.detail.item.follow
                                }

                                is DetailResult.Cached -> {
                                    state = DetailUiState.Content(refreshed.detail, offline = true, cachedAt = refreshed.cachedAt)
                                    follow = refreshed.detail.item.follow
                                }

                                is DetailResult.Failed -> Unit
                            }
                            followMessage = "关注状态已在其他设备更新，已重新读取，请确认后再试"
                        }

                        error is ApiError.Validation -> {
                            pendingKey = null
                            followMessage = error.describe()
                        }

                        error == ApiError.KeyPayloadConflict -> {
                            pendingKey = null
                            followMessage = error.describe()
                        }

                        error.isNetworkFailure || error is ApiError.ServiceUnavailable -> {
                            followMessage = "结果待核对：请重试（不会重复提交）"
                        }

                        error.isSessionExpired -> followMessage = "登录状态已失效，请重新登录"

                        else -> {
                            pendingKey = null
                            followMessage = error.describe()
                        }
                    }
                }
            }
            followBusy = false
        }
    }

    val contentState = state as? DetailUiState.Content

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("通知详情") },
                navigationIcon = { TextButton(onClick = onBack) { Text("返回") } },
            )
        },
        bottomBar = {
            if (contentState != null) {
                FollowBar(
                    available = followFeature.available,
                    starred = (follow ?: contentState.detail.item.follow).starred,
                    busy = followBusy,
                    message = followMessage,
                    onToggle = { toggleFollow() },
                )
            }
        },
    ) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            when (val current = state) {
                DetailUiState.Loading -> LoadingBox()

                is DetailUiState.Content -> DetailContent(
                    detail = current.detail,
                    follow = follow ?: current.detail.item.follow,
                    offline = current.offline,
                    cachedAt = current.cachedAt,
                )

                is DetailUiState.Failed -> WhenDetailFailed(
                    error = current.error,
                    onRetry = { reloadKey += 1 },
                    onBack = onBack,
                )
            }
        }
    }
}

@Composable
private fun WhenDetailFailed(
    error: ApiError,
    onRetry: () -> Unit,
    onBack: () -> Unit,
) {
    when {
        error is ApiError.ContractPending -> MessageBox(
            title = error.describe(),
            detail = "稍后再试",
            actionText = "返回",
            onAction = onBack,
            actionSecondaryText = "重试",
            onActionSecondary = onRetry,
        )

        error.isSessionExpired -> MessageBox(
            title = "登录状态已失效，请重新登录",
            detail = "网络失败不会导致退出登录",
            actionText = "返回",
            onAction = onBack,
        )

        else -> MessageBox(
            title = error.describe(),
            detail = "请检查网络后重试",
            actionText = "重试",
            onAction = onRetry,
            actionSecondaryText = "返回",
            onActionSecondary = onBack,
        )
    }
}

@Composable
private fun DetailContent(
    detail: NoticeDetail,
    follow: FollowState,
    offline: Boolean,
    cachedAt: String?,
) {
    val item: NoticeItem = detail.item.copy(follow = follow)
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        if (offline) {
            OfflineBanner(cachedAt)
            Spacer(Modifier.height(12.dp))
        }

        Text(
            text = item.title,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = "${item.sourceName ?: "来源未知"} · 发布于 ${DateDisplay.published(item.publishedAt)}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        val timeStatus = timeStatusText(item)
        if (timeStatus.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                text = timeStatus,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        Spacer(Modifier.height(16.dp))
        BodyText(detail)

        officialUrl(detail)?.let { url ->
            SectionTitle("官方原文")
            LinkText(url)
        }

        if (detail.attachments.isNotEmpty()) {
            SectionTitle("附件")
            detail.attachments.forEach { attachment ->
                AttachmentRow(attachment)
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

/** 时间与文件状态合成一行，原样显示后端文本，不再做标签。 */
private fun timeStatusText(item: NoticeItem): String = buildList {
    addAll(item.dateLabels.map { it.text })
    addAll(item.statusLabels.map { it.text.ifBlank { it.code.label } })
}
    .map { it.trim() }
    .filter { it.isNotEmpty() }
    .joinToString("　")

private fun officialUrl(detail: NoticeDetail): String? =
    detail.sourceUrl?.takeIf { it.isNotBlank() }
        ?: detail.sources.firstOrNull { !it.url.isNullOrBlank() }?.url

/**
 * 正文。用细描边 + 左侧一道竖线把它和标题、链接区分开，
 * 只做一层区分，不加底色和阴影。
 */
@Composable
private fun BodyText(detail: NoticeDetail) {
    val body = detail.body
    val missing = body.isNullOrBlank()
    val text = if (missing) {
        when (detail.item.accessReason) {
            AccessReason.NONE -> "正文暂未取得"
            else -> detail.item.accessReason.text
        }
    } else {
        body.orEmpty()
    }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.outlineVariant,
                shape = RoundedCornerShape(12.dp),
            )
            .padding(horizontal = 14.dp, vertical = 14.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .width(3.dp)
                .fillMaxHeight()
                .background(
                    color = MaterialTheme.colorScheme.primary.copy(alpha = 0.8f),
                    shape = RoundedCornerShape(2.dp),
                ),
        )
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            lineHeight = 26.sp,
            color = if (missing) {
                MaterialTheme.colorScheme.onSurfaceVariant
            } else {
                MaterialTheme.colorScheme.onSurface
            },
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun AttachmentRow(attachment: AttachmentInfo) {
    Text(
        text = attachment.name,
        style = MaterialTheme.typography.bodySmall,
        fontWeight = FontWeight.Medium,
    )
    val url = attachment.url?.takeIf { it.isNotBlank() }
    if (url != null) {
        LinkText(url)
    } else {
        Text(
            text = attachment.status.label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
    Spacer(Modifier.height(6.dp))
}

/** 直接显示网址本身，点击用浏览器打开。 */
@Composable
private fun LinkText(url: String) {
    val context = LocalContext.current
    Text(
        text = url,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier
            .clickable {
                runCatching {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                }
            }
            .padding(vertical = 2.dp),
    )
}

/** 底部固定关注栏。关注是收藏，不代表报名。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FollowBar(
    available: Boolean,
    starred: Boolean,
    busy: Boolean,
    message: String?,
    onToggle: () -> Unit,
) {
    Surface(tonalElevation = 3.dp) {
        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
            message?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.height(6.dp))
            }
            if (available) {
                FilterChip(
                    selected = starred,
                    onClick = onToggle,
                    enabled = !busy,
                    label = { Text(if (starred) "已关注" else "关注") },
                )
            } else {
                FilterChip(
                    selected = false,
                    onClick = {},
                    enabled = false,
                    label = { Text("关注") },
                )
            }
        }
    }
}

private sealed interface DetailUiState {
    data object Loading : DetailUiState

    data class Content(
        val detail: NoticeDetail,
        val offline: Boolean,
        val cachedAt: String?,
    ) : DetailUiState

    data class Failed(val error: ApiError) : DetailUiState
}
