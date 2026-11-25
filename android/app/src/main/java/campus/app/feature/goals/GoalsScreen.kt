package campus.app.feature.goals

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.material3.OutlinedCard
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
import androidx.compose.ui.Alignment
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
 * 设置目标：注册后的第二步，可以选多个方向（科研/竞赛/升学/就业），也可以跳过。
 *
 * 目标决定主页推送哪几类通知，所以允许多选：选中的每一类都会出现在主页。
 * 选择结果写进已有的偏好（goal_ids），不新增数据结构；
 * 课程、技能、兴趣保持原样，只替换目标这一项。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun GoalsScreen(
    onDone: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    var options by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }
    var optionsLoading by remember { mutableStateOf(true) }
    var optionsError by remember { mutableStateOf<String?>(null) }

    var preferences by remember { mutableStateOf<Preferences?>(null) }
    var preferencesLoading by remember { mutableStateOf(true) }
    var preferencesError by remember { mutableStateOf<String?>(null) }

    // 多选：用逗号拼接保存，避免失去配置变化后的勾选状态。
    var selectedCsv by rememberSaveable { mutableStateOf("") }
    val selectedIds: List<String> = remember(selectedCsv) {
        selectedCsv.split(',').map { it.trim() }.filter { it.isNotEmpty() }
    }
    fun toggle(id: String) {
        selectedCsv = if (id in selectedIds) {
            (selectedIds - id).joinToString(",")
        } else {
            (selectedIds + id).joinToString(",")
        }
    }
    var initialized by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var pendingKey by remember { mutableStateOf<String?>(null) }
    var pendingPayload by remember { mutableStateOf<Preferences?>(null) }

    suspend fun loadOptions() {
        optionsLoading = true
        optionsError = null
        when (val result = container.profile.preferenceOptions(PreferenceKind.GOAL)) {
            is ApiResult.Success -> options = result.value.items
            is ApiResult.Failure -> {
                options = emptyList()
                optionsError = result.error.describe()
            }
        }
        optionsLoading = false
    }

    suspend fun loadPreferences() {
        preferencesLoading = true
        preferencesError = null
        when (val result = container.profile.loadPreferences()) {
            is ApiResult.Success -> {
                preferences = result.value
                if (!initialized) {
                    selectedCsv = result.value.goalIds.joinToString(",")
                    initialized = true
                }
            }

            is ApiResult.Failure -> preferencesError = result.error.describe()
        }
        preferencesLoading = false
    }

    LaunchedEffect(container) {
        coroutineScope {
            launch { loadOptions() }
            launch { loadPreferences() }
        }
    }

    fun submit() {
        if (saving) return
        val current = preferences
        if (current == null) {
            scope.launch {
                snackbar.showSnackbar("目标读取失败，请先重试", duration = SnackbarDuration.Short)
            }
            return
        }
        if (selectedIds.isEmpty()) {
            scope.launch {
                snackbar.showSnackbar("请至少选择一个目标，或直接跳过", duration = SnackbarDuration.Short)
            }
            return
        }

        val payload = current.copy(goalIds = selectedIds)
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
        topBar = { TopAppBar(title = { Text("设置我的目标") }) },
    ) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            if (optionsLoading || preferencesLoading) {
                LoadingBox()
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                ) {
                    if (optionsError != null) {
                        Text(
                            text = "目标读取失败：$optionsError",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        TextButton(onClick = { scope.launch { loadOptions() } }) { Text("重试") }
                    }
                    if (preferencesError != null) {
                        Text(
                            text = "偏好读取失败：$preferencesError",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        TextButton(onClick = { scope.launch { loadPreferences() } }) { Text("重试") }
                    }

                    options.forEach { option ->
                        GoalRow(
                            name = option.name,
                            selected = option.id in selectedIds,
                            enabled = !saving,
                            onClick = { toggle(option.id) },
                        )
                    }
                    if (options.isEmpty() && optionsError == null) {
                        Text("暂无可选项", style = MaterialTheme.typography.bodyMedium)
                    }

                    Spacer(Modifier.height(24.dp))

                    Button(
                        onClick = { submit() },
                        enabled = !saving,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (saving) "保存中…" else "完成")
                    }
                    TextButton(
                        onClick = onDone,
                        enabled = !saving,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("先跳过，以后再说")
                    }

                    Spacer(Modifier.height(16.dp))
                }
            }
        }
    }
}

@Composable
private fun GoalRow(
    name: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    OutlinedCard(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(enabled = enabled, onClick = onClick)
                .padding(14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(name, style = MaterialTheme.typography.bodyLarge)
            if (selected) {
                Text(
                    text = "已选",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}
