package campus.app.core.network

import campus.app.core.model.AccessReason
import campus.app.core.model.Applicability
import campus.app.core.model.AttachmentInfo
import campus.app.core.model.AttachmentStatus
import campus.app.core.model.AudienceLabel
import campus.app.core.model.Benefit
import campus.app.core.model.BenefitConfirmation
import campus.app.core.model.BenefitLabel
import campus.app.core.model.BenefitResult
import campus.app.core.model.BenefitType
import campus.app.core.model.BenefitVerificationState
import campus.app.core.model.BodySegment
import campus.app.core.model.BodyStatus
import campus.app.core.model.CatalogNode
import campus.app.core.model.CatalogPage
import campus.app.core.model.Category
import campus.app.core.model.DateGroup
import campus.app.core.model.DateLabel
import campus.app.core.model.DocumentStatusCode
import campus.app.core.model.EligibilityState
import campus.app.core.model.EvaluationContext
import campus.app.core.model.EvidenceRef
import campus.app.core.model.FollowState
import campus.app.core.model.GradeOption
import campus.app.core.model.Lifecycle
import campus.app.core.model.LifecycleState
import campus.app.core.model.MatchInfo
import campus.app.core.model.MatchState
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticeItem
import campus.app.core.model.NoticePage
import campus.app.core.model.NoticeSource
import campus.app.core.model.PolicyRef
import campus.app.core.model.PreferenceKind
import campus.app.core.model.Preferences
import campus.app.core.model.PriorityTier
import campus.app.core.model.Profile
import campus.app.core.model.ProfileResponse
import campus.app.core.model.StatusLabel
import campus.app.core.model.TimeWindowRow
import campus.app.core.model.WindowKind
import campus.app.core.model.WindowState
import campus.app.core.session.SessionView
import kotlinx.serialization.json.JsonObject

/**
 * JSON → 模型（契约 undergrad-app/2）。
 *
 * 两条不许退让的规则：
 * - 未知值落到 UNKNOWN / null，不用 0 或空串冒充；
 * - 字段缺失时保持为空，不伪造内容（例如没有 date_labels 就不编一个截止日期）。
 */
object Mappers {

    /** SessionView：{user:{id,email}, expires_at(Unix 秒), csrf_token}。 */
    fun session(o: JsonObject): SessionView? {
        val user = o.obj("user") ?: o
        val userId = user.str("id") ?: return null
        return SessionView(
            userId = userId,
            email = user.str("email").orEmpty(),
            expiresAtEpochSeconds = o.long("expires_at") ?: return null,
            csrfToken = o.str("csrf_token").orEmpty(),
        )
    }

    /** 目录响应：{items:[{id,name,...}], message:string|null}。 */
    fun catalogPage(o: JsonObject): CatalogPage = CatalogPage(
        items = o.items().mapNotNull { node(it) },
        message = o.str("message"),
    )

    private fun node(o: JsonObject): CatalogNode? {
        val id = o.str("id") ?: return null
        return CatalogNode(id = id, name = o.str("name") ?: id, hint = o.str("hint"))
    }

    /** 年级目录：value 是 1—8 的整数。 */
    fun grades(o: JsonObject): List<GradeOption> =
        o.items().mapNotNull { item ->
            val value = item.int("value") ?: return@mapNotNull null
            GradeOption(value = value, label = item.str("label") ?: "${value}年级")
        }

    /** ProfileResponse：{completed, profile:ProfileView|null, version}。 */
    fun profileResponse(o: JsonObject): ProfileResponse {
        val completed = o.bool("completed") ?: false
        val version = o.long("version") ?: 0L
        val profile = o.obj("profile")?.let { profile(it) }
        return ProfileResponse(completed = completed, profile = profile, version = version)
    }

    private fun profile(o: JsonObject): Profile = Profile(
        schoolId = o.str("school_id"),
        schoolName = o.str("school_name"),
        collegeId = o.str("college_id"),
        collegeName = o.str("college_name"),
        majorId = o.str("major_id"),
        majorName = o.str("major_name"),
        grade = o.int("grade"),
        admissionYear = o.int("admission_year"),
        educationStage = o.str("education_stage"),
        majorGroupId = o.obj("major_group")?.str("id"),
        majorGroupName = o.obj("major_group")?.str("name"),
        version = o.long("version") ?: 0L,
    )

    /** PreferencesView：四组 ID 数组 + 独立 64 位版本。 */
    fun preferences(o: JsonObject): Preferences = Preferences(
        courseIds = o.strList("course_ids"),
        skillIds = o.strList("skill_ids"),
        goalIds = o.strList("goal_ids"),
        interestIds = o.strList("interest_ids"),
        version = o.long("version") ?: 0L,
    )

    /** 关注状态：{notice_id, starred, followed_at|null, version}。 */
    fun follow(o: JsonObject?, fallbackNoticeId: String = ""): FollowState {
        if (o == null) return FollowState(noticeId = fallbackNoticeId)
        return FollowState(
            noticeId = o.str("notice_id") ?: fallbackNoticeId,
            starred = o.bool("starred") ?: false,
            followedAt = o.str("followed_at"),
            version = o.long("version") ?: 0L,
        )
    }

    /** date_labels: [{window_id,group,text,state}]，文本原样保留。 */
    fun dateLabels(o: JsonObject): List<DateLabel> =
        o.objList("date_labels").mapNotNull { node ->
            val text = node.str("text") ?: return@mapNotNull null
            DateLabel(
                text = text,
                state = WindowState.from(node.str("state")),
                windowId = node.str("window_id"),
                group = DateGroup.from(node.str("group")),
            )
        }

    /** benefit_labels: [{benefit_id,text,verification}]。 */
    fun benefitLabels(o: JsonObject): List<BenefitLabel> =
        o.objList("benefit_labels").mapNotNull { node ->
            val text = node.str("text") ?: return@mapNotNull null
            BenefitLabel(
                text = text,
                verification = BenefitVerificationState.from(node.str("verification")),
                benefitId = node.str("benefit_id"),
            )
        }

    /** audience_labels: [{group_id,text,evidence_ids}]。 */
    fun audienceLabels(o: JsonObject): List<AudienceLabel> =
        o.objList("audience_labels").mapNotNull { node ->
            val text = node.str("text") ?: return@mapNotNull null
            AudienceLabel(
                text = text,
                groupId = node.str("group_id"),
                evidenceIds = node.strList("evidence_ids"),
            )
        }

    /** status_labels: [{code,text,evidence_ids}]。 */
    fun statusLabels(o: JsonObject): List<StatusLabel> =
        o.objList("status_labels").mapNotNull { node ->
            val text = node.str("text") ?: return@mapNotNull null
            StatusLabel(
                code = DocumentStatusCode.from(node.str("code")),
                text = text,
                evidenceIds = node.strList("evidence_ids"),
            )
        }

    /** benefits: BenefitResult{items,priority_tier,confirmation,policy_version}。 */
    fun benefits(o: JsonObject): BenefitResult {
        val node = o.obj("benefits") ?: return BenefitResult()
        return BenefitResult(
            items = node.objList("items").mapNotNull { item ->
                val id = item.str("id") ?: return@mapNotNull null
                Benefit(
                    id = id,
                    type = BenefitType.from(item.str("type")),
                    label = item.str("label").orEmpty(),
                    verification = BenefitVerificationState.from(item.str("verification")),
                    applicability = Applicability.from(item.str("applicability")),
                    evidenceIds = item.strList("evidence_ids"),
                )
            },
            priorityTier = PriorityTier.from(node.str("priority_tier")),
            confirmation = BenefitConfirmation.from(node.str("confirmation")),
            policyVersion = node.str("policy_version"),
        )
    }

    /** time_windows: EvaluatedTimeWindow 数组。 */
    fun timeWindows(o: JsonObject): List<TimeWindowRow> =
        o.objList("time_windows").mapNotNull { node ->
            val id = node.str("id") ?: return@mapNotNull null
            TimeWindowRow(
                id = id,
                kind = WindowKind.from(node.str("kind")),
                label = node.str("label").orEmpty(),
                start = temporal(node.raw("start")),
                end = temporal(node.raw("end")),
                explicitLongTerm = node.bool("explicit_long_term") ?: false,
                studentAction = node.bool("student_action") ?: true,
                audienceText = node.str("audience_text"),
                verified = node.str("verification")?.lowercase() != "uncertain",
                rawText = node.str("raw_text"),
                note = node.str("uncertainty_reason"),
                state = WindowState.from(node.str("state")),
                applicability = Applicability.from(node.str("applicability")),
            )
        }

    /** TemporalValue 既可能是 {value,precision}，也可能直接是字符串。 */
    private fun temporal(element: kotlinx.serialization.json.JsonElement?): String? {
        if (element == null) return null
        val asObject = runCatching { element as JsonObject }.getOrNull() ?: return null
        return asObject.str("value")
    }

    fun match(o: JsonObject?): MatchInfo {
        if (o == null) return MatchInfo()
        return MatchInfo(
            state = MatchState.from(o.str("state")),
            reasons = o.strList("reasons"),
            eligibility = EligibilityState.from(o.str("eligibility")),
            evaluatedProfileVersion = o.long("evaluated_profile_version"),
        )
    }

    fun lifecycle(o: JsonObject?): Lifecycle {
        if (o == null) return Lifecycle()
        return Lifecycle(
            homeVisible = o.bool("home_visible") ?: true,
            state = LifecycleState.from(o.str("state")),
            reason = o.str("reason"),
        )
    }

    fun evaluationContext(o: JsonObject?): EvaluationContext {
        if (o == null) return EvaluationContext()
        return EvaluationContext(
            contractVersion = o.str("contract_version"),
            profileVersion = o.long("profile_version"),
            preferencesVersion = o.long("preferences_version"),
            policyVersion = o.str("policy_version"),
            rulesVersion = o.str("rules_version"),
            factsVersion = o.str("facts_version"),
        )
    }

    /** 列表项 / 详情共用的通知字段。 */
    fun noticeItem(o: JsonObject): NoticeItem? {
        val id = o.str("notice_id") ?: o.str("id") ?: return null
        val category = Category.from(o.str("category"))
        return NoticeItem(
            noticeId = id,
            title = o.str("title").orEmpty().ifBlank { "（无标题）" },
            sourceName = o.str("source_name"),
            category = category,
            categoryPending = o.bool("category_pending") ?: (category == Category.UNKNOWN),
            publishedAt = o.str("published_at"),
            timeWindows = timeWindows(o),
            dateLabels = dateLabels(o),
            benefits = benefits(o),
            benefitLabels = benefitLabels(o),
            audienceLabels = audienceLabels(o),
            statusLabels = statusLabels(o),
            match = match(o.obj("match")),
            lifecycle = lifecycle(o.obj("lifecycle")),
            follow = follow(o.obj("follow"), id),
            contentVersion = o.str("content_version"),
            latestVersion = o.str("latest_version"),
            evaluationContext = evaluationContext(o.obj("evaluation_context")),
            bodyStatus = BodyStatus.from(o.str("body_status")),
            accessReason = AccessReason.from(o.str("access_reason")),
            processing = o.bool("processing") ?: false,
            uncertainties = o.strList("uncertainties"),
        )
    }

    /** FeedPage / FollowPage 共用结构。 */
    fun noticePage(o: JsonObject): NoticePage = NoticePage(
        items = o.items().mapNotNull { noticeItem(it) },
        total = o.int("total") ?: 0,
        offset = o.int("offset") ?: 0,
        limit = o.int("limit") ?: 0,
        profileVersion = o.long("profile_version"),
        preferencesVersion = o.long("preferences_version"),
        policyVersion = o.str("policy_version"),
        rulesVersion = o.str("rules_version"),
        rankingStrategyVersion = o.str("ranking_strategy_version"),
        evaluatedAt = o.str("evaluated_at"),
        lastUpdatedAt = o.str("last_updated_at"),
        queryFingerprint = o.str("query_fingerprint"),
        listRevision = o.str("list_revision"),
        coverageUrl = o.str("coverage_url"),
        contractVersion = o.str("contract_version"),
    )

    /** 详情：列表项字段在顶层，另加正文/来源/附件/政策/证据。 */
    fun detail(o: JsonObject): NoticeDetail? {
        val item = noticeItem(o) ?: return null
        return NoticeDetail(
            item = item,
            body = o.str("body"),
            segments = o.objList("segments").mapNotNull { node ->
                val id = node.str("id") ?: return@mapNotNull null
                BodySegment(id = id, text = node.str("text").orEmpty(), page = node.int("page"))
            },
            sourceUrl = o.str("source_url"),
            sources = o.objList("sources").mapNotNull { node ->
                val name = node.str("name") ?: return@mapNotNull null
                NoticeSource(
                    id = node.str("id"),
                    name = name,
                    description = node.str("description"),
                    url = node.str("url"),
                )
            },
            attachments = o.objList("attachments").mapNotNull { node ->
                val name = node.str("name") ?: return@mapNotNull null
                AttachmentInfo(
                    id = node.str("id"),
                    name = name,
                    url = node.str("url"),
                    mediaType = node.str("media_type"),
                    status = AttachmentStatus.from(node.str("status")),
                    reason = node.str("reason"),
                )
            },
            policyReferences = o.objList("policy_references").mapNotNull { node ->
                val title = node.str("title") ?: return@mapNotNull null
                PolicyRef(
                    policyId = node.str("policy_id"),
                    title = title,
                    version = node.str("version"),
                    applicabilityText = node.str("applicability_text"),
                    validityText = node.str("validity_text"),
                    sourceUrl = node.str("source_url"),
                    evidenceIds = node.strList("evidence_ids"),
                )
            },
            evidenceRefs = o.objList("evidence_refs").mapNotNull { node ->
                val id = node.str("evidence_id") ?: return@mapNotNull null
                val locator = node.obj("locator")
                EvidenceRef(
                    evidenceId = id,
                    sourceKind = node.str("source_kind"),
                    sourceId = node.str("source_id"),
                    sourceUrl = node.str("source_url"),
                    quote = node.str("quote").orEmpty(),
                    page = locator?.int("page"),
                    clause = locator?.str("clause"),
                )
            },
        )
    }

    /**
     * 解析 {"error":{"code","message","request_id","details"}}。
     * [fields] 是 details 中的 field 列表，用于 422 提示具体字段。
     */
    fun errorEnvelope(o: JsonObject): ErrorBody {
        val e = o.obj("error") ?: o
        return ErrorBody(
            code = e.str("code"),
            message = e.str("message"),
            requestId = e.str("request_id"),
            fields = e.objList("details").mapNotNull { it.str("field") },
        )
    }

    data class ErrorBody(
        val code: String?,
        val message: String?,
        val requestId: String?,
        val fields: List<String>,
    )

    /** 偏好目录请求的 kind 参数取值。 */
    fun preferenceKind(kind: PreferenceKind): String = kind.wire

    // ------------------------------------------------------------ 真实后端（v1）读模型
    // 后端返回的是「分类 + 重要度 + 截止时间 + 附件」这套字段，没有 date_labels。
    // 这里只挑界面要用到的部分，其余不假装有值。

    /** 后端八个分类归到界面的三档；奖助与科研保持原义，其余都算日常。 */
    fun appCategory(o: JsonObject): Category = when (o.str("category")) {
        "financial_aid" -> Category.FINANCIAL_AID
        "research_innovation" -> Category.RESEARCH_INNOVATION
        null -> Category.UNKNOWN
        else -> Category.DAILY
    }

    /** 2026-03-04 → 03/04；无法识别就原样返回。 */
    private fun shortDate(raw: String): String =
        raw.takeIf { it.length >= 10 && it[4] == '-' && it[7] == '-' }?.substring(5)?.replace('-', '/') ?: raw

    fun appItem(o: JsonObject): NoticeItem? {
        val id = o.str("notice_id") ?: return null
        val deadline = o.str("deadline")?.takeIf { it.isNotBlank() }
        val published = o.str("published_at")?.takeIf { it.isNotBlank() }
        return NoticeItem(
            noticeId = id,
            title = o.str("title").orEmpty().ifBlank { "（无标题）" },
            sourceName = o.str("source"),
            category = appCategory(o),
            publishedAt = o.str("published_at"),
            // 卡片只显示一行时间：有截止就显示截止，否则退回发布时间。
            dateLabels = when {
                deadline != null -> listOf(DateLabel(text = "截止 " + shortDate(deadline)))
                published != null -> listOf(DateLabel(text = "发布 " + shortDate(published)))
                else -> emptyList()
            },
            follow = follow(o.obj("follow"), id),
            contentVersion = o.str("content_version"),
            latestVersion = o.str("latest_version"),
            bodyStatus = BodyStatus.from(o.str("body_status")),
            accessReason = AccessReason.from(o.str("access_reason")),
            processing = o.bool("processing") ?: false,
            uncertainties = o.strList("uncertainties"),
        )
    }

    fun appPage(o: JsonObject): NoticePage = NoticePage(
        items = o.items().mapNotNull { appItem(it) },
        total = o.int("total") ?: 0,
        offset = o.int("offset") ?: 0,
        limit = o.int("limit") ?: 0,
        evaluatedAt = o.str("evaluated_at"),
        lastUpdatedAt = o.str("last_updated_at"),
    )

    fun appDetail(o: JsonObject): NoticeDetail? {
        // 详情页已经有"发布于 …"，时间行只在有明确截止时出现，避免重复。
        val deadline = o.str("deadline")?.takeIf { it.isNotBlank() }
        val item = appItem(o)?.copy(
            dateLabels = deadline?.let { listOf(DateLabel(text = "截止 " + shortDate(it))) } ?: emptyList(),
        ) ?: return null
        return NoticeDetail(
            item = item,
            body = o.str("content")?.takeIf { it.isNotBlank() },
            sourceUrl = o.str("source_url"),
            sources = o.objList("sources").mapNotNull { source ->
                val name = source.str("name") ?: return@mapNotNull null
                NoticeSource(id = source.str("source_id"), name = name, url = source.str("url"))
            },
            attachments = o.objList("assets")
                .filter { it.str("role") != "original_html" }
                .mapNotNull { asset ->
                    val name = asset.str("filename") ?: return@mapNotNull null
                    AttachmentInfo(
                        name = name,
                        url = asset.str("url"),
                        mediaType = asset.str("media_type"),
                        status = AttachmentStatus.from(asset.str("status")),
                    )
                },
        )
    }
}
