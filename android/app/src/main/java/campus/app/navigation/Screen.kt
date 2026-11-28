package campus.app.navigation

/**
 * 页面路由。
 *
 * 首版页面数不多，继续用密封类型 + 状态切换，不引入 navigation-compose。
 */
sealed interface Screen {
    data object Auth : Screen

    /**
     * 身份资料。[onboarding] 为 true 表示注册后的首次填写，
     * 保存或跳过后进入画像两步；从「我的」进来修改时也走同一条链路。
     */
    data class ProfileSetup(val onboarding: Boolean = false) : Screen

    /** 画像第一步：你的比赛规划，可多选、可跳过。 */
    data object Competition : Screen

    /** 画像第二步：其它希望收到的通知；携带第一步的选择，保存时合并写入。 */
    data class NoticePrefs(val competitionCsv: String = "") : Screen

    /** 底部四个 Tab 的容器。 */
    data object Main : Screen

    /** 「更多」：奖助、日常两类的通知直接展示在同一页。 */
    data object MoreCategories : Screen

    data class Detail(val noticeId: String) : Screen
}
