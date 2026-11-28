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
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.model.CatalogNode
import campus.app.core.model.PreferenceKind
import campus.app.core.model.Preferences
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/**
 * 设置画像第二步：除了比赛，还想收哪些通知。
 *
 * 与第一步同样的多选交互；保存时把两步的选择合并写进 goal_ids，
 * 一次请求完成，避免中途失败只存一半。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NoticePrefsScreen(
    competitionIds: List<String>,
    onDone: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var options by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }
    var preferences by remember { mutableStateOf<Preferences?>(null) }
    var loading by remember { mutableStateOf(true) }
    var loadError by remember { mutableStateOf<String?>(null) }

    var selectedCsv by rememberSaveable { mutableStateOf("") }
    var initialized by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var pendingKey by remember { mutableStateOf<String?>(null) }
    var pendingPayload by remember { mutableStateOf<Preferences?>(null) }

    val selectedIds: List<String> = remember(selectedCsv) { splitIds(selectedCsv) }

    suspend fun loadAll() {
        loading = true
        loadError = null
        coroutineScope {
            launch {
                when (val result = container.profile.preferenceOptions(PreferenceKind.GOAL)) {
                    is ApiResult.Success -> options = result.value.items
                    is ApiResult.Failure -> loadError = result.error.describe()
                }
            }
            launch {
                when (val result = container.profile.loadPreferences()) {
                    is ApiResult.Success -> {
                        preferences = result.value
                        if (!initialized) {
                            selectedCsv = result.value.goalIds
                                .filter { it.startsWith(NOTICE_PREFIX) }
                                .joinToString(",")
                            initialized = true
                        }
                    }

                    is ApiResult.Failure -> loadError = result.error.describe()
                }
            }
        }
        loading = false
    }

    LaunchedEffect(container) { loadAll() }

    fun toggle(id: String) {
        selectedCsv = if (id in selectedIds) {
            (selectedIds - id).joinToString(",")
        } else {
            (selectedIds + id).joinToString(",")
        }
    }

    fun submit(noticeIds: List<String>) {
        if (saving) return
        val current = preferences
        if (current == null) {
            scope.launch {
                snackbar.showSnackbar("偏好读取失败，请先重试", duration = SnackbarDuration.Short)
            }
            return
        }
        // 旧版目标（goal_research 等）已不在目录里，这里直接以本次两步的选择为准。
        val payload = current.copy(goalIds = competitionIds + noticeIds)
        val key = if (pendingKey != null && pendingPayload == payload) {
            pendingKey.orEmpty()
        } else {
            container.profile.newIdempotencyKey().also {
                pendingKey = it
                pendingPayload = payload
            }
        }

        saving = true
        scope.launch {
            when (val result = container.profile.savePreferences(payload, key)) {
                is ApiResult.Success -> {
                    saving = false
                    pendingKey = null
                    pendingPayload = null
                    onDone()
                }

                is ApiResult.Failure -> {
                    saving = false
                    snackbar.showSnackbar(
                        message = result.error.describe() + "，可重试",
                        duration = SnackbarDuration.Long,
                    )
                }
            }
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text("其它通知推送") }) },
    ) { padding ->
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
                        text = "除了比赛，你还希望我们推送哪些通知？",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(14.dp))

                    loadError?.let {
                        Text(
                            text = "读取失败：$it",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Spacer(Modifier.height(8.dp))
                    }

                    options
                        .filter { it.id.startsWith(NOTICE_PREFIX) }
                        .forEach { option ->
                            ChoiceRow(
                                title = option.name,
                                hint = option.hint,
                                selected = option.id in selectedIds,
                                enabled = !saving,
                                onClick = { toggle(option.id) },
                            )
                        }

                    Spacer(Modifier.height(20.dp))

                    Button(
                        onClick = { submit(selectedIds) },
                        enabled = !saving,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (saving) "保存中…" else "下一步")
                    }

                    // 跳过＝这一页不动：保留原来的通知类型，直接结束流程。
                    TextButton(
                        onClick = {
                            submit(
                                preferences?.goalIds.orEmpty()
                                    .filter { it.startsWith(NOTICE_PREFIX) },
                            )
                        },
                        enabled = !saving,
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
