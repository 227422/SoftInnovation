package campus.app.feature.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.network.ApiResult
import campus.app.core.session.SessionState
import campus.app.core.ui.describe
import kotlinx.coroutines.launch

/**
 * 登录 / 注册。
 *
 * 账号存在后端，登录成功后资料和目标也都存在后端。
 * 另有「演示账号进入」：用固定账号登录，账号不存在时自动注册，
 * 方便反复试而不用每次输密码。
 */
@Composable
fun AuthScreen(
    onAuthenticated: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val sessionState by container.session.state.collectAsState()

    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var busyAction by remember { mutableStateOf<String?>(null) }
    var requestError by remember { mutableStateOf<String?>(null) }

    fun enter(register: Boolean) {
        if (busyAction != null) return
        requestError = null
        val useEmail = email.trim()
        val usePassword = password
        if (useEmail.isBlank() || usePassword.isBlank()) {
            requestError = "请填写邮箱和密码"
            return
        }
        busyAction = if (register) "register" else "login"
        scope.launch {
            val result = if (register) {
                container.session.register(useEmail, usePassword)
            } else {
                container.session.login(useEmail, usePassword)
            }
            busyAction = null
            when (result) {
                is ApiResult.Success -> {
                    // 注册按"新账号"处理：演示环境下清空样例身份，先进入资料填写。
                    if (register) container.profile.resetForNewAccount()
                    onAuthenticated()
                }

                is ApiResult.Failure -> requestError = result.error.describe()
            }
        }
    }

    /** 演示账号：先在服务器上登录，账号还不存在就直接注册一个。 */
    fun enterDemo() {
        if (busyAction != null) return
        requestError = null
        busyAction = "demo"
        scope.launch {
            var result = container.session.login(DEMO_EMAIL, DEMO_PASSWORD)
            if (result is ApiResult.Failure) {
                result = container.session.register(DEMO_EMAIL, DEMO_PASSWORD)
            }
            busyAction = null
            when (result) {
                is ApiResult.Success -> onAuthenticated()
                is ApiResult.Failure -> requestError = result.error.describe()
            }
        }
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 28.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("知要", style = MaterialTheme.typography.headlineLarge)
            Spacer(Modifier.height(8.dp))
            Text(
                text = "把校内通知，收敛成针对你的一件事",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )

            Spacer(Modifier.height(36.dp))

            OutlinedTextField(
                value = email,
                onValueChange = {
                    email = it
                    requestError = null
                },
                label = { Text("邮箱") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = password,
                onValueChange = {
                    password = it
                    requestError = null
                },
                label = { Text("密码") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
            )

            if (sessionState is SessionState.Loading) {
                Spacer(Modifier.height(16.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                    Text(
                        text = "正在确认登录状态…",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = { enter(register = false) },
                enabled = busyAction == null,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (busyAction == "login") {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text("登录")
            }

            Spacer(Modifier.height(10.dp))

            OutlinedButton(
                onClick = { enter(register = true) },
                enabled = busyAction == null,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (busyAction == "register") {
                    CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text("注册")
            }

            Spacer(Modifier.height(14.dp))

            TextButton(
                onClick = { enterDemo() },
                enabled = busyAction == null,
            ) {
                if (busyAction == "demo") {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text("演示账号进入")
            }

            requestError?.let { message ->
                Spacer(Modifier.height(16.dp))
                Text(
                    text = message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                )
            }

            (sessionState as? SessionState.Failed)?.let { state ->
                Spacer(Modifier.height(16.dp))
                Text(
                    text = state.message,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center,
                )
                TextButton(
                    onClick = {
                        if (busyAction != null) return@TextButton
                        busyAction = "restore"
                        scope.launch {
                            container.session.restore()
                            busyAction = null
                        }
                    },
                    enabled = busyAction == null,
                ) { Text("重试") }
            }
        }
    }
}

/** 演示账号：数据同样存在后端，只是省掉每次输入。 */
private const val DEMO_EMAIL = "demo@csu.edu.cn"
private const val DEMO_PASSWORD = "campus2026"
