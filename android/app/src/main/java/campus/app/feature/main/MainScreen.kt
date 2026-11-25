package campus.app.feature.main

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import campus.app.feature.follows.FollowsScreen
import campus.app.feature.home.HomeScreen
import campus.app.feature.mine.MineScreen

/** 底部导航的四个入口。 */
enum class MainTab(val label: String) {
    HOME("主页"),
    FOLLOWS("关注"),
    COMMUNITY("社区"),
    MINE("我的"),
}

/**
 * 主容器：底部四个 Tab，页面切换不重建外层。
 *
 * 详情、更多、设置资料等页面仍然整页替换，返回时回到原来的 Tab。
 */
@Composable
fun MainScreen(
    tab: MainTab,
    onTabSelected: (MainTab) -> Unit,
    onOpenNotice: (String) -> Unit,
    onOpenMore: () -> Unit,
    onEditProfile: () -> Unit,
    onOpenGoals: () -> Unit,
    onLoggedOut: () -> Unit,
) {
    Scaffold(
        bottomBar = { BottomNav(selected = tab, onSelect = onTabSelected) },
    ) { padding ->
        Box(modifier = Modifier.padding(padding).fillMaxSize()) {
            when (tab) {
                MainTab.HOME -> HomeScreen(
                    onOpenNotice = onOpenNotice,
                    onOpenMore = onOpenMore,
                )

                MainTab.FOLLOWS -> FollowsScreen(
                    onOpenNotice = onOpenNotice,
                )

                MainTab.COMMUNITY -> CommunityScreen()

                MainTab.MINE -> MineScreen(
                    onEditProfile = onEditProfile,
                    onOpenGoals = onOpenGoals,
                    onLoggedOut = onLoggedOut,
                )
            }
        }
    }
}

@Composable
private fun BottomNav(
    selected: MainTab,
    onSelect: (MainTab) -> Unit,
) {
    Surface(tonalElevation = 3.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .height(56.dp),
        ) {
            MainTab.entries.forEach { item ->
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .clickable { onSelect(item) },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = item.label,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (item == selected) FontWeight.SemiBold else FontWeight.Normal,
                        color = if (item == selected) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
        }
    }
}

/** 社区：暂未开始，只保留入口。 */
@Composable
fun CommunityScreen() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = "社区还在准备中",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
