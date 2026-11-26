package campus.app.feature.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import campus.app.core.model.NoticeItem

/**
 * 全站统一的卡片外观：细描边 + 12dp 圆角，不加阴影。
 * 列表、更多页、我的都走这一个，避免各页各画一套。
 */
@Composable
fun AppCard(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    innerPadding: Dp = 14.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    val clickableModifier = if (onClick != null) modifier.clickable(onClick = onClick) else modifier
    OutlinedCard(
        modifier = clickableModifier,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(innerPadding),
            content = content,
        )
    }
}

/**
 * 通知卡片（首页与更多页共用）。
 *
 * 只保留标题和一行时间；来源、收益、面向群体、状态等都不在卡片上出现，
 * 点进详情再看。
 */
@Composable
fun NoticeCard(
    item: NoticeItem,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    /** 卡片内右下角的小操作（例如关注页的「取消关注」），不额外占一行。 */
    trailing: (@Composable () -> Unit)? = null,
) {
    val timeText = item.dateLabels
        .map { it.text.trim() }
        .filter { it.isNotEmpty() }
        .joinToString("　")

    AppCard(onClick = onClick, modifier = modifier.fillMaxWidth()) {
        Text(
            text = item.title,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.Medium,
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
        )
        if (timeText.isNotEmpty() || trailing != null) {
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = timeText,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                trailing?.invoke()
            }
        }
    }
}

/** 一页通知列表（含离线横幅）。 */
@Composable
fun NoticeListContent(
    items: List<NoticeItem>,
    offline: Boolean,
    cachedAt: String?,
    onOpenNotice: (String) -> Unit,
    onRetry: () -> Unit,
) {
    if (items.isEmpty()) {
        MessageBox(
            title = "暂时没有通知",
            detail = "稍后刷新再看看",
            actionText = "刷新",
            onAction = onRetry,
        )
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(vertical = 12.dp),
    ) {
        if (offline) {
            item { OfflineBanner(cachedAt) }
        }
        items(items, key = { it.noticeId }) { notice ->
            NoticeCard(item = notice, onClick = { onOpenNotice(notice.noticeId) })
        }
    }
}

@Composable
fun OfflineBanner(cachedAt: String?) {
    OutlinedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text("当前离线，显示的是缓存内容", style = MaterialTheme.typography.bodySmall)
            Text(
                text = "缓存时间：${cachedAt ?: "未知"}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** 加载态。 */
@Composable
fun LoadingBox(text: String = "加载中…") {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator(modifier = Modifier.height(26.dp), strokeWidth = 2.dp)
        Spacer(Modifier.height(10.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** 空/错误/提示的统一版式。 */
@Composable
fun MessageBox(
    title: String,
    detail: String? = null,
    actionText: String? = null,
    onAction: (() -> Unit)? = null,
    actionSecondaryText: String? = null,
    onActionSecondary: (() -> Unit)? = null,
    danger: Boolean = false,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.bodyMedium,
            color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface,
            textAlign = TextAlign.Center,
        )
        if (detail != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = detail,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        if (actionText != null && onAction != null) {
            Spacer(Modifier.height(12.dp))
            Button(onClick = onAction) { Text(actionText) }
        }
        if (actionSecondaryText != null && onActionSecondary != null) {
            TextButton(onClick = onActionSecondary) { Text(actionSecondaryText) }
        }
    }
}

/** 区块标题（详情页用）。 */
@Composable
fun SectionTitle(title: String, modifier: Modifier = Modifier) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.SemiBold,
        modifier = modifier.padding(top = 16.dp, bottom = 6.dp),
    )
}
