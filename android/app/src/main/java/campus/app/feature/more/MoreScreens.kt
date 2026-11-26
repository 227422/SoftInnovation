package campus.app.feature.more

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.data.PageResult
import campus.app.core.model.Category
import campus.app.core.model.NoticePage
import campus.app.core.network.ApiError
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import campus.app.feature.common.NoticeCard
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/** 主页之外的两类通知；内容不多，和首页放在同一页里分两段展示。 */
private val SECONDARY_CATEGORIES: List<Category> = listOf(
    Category.FINANCIAL_AID,
    Category.DAILY,
)

/**
 * 更多：直接展示奖助、日常两类的通知，各一段，不再套一层分类菜单。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MoreCategoriesScreen(
    onBack: () -> Unit,
    onOpenNotice: (String) -> Unit,
) {
    val container = LocalAppContainer.current

    var reloadKey by remember { mutableIntStateOf(0) }
    var sections by remember { mutableStateOf<Map<Category, SectionState>>(emptyMap()) }

    LaunchedEffect(container, reloadKey) {
        sections = SECONDARY_CATEGORIES.associateWith { SectionState(loading = true) }
        coroutineScope {
            SECONDARY_CATEGORIES.forEach { category ->
                launch {
                    val next = when (val result = container.notice.feed(category = category)) {
                        is PageResult.Fresh -> SectionState(page = result.page)
                        is PageResult.Cached -> SectionState(page = result.page)
                        is PageResult.Failed -> SectionState(error = result.error)
                    }
                    sections = sections + (category to next)
                }
            }
        }
    }

    val allLoading = sections.values.let { states ->
        states.isEmpty() || states.all { it.loading && it.page == null }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("奖助与日常通知") },
                navigationIcon = { TextButton(onClick = onBack) { Text("返回") } },
            )
        },
    ) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            if (allLoading) {
                LoadingBox()
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    contentPadding = PaddingValues(top = 4.dp, bottom = 16.dp),
                ) {
                    SECONDARY_CATEGORIES.forEach { category ->
                        val section = sections[category] ?: SectionState(loading = true)

                        item(key = "header:${category.wire}") {
                            Text(
                                text = sectionTitle(category),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(start = 4.dp, top = 12.dp, bottom = 2.dp),
                            )
                        }

                        when {
                            section.loading && section.page == null -> item(key = "loading:${category.wire}") {
                                Text(
                                    text = "加载中…",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(start = 4.dp, top = 4.dp),
                                )
                            }

                            section.error != null -> item(key = "error:${category.wire}") {
                                Column(modifier = Modifier.fillMaxWidth().padding(start = 4.dp)) {
                                    Text(
                                        text = section.error.describe(),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.error,
                                    )
                                    TextButton(onClick = { reloadKey += 1 }) { Text("重试") }
                                }
                            }

                            section.page?.items.isNullOrEmpty() -> item(key = "empty:${category.wire}") {
                                Text(
                                    text = "暂时没有通知",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(start = 4.dp, top = 4.dp),
                                )
                            }

                            else -> items(
                                items = section.page!!.items,
                                key = { "${category.wire}:${it.noticeId}" },
                            ) { notice ->
                                NoticeCard(
                                    item = notice,
                                    onClick = { onOpenNotice(notice.noticeId) },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 页面里的段落标题比分类全名短一些。 */
private fun sectionTitle(category: Category): String = when (category) {
    Category.FINANCIAL_AID -> "奖助"
    Category.DAILY -> "日常通知"
    else -> category.label
}

private data class SectionState(
    val page: NoticePage? = null,
    val error: ApiError? = null,
    val loading: Boolean = false,
)
