package campus.app.feature.goals

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.model.CatalogNode
import campus.app.core.model.PreferenceKind
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/** 第一步的选项前缀；第二步用 [NOTICE_PREFIX]。 */
internal const val COMPETITION_PREFIX = "goal_comp_"
internal const val NOTICE_PREFIX = "goal_notice_"

/**
 * 设置画像第一步：你的比赛规划。
 *
 * 比赛是这类通知里最主要的一类，所以单独一步、允许选多个方向；
 * 选完（或跳过后）进入第二步，选其它希望收到的通知。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GoalsScreen(
    onNext: (List<String>) -> Unit,
) {
    val container = LocalAppContainer.current

    var options by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }

    var selectedCsv by rememberSaveable { mutableStateOf("") }
    val selectedIds: List<String> = remember(selectedCsv) { splitIds(selectedCsv) }

    LaunchedEffect(container) {
        coroutineScope {
            launch {
                when (val result = container.profile.preferenceOptions(PreferenceKind.GOAL)) {
                    is ApiResult.Success -> options = result.value.items
                    is ApiResult.Failure -> loadError = result.error.describe()
                }
                loading = false
            }
            launch {
                // 已经选过的回填；只取本页相关的项。
                val preferences = (container.profile.loadPreferences() as? ApiResult.Success)?.value
                if (selectedCsv.isBlank()) {
                    selectedCsv = preferences?.goalIds.orEmpty()
                        .filter { it.startsWith(COMPETITION_PREFIX) }
                        .joinToString(",")
                }
            }
        }
    }

    fun toggle(id: String) {
        selectedCsv = if (id in selectedIds) {
            (selectedIds - id).joinToString(",")
        } else {
            (selectedIds + id).joinToString(",")
        }
    }

    Scaffold(topBar = { TopAppBar(title = { Text("你的比赛规划") }) }) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            if (loading) {
                LoadingBox()
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    Text(
                        text = "比赛是大学里投入产出最高的事之一\n你想从比赛里得到什么？",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(14.dp))

                    loadError?.let {
                        Text(
                            text = "选项读取失败：$it",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Spacer(Modifier.height(8.dp))
                    }

                    options
                        .filter { it.id.startsWith(COMPETITION_PREFIX) }
                        .forEach { option ->
                            ChoiceRow(
                                title = option.name,
                                hint = option.hint,
                                selected = option.id in selectedIds,
                                enabled = true,
                                onClick = { toggle(option.id) },
                            )
                        }

                    Spacer(Modifier.height(20.dp))

                    Button(
                        onClick = { onNext(selectedIds) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("下一步")
                    }

                    TextButton(
                        onClick = { onNext(emptyList()) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(
                            text = "跳过",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }

                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }
}

internal fun splitIds(csv: String): List<String> =
    csv.split(',').map { it.trim() }.filter { it.isNotEmpty() }
