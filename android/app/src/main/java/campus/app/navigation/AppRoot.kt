package campus.app.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import campus.app.core.AppContainer
import campus.app.core.LocalAppContainer
import campus.app.core.network.ApiResult
import campus.app.core.network.Env
import campus.app.core.session.SessionState
import campus.app.feature.auth.AuthScreen
import campus.app.feature.detail.DetailScreen
import campus.app.feature.goals.GoalsScreen
import campus.app.feature.goals.NoticePrefsScreen
import campus.app.feature.goals.splitIds
import campus.app.feature.main.MainScreen
import campus.app.feature.main.MainTab
import campus.app.feature.more.MoreCategoriesScreen
import campus.app.feature.profile.ProfileSetupScreen
import kotlinx.coroutines.launch

/**
 * 应用根节点：依赖装配、会话恢复与页面切换。
 *
 * 启动流程：先恢复会话再看页面。
 * - 恢复成功 → 已保存过身份资料进主页面，否则进资料页；
 * - 明确失效 → 登录页；
 * - 无法确认（断网/503）→ 停在登录页，但登录页给出可重试入口，不误报密码错。
 */
@Composable
fun AppRoot() {
    val context = LocalContext.current.applicationContext
    val container = remember { AppContainer(context, Env.current) }

    CompositionLocalProvider(LocalAppContainer provides container) {
        AppNavigation()
    }
}

@Composable
private fun AppNavigation() {
    val container = LocalAppContainer.current
    val sessionState by container.session.state.collectAsState()
    val scope = rememberCoroutineScope()

    var current by rememberSaveable(stateSaver = ScreenSaver) {
        mutableStateOf<Screen>(Screen.Auth)
    }
    var mainTabIndex by rememberSaveable { mutableIntStateOf(0) }
    val gate = remember { RequestGate() }

    LaunchedEffect(container) {
        container.session.restore()
    }

    // 会话变化只处理"必须离开当前页"的情形，其余保存草稿的页面自己负责。
    LaunchedEffect(sessionState) {
        when (sessionState) {
            is SessionState.LoggedIn -> if (current is Screen.Auth) current = Screen.Main
            is SessionState.LoggedOut -> {
                current = Screen.Auth
                mainTabIndex = 0
            }

            else -> Unit
        }
    }

    fun navigateTo(screen: Screen) {
        gate.next()
        current = screen
    }

    fun afterAuthenticated() {
        mainTabIndex = 0
        scope.launch {
            val next = when (val result = container.profile.load()) {
                is ApiResult.Success ->
                    if (result.value.completed) Screen.Main else Screen.ProfileSetup(onboarding = true)

                is ApiResult.Failure -> Screen.ProfileSetup(onboarding = true)
            }
            navigateTo(next)
        }
    }

    val mainTab = MainTab.entries.getOrElse(mainTabIndex) { MainTab.HOME }

    when (val screen = current) {
        is Screen.Auth -> AuthScreen(
            onAuthenticated = { afterAuthenticated() },
        )

        is Screen.ProfileSetup -> ProfileSetupScreen(
            continueLabel = if (screen.onboarding) "下一步" else "保存",
            onContinue = {
                navigateTo(if (screen.onboarding) Screen.Competition else Screen.Main)
            },
        )

        is Screen.Competition -> GoalsScreen(
            onNext = { ids -> navigateTo(Screen.NoticePrefs(ids.joinToString(","))) },
        )

        is Screen.NoticePrefs -> NoticePrefsScreen(
            competitionIds = splitIds(screen.competitionCsv),
            onDone = { navigateTo(Screen.Main) },
        )

        is Screen.Main -> MainScreen(
            tab = mainTab,
            onTabSelected = { mainTabIndex = it.ordinal },
            onOpenNotice = { noticeId -> navigateTo(Screen.Detail(noticeId)) },
            onOpenMore = { navigateTo(Screen.MoreCategories) },
            onEditProfile = { navigateTo(Screen.ProfileSetup(onboarding = false)) },
            onOpenGoals = { navigateTo(Screen.Competition) },
            onLoggedOut = { navigateTo(Screen.Auth) },
        )

        is Screen.MoreCategories -> MoreCategoriesScreen(
            onBack = { navigateTo(Screen.Main) },
            onOpenNotice = { noticeId -> navigateTo(Screen.Detail(noticeId)) },
        )

        is Screen.Detail -> DetailScreen(
            noticeId = screen.noticeId,
            onBack = { navigateTo(Screen.Main) },
        )
    }
}

/** 只保存"当前在哪个页面"，不带业务草稿；草稿由各页面自己保留。 */
private val ScreenSaver = Saver<Screen, String>(
    save = { screen ->
        when (screen) {
            is Screen.Auth -> "auth"
            is Screen.ProfileSetup -> "profile:${screen.onboarding}"
            is Screen.Competition -> "competition"
            is Screen.NoticePrefs -> "notices:${screen.competitionCsv}"
            is Screen.Main -> "main"
            is Screen.MoreCategories -> "more"
            is Screen.Detail -> "detail:${screen.noticeId}"
        }
    },
    restore = { raw ->
        when {
            raw == "auth" -> Screen.Auth
            raw == "profile" -> Screen.ProfileSetup()
            raw.startsWith("profile:") -> Screen.ProfileSetup(raw.removePrefix("profile:").toBoolean())
            raw == "competition" -> Screen.Competition
            raw == "goals" -> Screen.Competition
            raw.startsWith("notices:") -> Screen.NoticePrefs(raw.removePrefix("notices:"))
            raw == "main" || raw == "home" -> Screen.Main
            raw == "more" -> Screen.MoreCategories
            raw.startsWith("detail:") -> Screen.Detail(raw.removePrefix("detail:"))
            else -> Screen.Auth
        }
    },
)
