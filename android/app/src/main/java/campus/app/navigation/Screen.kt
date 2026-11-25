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
     * 保存或跳过后继续去「设置我的目标」；从「我的」进来修改时直接回主页面。
     */
    data class ProfileSetup(val onboarding: Boolean = false) : Screen

    /** 注册后的第二步：选择自己的目标倾向，可跳过。 */
    data object Goals : Screen

    /** 底部四个 Tab 的容器。 */
    data object Main : Screen

    /** 「更多」：奖助、日常两类的通知直接展示在同一页。 */
    data object MoreCategories : Screen

    data class Detail(val noticeId: String) : Screen
}
