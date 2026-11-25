package campus.app.feature.mine

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.model.PreferenceKind
import campus.app.core.model.ProfileResponse
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.AppCard
import kotlinx.coroutines.launch

/**
 * 「我的」：身份与目标两张卡片，都能点进去修改；底部只有退出登录。
 */
@Composable
fun MineScreen(
    onEditProfile: () -> Unit,
    onOpenGoals: () -> Unit,
    onLoggedOut: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()

    var profileResponse by remember { mutableStateOf<ProfileResponse?>(null) }
    var profileError by remember { mutableStateOf<String?>(null) }
    var profileLoading by remember { mutableStateOf(true) }
    var goalLabel by remember { mutableStateOf<String?>(null) }
    var loggingOut by remember { mutableStateOf(false) }

    LaunchedEffect(container) {
        profileLoading = true
        profileError = null
        profileResponse = null

        when (val result = container.profile.load()) {
            is ApiResult.Success -> profileResponse = result.value
            is ApiResult.Failure -> profileError = result.error.describe()
        }
        profileLoading = false

        // 目标名称：从偏好里取 id，再在目标目录里换成文字。
        val preferences = (container.profile.loadPreferences() as? ApiResult.Success)?.value
        val goalIds = preferences?.goalIds.orEmpty()
        goalLabel = if (goalIds.isEmpty()) {
            null
        } else {
            val options = (container.profile.preferenceOptions(PreferenceKind.GOAL) as? ApiResult.Success)?.value
            val names = options?.items.orEmpty()
                .filter { it.id in goalIds }
                .map { it.name }
            when {
                names.isEmpty() -> null
                names.size == 1 -> names.first()
                else -> "${names.first()} 等 ${names.size} 项"
            }
        }
    }

    fun logout() {
        if (loggingOut) return
        loggingOut = true
        scope.launch {
            // 服务端撤销失败也要回到登录页；退出只清除本机会话。
            runCatching { container.session.logout() }
            onLoggedOut()
        }
    }

    val profile = profileResponse?.profile
    val completed = profileResponse?.completed == true && profile != null
    val schoolName = profile?.schoolName?.takeIf { it.isNotBlank() }
    val detailLine = listOfNotNull(
        profile?.collegeName?.takeIf { it.isNotBlank() },
        profile?.majorName?.takeIf { it.isNotBlank() },
        profile?.grade?.let { "第${it}年" },
    ).joinToString(" · ")

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
    ) {
        // ------------------------------------------------ 身份
        AppCard(
            modifier = Modifier.fillMaxWidth(),
            onClick = onEditProfile,
            innerPadding = 16.dp,
        ) {
            Text(
                text = "我的身份",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = when {
                        profileLoading -> "正在读取…"
                        completed && schoolName != null -> schoolName
                        else -> "未填写"
                    },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = "修改",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
            if (!profileLoading && detailLine.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = detailLine,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            profileError?.let { message ->
                Spacer(Modifier.height(4.dp))
                Text(
                    text = "读取失败：$message",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        // ------------------------------------------------ 目标
        AppCard(
            modifier = Modifier.fillMaxWidth(),
            onClick = onOpenGoals,
            innerPadding = 16.dp,
        ) {
            Text(
                text = "我的目标",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = goalLabel ?: "未设置",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = "修改",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }

        Spacer(Modifier.height(24.dp))

        OutlinedButton(
            onClick = { logout() },
            enabled = !loggingOut,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (loggingOut) "正在退出…" else "退出登录")
        }

        Spacer(Modifier.height(16.dp))
    }
}
