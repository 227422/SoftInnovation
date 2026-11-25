package campus.app.core.model

/**
 * 界面用到的数据结构，字段与语义以 `docs/contracts/app-v2/openapi.json`
 * （契约版本 undergrad-app/2）为准。
 *
 * 三条硬规则：
 * - 未知一律是 `UNKNOWN` 或 `null`，不用 0、空串、"符合"顶替；
 * - 界面不出现分数，顺序完全由后端返回决定；
 * - 日期/收益/面向群体/文件状态标签由后端生成，前端只显示，不从中文文本反推日期或优先级。
 */

/** 首版三类。[wire] 是列表查询参数取值。unknown 是"待确认"容器，不单独成 Tab。 */
enum class Category(val label: String, val wire: String) {
    RESEARCH_INNOVATION("科研、竞赛与创新", "research_innovation"),
    FINANCIAL_AID("奖助与学生权益", "financial_aid"),
    DAILY("日常通知", "daily"),
    UNKNOWN("待确认", "unknown"),
    ;

    companion object {
        /** 首页三个 Tab，不含 UNKNOWN。 */
        val tabs: List<Category> = listOf(RESEARCH_INNOVATION, FINANCIAL_AID, DAILY)

        fun from(raw: String?): Category = when (raw?.trim()?.lowercase()) {
            "research_innovation" -> RESEARCH_INNOVATION
            "financial_aid" -> FINANCIAL_AID
            "daily" -> DAILY
            else -> UNKNOWN
        }
    }
}

/** 个人相关性。与"资格是否满足"分开，不在这里下结论。 */
enum class MatchState(val label: String) {
    RELEVANT("相关"),
    POSSIBLE("可能相关"),
    IRRELEVANT("不相关"),
    UNKNOWN("匹配待确认"),
    ;

    companion object {
        fun from(raw: String?): MatchState = when (raw?.trim()?.lowercase()) {
            "relevant" -> RELEVANT
            "possible" -> POSSIBLE
            "irrelevant" -> IRRELEVANT
            else -> UNKNOWN
        }
    }
}

/** 资格核对结论。未核实时不得显示为"符合"。 */
enum class EligibilityState {
    MET, NOT_MET, UNKNOWN;

    companion object {
        fun from(raw: String?): EligibilityState = when (raw?.trim()?.lowercase()) {
            "met" -> MET
            "not_met" -> NOT_MET
            else -> UNKNOWN
        }
    }
}

data class MatchInfo(
    val state: MatchState = MatchState.UNKNOWN,
    val reasons: List<String> = emptyList(),
    val eligibility: EligibilityState = EligibilityState.UNKNOWN,
    val evaluatedProfileVersion: Long? = null,
)

/** 时间窗口状态。UNKNOWN 不得用于自动隐藏、倒计时或"长期有效"判定。 */
enum class WindowState {
    UPCOMING, OPEN, CLOSED, UNKNOWN;

    companion object {
        fun from(raw: String?): WindowState = when (raw?.trim()?.lowercase()) {
            "upcoming" -> UPCOMING
            "open" -> OPEN
            "closed" -> CLOSED
            else -> UNKNOWN
        }
    }
}

/** 日期标签分组：报名/办理、事项举行、政策有效期；null 表示整条期限提示。 */
enum class DateGroup(val label: String) {
    HANDLING("报名/办理"),
    EVENT("事项举行"),
    POLICY_VALIDITY("政策有效期"),
    UNSPECIFIED("其他提示"),
    ;

    companion object {
        fun from(raw: String?): DateGroup = when (raw?.trim()?.lowercase()) {
            "handling" -> HANDLING
            "event" -> EVENT
            "policy_validity" -> POLICY_VALIDITY
            else -> UNSPECIFIED
        }

        /** 详情页按此顺序分组展示。 */
        val ordered: List<DateGroup> = listOf(HANDLING, EVENT, POLICY_VALIDITY, UNSPECIFIED)
    }
}

/**
 * 后端生成的日期标签，例如"报名：11/12—11/18""期限未注明""时间待确认"。
 * 前端原样显示，不解析文本里的日期。
 */
data class DateLabel(
    val text: String,
    val state: WindowState = WindowState.UNKNOWN,
    val windowId: String? = null,
    val group: DateGroup = DateGroup.UNSPECIFIED,
)

/** 收益核验状态。PENDING 时界面必须显示"待确认"。 */
enum class BenefitVerificationState {
    CONFIRMED, PENDING;

    companion object {
        fun from(raw: String?): BenefitVerificationState =
            if (raw?.trim()?.lowercase() == "confirmed") CONFIRMED else PENDING
    }
}

/** 收益是否适用于当前用户。未知不等于适用，也不等于不适用。 */
enum class Applicability {
    APPLICABLE, NOT_APPLICABLE, UNKNOWN;

    companion object {
        fun from(raw: String?): Applicability = when (raw?.trim()?.lowercase()) {
            "applicable" -> APPLICABLE
            "not_applicable" -> NOT_APPLICABLE
            else -> UNKNOWN
        }
    }
}

/** 契约第五节九种收益类型。只表达"有没有、有什么"，不表达数值与条件。 */
enum class BenefitType(val label: String, val wire: String) {
    VOLUNTEER_HOURS("志愿时长", "volunteer_hours"),
    INNOVATION_CREDIT("创新学分", "innovation_credit"),
    COURSE_CREDIT("课程/实践学分", "course_credit"),
    SPORTS_POINTS("体育分", "sports_points"),
    SECOND_CLASSROOM_POINTS("第二课堂积分", "second_classroom_points"),
    RECOMMENDATION_POINTS("推免加分", "recommendation_points"),
    COMPREHENSIVE_POINTS("综测加分", "comprehensive_points"),
    FINANCIAL_AWARD("奖金/奖学金/补助", "financial_award"),
    CERTIFICATE("证书", "certificate"),
    UNKNOWN("收益类型待确认", "unknown"),
    ;

    companion object {
        fun from(raw: String?): BenefitType = when (raw?.trim()?.lowercase()) {
            "volunteer_hours" -> VOLUNTEER_HOURS
            "innovation_credit" -> INNOVATION_CREDIT
            "course_credit" -> COURSE_CREDIT
            "sports_points" -> SPORTS_POINTS
            "second_classroom_points" -> SECOND_CLASSROOM_POINTS
            "recommendation_points" -> RECOMMENDATION_POINTS
            "comprehensive_points" -> COMPREHENSIVE_POINTS
            "financial_award" -> FINANCIAL_AWARD
            "certificate" -> CERTIFICATE
            else -> UNKNOWN
        }
    }
}

/** 科研收益排序档位，仅内部定序，界面不显示分数或档位名。 */
enum class PriorityTier(val wire: String) {
    RECOMMENDATION("recommendation"),
    CREDIT("credit"),
    COMPREHENSIVE("comprehensive"),
    VOLUNTEER("volunteer"),
    NONE("none"),
    ;

    companion object {
        fun from(raw: String?): PriorityTier = when (raw?.trim()?.lowercase()) {
            "recommendation" -> RECOMMENDATION
            "credit" -> CREDIT
            "comprehensive" -> COMPREHENSIVE
            "volunteer" -> VOLUNTEER
            else -> NONE
        }
    }
}

enum class BenefitConfirmation(val wire: String) {
    CONFIRMED("confirmed"),
    PENDING("pending"),
    CONFIRMED_NONE("confirmed_none"),
    ;

    companion object {
        fun from(raw: String?): BenefitConfirmation = when (raw?.trim()?.lowercase()) {
            "confirmed" -> CONFIRMED
            "confirmed_none" -> CONFIRMED_NONE
            else -> PENDING
        }
    }
}

data class Benefit(
    val id: String,
    val type: BenefitType = BenefitType.UNKNOWN,
    val label: String = "",
    val verification: BenefitVerificationState = BenefitVerificationState.PENDING,
    val applicability: Applicability = Applicability.UNKNOWN,
    val evidenceIds: List<String> = emptyList(),
) {
    /** 明确适用且已核实时，才算"对当前用户确认"的收益。 */
    val confirmedForUser: Boolean
        get() = verification == BenefitVerificationState.CONFIRMED &&
            applicability == Applicability.APPLICABLE
}

data class BenefitResult(
    val items: List<Benefit> = emptyList(),
    val priorityTier: PriorityTier = PriorityTier.NONE,
    val confirmation: BenefitConfirmation = BenefitConfirmation.PENDING,
    val policyVersion: String? = null,
)

/** 后端生成的收益标签。PENDING 时界面追加"待确认"。 */
data class BenefitLabel(
    val text: String,
    val verification: BenefitVerificationState = BenefitVerificationState.PENDING,
    val benefitId: String? = null,
)

/** 面向群体标签：只表达对象范围，资格与材料在正文查看。 */
data class AudienceLabel(
    val text: String,
    val groupId: String? = null,
    val evidenceIds: List<String> = emptyList(),
)

/** 文件（原件）状态，独立于个人生命周期。 */
enum class DocumentStatusCode(val label: String, val wire: String) {
    RESULT_PUBLICITY("结果公示", "result_publicity"),
    EVENT_ENDED("事项已结束", "event_ended"),
    POLICY_VALID("政策有效", "policy_valid"),
    POLICY_EXPIRED("政策失效", "policy_expired"),
    UNKNOWN("状态待确认", "unknown"),
    ;

    companion object {
        fun from(raw: String?): DocumentStatusCode = when (raw?.trim()?.lowercase()) {
            "result_publicity" -> RESULT_PUBLICITY
            "event_ended" -> EVENT_ENDED
            "policy_valid" -> POLICY_VALID
            "policy_expired" -> POLICY_EXPIRED
            else -> UNKNOWN
        }
    }
}

data class StatusLabel(
    val code: DocumentStatusCode = DocumentStatusCode.UNKNOWN,
    val text: String = "",
    val evidenceIds: List<String> = emptyList(),
)

/** 时间窗口用途。 */
enum class WindowKind(val label: String, val wire: String) {
    REGISTRATION("报名", "registration"),
    APPLICATION("申请", "application"),
    SUBMISSION("提交", "submission"),
    EVENT("活动", "event"),
    APPEAL("异议/申诉", "appeal"),
    POLICY_VALIDITY("有效期", "policy_validity"),
    OTHER("其他", "other"),
    ;

    companion object {
        fun from(raw: String?): WindowKind = when (raw?.trim()?.lowercase()) {
            "registration" -> REGISTRATION
            "application" -> APPLICATION
            "submission" -> SUBMISSION
            "event" -> EVENT
            "appeal" -> APPEAL
            "policy_validity" -> POLICY_VALIDITY
            else -> OTHER
        }
    }
}

/**
 * 单个已评估时间窗口（契约第五节 EvaluatedTimeWindow 的展示子集）。
 * [verified] 为 false 时界面显示"时间待确认"及原因。
 * [start]/[end] 是后端给出的原值字符串（日期或带时区时刻），由格式化工具展示。
 */
data class TimeWindowRow(
    val id: String,
    val kind: WindowKind = WindowKind.OTHER,
    val label: String = "",
    val start: String? = null,
    val end: String? = null,
    val explicitLongTerm: Boolean = false,
    val studentAction: Boolean = true,
    val audienceText: String? = null,
    val verified: Boolean = true,
    val rawText: String? = null,
    val note: String? = null,
    val state: WindowState = WindowState.UNKNOWN,
    val applicability: Applicability = Applicability.UNKNOWN,
) {
    val kindText: String get() = label.ifBlank { kind.label }
}

/** 正文取得程度。四种状态必须分开，不能统一显示成"加载失败"。 */
enum class BodyStatus(val label: String) {
    FULL("正文完整"),
    PARTIAL("正文部分取得"),
    TITLE_ONLY("仅取得标题"),
    UNAVAILABLE("正文暂未取得"),
    UNKNOWN("正文状态待确认"),
    ;

    companion object {
        fun from(raw: String?): BodyStatus = when (raw?.trim()?.lowercase()) {
            "full" -> FULL
            "partial" -> PARTIAL
            "title_only" -> TITLE_ONLY
            "unavailable" -> UNAVAILABLE
            else -> UNKNOWN
        }
    }
}

/** 正文未取得的真实原因。公开正文受限不等于 App 账号失效。 */
enum class AccessReason(val text: String) {
    LOGIN_REQUIRED("需要登录校园账号后查看"),
    PERMISSION_DENIED("该正文公开范围受限"),
    FETCH_FAILED("暂时读取失败，可稍后重试"),
    PROCESSING("正文处理中，稍后重试"),
    NONE(""),
    UNKNOWN("正文暂未取得"),
    ;

    companion object {
        fun from(raw: String?): AccessReason = when (raw?.trim()?.lowercase()) {
            "login_required" -> LOGIN_REQUIRED
            "permission_denied" -> PERMISSION_DENIED
            "fetch_failed" -> FETCH_FAILED
            "processing" -> PROCESSING
            null, "" -> NONE
            else -> UNKNOWN
        }
    }
}

/** 个人生命周期。首页隐藏不等于删除，也不等于关注消失。 */
enum class LifecycleState(val label: String) {
    ACTIVE("进行中"),
    EXPIRED("已过期"),
    ENDED("已结束"),
    REVOKED("已撤销"),
    UNKNOWN("状态待确认"),
    ;

    companion object {
        fun from(raw: String?): LifecycleState = when (raw?.trim()?.lowercase()) {
            "active" -> ACTIVE
            "expired" -> EXPIRED
            "ended" -> ENDED
            "revoked" -> REVOKED
            else -> UNKNOWN
        }
    }
}

data class Lifecycle(
    val homeVisible: Boolean = true,
    val state: LifecycleState = LifecycleState.UNKNOWN,
    val reason: String? = null,
)

/** 关注状态。version 为 64 位，用于跨来源合并：低版本不得覆盖已知高版本。 */
data class FollowState(
    val noticeId: String = "",
    val starred: Boolean = false,
    val followedAt: String? = null,
    val version: Long = 0L,
)

/** 该条数据所依据的公共版本与个人版本。 */
data class EvaluationContext(
    val contractVersion: String? = null,
    val profileVersion: Long? = null,
    val preferencesVersion: Long? = null,
    val policyVersion: String? = null,
    val rulesVersion: String? = null,
    val factsVersion: String? = null,
)

/** 列表项（首页与我的关注共用）。 */
data class NoticeItem(
    val noticeId: String,
    val title: String,
    val sourceName: String? = null,
    val category: Category = Category.UNKNOWN,
    val categoryPending: Boolean = false,
    val publishedAt: String? = null,
    val timeWindows: List<TimeWindowRow> = emptyList(),
    val dateLabels: List<DateLabel> = emptyList(),
    val benefits: BenefitResult = BenefitResult(),
    val benefitLabels: List<BenefitLabel> = emptyList(),
    val audienceLabels: List<AudienceLabel> = emptyList(),
    val statusLabels: List<StatusLabel> = emptyList(),
    val match: MatchInfo = MatchInfo(),
    val lifecycle: Lifecycle = Lifecycle(),
    val follow: FollowState = FollowState(),
    val contentVersion: String? = null,
    val latestVersion: String? = null,
    val evaluationContext: EvaluationContext = EvaluationContext(),
    val bodyStatus: BodyStatus = BodyStatus.UNKNOWN,
    val accessReason: AccessReason = AccessReason.NONE,
    val processing: Boolean = false,
    val uncertainties: List<String> = emptyList(),
) {
    /** 展示依据落后于已取得的最新原件时提示"有更新"。 */
    val hasUpdate: Boolean
        get() = contentVersion != null && latestVersion != null && contentVersion != latestVersion

    val hasPendingBenefit: Boolean
        get() = benefitLabels.any { it.verification == BenefitVerificationState.PENDING }

    val bodyIncomplete: Boolean
        get() = bodyStatus == BodyStatus.TITLE_ONLY || bodyStatus == BodyStatus.UNAVAILABLE

    /** 按分组排序后的日期标签（组内保持后端顺序）。 */
    fun dateLabelsByGroup(): List<Pair<DateGroup, List<DateLabel>>> =
        DateGroup.ordered.mapNotNull { group ->
            val labels = dateLabels.filter { it.group == group }
            if (labels.isEmpty()) null else group to labels
        }

    /** 该条是否已从默认首页隐藏（关注页仍保留）。 */
    val hiddenFromHome: Boolean get() = !lifecycle.homeVisible
}

/** 一类通知的一页结果；首页和关注页共用同一结构。 */
data class NoticePage(
    val items: List<NoticeItem> = emptyList(),
    val total: Int = 0,
    val offset: Int = 0,
    val limit: Int = 0,
    val profileVersion: Long? = null,
    val preferencesVersion: Long? = null,
    val policyVersion: String? = null,
    val rulesVersion: String? = null,
    val rankingStrategyVersion: String? = null,
    val evaluatedAt: String? = null,
    val lastUpdatedAt: String? = null,
    val queryFingerprint: String? = null,
    val listRevision: String? = null,
    val coverageUrl: String? = null,
    val contractVersion: String? = null,
)

/** 政策依据。首版详情必须能独立显示，不依赖任何 AI 解读。 */
data class PolicyRef(
    val policyId: String? = null,
    val title: String = "",
    val version: String? = null,
    val applicabilityText: String? = null,
    val validityText: String? = null,
    val sourceUrl: String? = null,
    val evidenceIds: List<String> = emptyList(),
)

/** 附件状态。附件失败不覆盖已取得正文。 */
enum class AttachmentStatus(val label: String, val wire: String) {
    AVAILABLE("可打开", "available"),
    RESTRICTED("受限", "restricted"),
    FAILED("读取失败", "failed"),
    PENDING("处理中", "pending"),
    UNKNOWN("状态待确认", "unknown"),
    ;

    companion object {
        fun from(raw: String?): AttachmentStatus = when (raw?.trim()?.lowercase()) {
            "available" -> AVAILABLE
            "restricted" -> RESTRICTED
            "failed" -> FAILED
            "pending" -> PENDING
            else -> UNKNOWN
        }
    }
}

data class AttachmentInfo(
    val id: String? = null,
    val name: String,
    val url: String? = null,
    val mediaType: String? = null,
    val status: AttachmentStatus = AttachmentStatus.UNKNOWN,
    val reason: String? = null,
)

data class NoticeSource(
    val id: String? = null,
    val name: String,
    val description: String? = null,
    val url: String? = null,
)

/** 正文分段（纯文本）。首版不解析 HTML。 */
data class BodySegment(
    val id: String,
    val text: String,
    val page: Int? = null,
)

/** 证据引用子集，供详情展示与契约测试使用。 */
data class EvidenceRef(
    val evidenceId: String,
    val sourceKind: String? = null,
    val sourceId: String? = null,
    val sourceUrl: String? = null,
    val quote: String = "",
    val page: Int? = null,
    val clause: String? = null,
)

/** 通知详情：列表项字段 + 正文 + 附件 + 来源 + 政策依据 + 证据。 */
data class NoticeDetail(
    val item: NoticeItem,
    val body: String? = null,
    val segments: List<BodySegment> = emptyList(),
    val sourceUrl: String? = null,
    val sources: List<NoticeSource> = emptyList(),
    val attachments: List<AttachmentInfo> = emptyList(),
    val policyReferences: List<PolicyRef> = emptyList(),
    val evidenceRefs: List<EvidenceRef> = emptyList(),
) {
    /** 展示正文落后于已取得最新原件。 */
    val staleBody: Boolean get() = item.hasUpdate

    val sourceDescription: String?
        get() = sources.firstOrNull { !it.description.isNullOrBlank() }?.description
}

data class CatalogNode(val id: String, val name: String)

/** 目录响应：条目可能为空，[message] 由后端说明原因（例如课程目录待核验）。 */
data class CatalogPage(
    val items: List<CatalogNode> = emptyList(),
    val message: String? = null,
)

/** 年级目录：value 是 1—8 的整数，不是字符串。 */
data class GradeOption(val value: Int, val label: String)

/**
 * 资料读取结果，对应契约 ProfileResponse `{completed, profile, version}`。
 * completed 表示"身份资料已保存"，不等于所有政策资格已核验。
 */
data class ProfileResponse(
    val completed: Boolean = false,
    val profile: Profile? = null,
    val version: Long = 0L,
)

/**
 * 资料保存草稿：全量提交的字段 + 读取到的权威版本。
 *
 * 入学年份是三态：省略（保留服务端原值）、显式 null（用户清空）、整数（设置）。
 * [admissionYearSpecified] 区分前两者。
 */
data class ProfileEdit(
    val schoolId: String,
    val collegeId: String,
    val majorId: String,
    val grade: Int,
    val admissionYear: Int? = null,
    val admissionYearSpecified: Boolean = false,
    /** 只允许 "undergraduate" 或省略（null 表示不提交该字段；显式 null 会被后端拒绝）。 */
    val educationStage: String? = null,
    val expectedVersion: Long = 0L,
)

data class Profile(
    val schoolId: String? = null,
    val schoolName: String? = null,
    val collegeId: String? = null,
    val collegeName: String? = null,
    val majorId: String? = null,
    val majorName: String? = null,
    val grade: Int? = null,
    /** 可选入学年份，不填仍可使用。范围 1900—2100，由后端校验。 */
    val admissionYear: Int? = null,
    /** "undergraduate" 或 null。 */
    val educationStage: String? = null,
    /** 学校当届招生/分流大类，由后端映射；可能为 null，前端不得自行推断。 */
    val majorGroupId: String? = null,
    val majorGroupName: String? = null,
    val version: Long = 0L,
) {
    val isUndergraduate: Boolean get() = educationStage == "undergraduate"
}

/** 偏好：四组自述标签 + 独立版本。 */
data class Preferences(
    val courseIds: List<String> = emptyList(),
    val skillIds: List<String> = emptyList(),
    val goalIds: List<String> = emptyList(),
    val interestIds: List<String> = emptyList(),
    val version: Long = 0L,
)

/** 与服务端唯一维护的偏好目录种类对应。 */
enum class PreferenceKind(val wire: String, val label: String) {
    COURSE("course", "课程"),
    SKILL("skill", "技能"),
    GOAL("goal", "目标"),
    INTEREST("interest", "兴趣"),
    ;

    companion object {
        fun from(raw: String?): PreferenceKind? =
            entries.firstOrNull { it.wire == raw?.trim()?.lowercase() }
    }
}
