package campus.app.core.data

import android.content.Context
import campus.app.core.model.Category
import campus.app.core.model.CatalogPage
import campus.app.core.model.FollowState
import campus.app.core.model.GradeOption
import campus.app.core.model.NoticeDetail
import campus.app.core.model.NoticeItem
import campus.app.core.model.NoticePage
import campus.app.core.model.PreferenceKind
import campus.app.core.model.Preferences
import campus.app.core.model.Profile
import campus.app.core.model.ProfileEdit
import campus.app.core.model.ProfileResponse
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.network.JsonKit
import campus.app.core.network.Mappers
import campus.app.core.network.obj
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.IOException
import java.time.OffsetDateTime
import java.util.UUID

private fun emptyObject(): JsonObject = JsonObject(emptyMap<String, JsonElement>())

/**
 * 样例场景（Env = MOCK）。
 *
 * 数据来自 `assets/mock/scenario.json`，与后端共同契约 `undergrad-app/2` 同形，
 * 但全是合成内容（虚构来源、example.org 链接），界面会持续显示"样例数据"标记。
 *
 * 关注状态保存在内存里：MOCK 下不联网、不写服务端，仅用于把交互流程走通。
 */
class MockScenario private constructor(
    private val root: JsonObject,
) {

    val profileResponse: ProfileResponse =
        Mappers.profileResponse(root.obj("profile") ?: emptyObject())

    var preferences: Preferences = Mappers.preferences(root.obj("preferences") ?: emptyObject())
        private set

    private var profileValue: ProfileResponse = profileResponse

    private val catalogNode: JsonObject = root.obj("catalog") ?: emptyObject()

    private val schoolsPage: CatalogPage =
        Mappers.catalogPage(catalogNode.obj("schools") ?: emptyObject())
    private val collegesRoot: JsonObject = catalogNode.obj("colleges") ?: emptyObject()
    private val majorsRoot: JsonObject = catalogNode.obj("majors") ?: emptyObject()
    private val gradesPage: List<GradeOption> =
        Mappers.grades(catalogNode.obj("grades") ?: emptyObject())
    private val preferenceRoot: JsonObject =
        catalogNode.obj("preference_options") ?: emptyObject()

    private val feeds: Map<String, JsonObject> =
        (root.obj("feed") ?: emptyObject()).let { feed ->
            Category.tabs.associate { category ->
                category.wire to (feed.obj(category.wire) ?: emptyObject())
            }
        }

    private val detailsRoot: Map<String, JsonObject> =
        (root.obj("details") ?: emptyObject()).let { details ->
            details.keys.associateWith { key -> details.obj(key) ?: emptyObject() }
        }

    private val followsPageJson: JsonObject = root.obj("follows") ?: emptyObject()

    /** 关注状态（内存）：初始值取自样例详情里的 follow 字段。 */
    private val followStates: MutableMap<String, FollowState> = mutableMapOf()

    init {
        detailsRoot.forEach { (id, json) ->
            val followJson = json.obj("follow") ?: return@forEach
            val state = Mappers.follow(followJson, id)
            if (state.starred || state.version > 0) followStates[id] = state
        }
    }

    // ------------------------------------------------------------ 目录与资料

    fun schools(prefix: String?): ApiResult<CatalogPage> {
        val page = if (prefix.isNullOrBlank()) {
            schoolsPage
        } else {
            schoolsPage.copy(items = schoolsPage.items.filter { it.name.contains(prefix) })
        }
        return ApiResult.Success(page)
    }

    fun colleges(schoolId: String): ApiResult<CatalogPage> {
        val json = collegesRoot.obj(schoolId)
            ?: return ApiResult.Success(CatalogPage(message = "暂未支持该学校的学院目录"))
        return ApiResult.Success(Mappers.catalogPage(json))
    }

    fun majors(schoolId: String, collegeId: String): ApiResult<CatalogPage> {
        val json = majorsRoot.obj("$schoolId|$collegeId")
            ?: return ApiResult.Success(CatalogPage(message = "暂未支持该组合的专业目录"))
        return ApiResult.Success(Mappers.catalogPage(json))
    }

    fun grades(): ApiResult<List<GradeOption>> = ApiResult.Success(gradesPage)

    fun preferenceOptions(kind: PreferenceKind): ApiResult<CatalogPage> {
        val json = preferenceRoot.obj(kind.wire)
            ?: return ApiResult.Success(CatalogPage(message = "目录待核验，可跳过"))
        return ApiResult.Success(Mappers.catalogPage(json))
    }

    fun loadProfile(): ApiResult<ProfileResponse> = ApiResult.Success(profileValue)

    /** 演示用：模拟"刚注册、还没填过资料"的新账号。 */
    fun startAsNewUser() {
        profileValue = ProfileResponse(completed = false, profile = null, version = 0)
        preferences = Preferences()
    }

    fun saveProfile(edit: ProfileEdit): ApiResult<ProfileResponse> {
        if (edit.expectedVersion != profileValue.version) {
            return ApiResult.Failure(ApiError.VersionConflict)
        }
        val existing = profileValue.profile
        val names = namesFor(edit.schoolId, edit.collegeId, edit.majorId)
        val nextProfile = Profile(
            schoolId = edit.schoolId,
            schoolName = names.schoolName ?: edit.schoolId,
            collegeId = edit.collegeId,
            collegeName = names.collegeName ?: edit.collegeId,
            majorId = edit.majorId,
            majorName = names.majorName ?: edit.majorId,
            grade = edit.grade,
            admissionYear = if (edit.admissionYearSpecified) edit.admissionYear else existing?.admissionYear,
            educationStage = edit.educationStage ?: existing?.educationStage,
            majorGroupId = existing?.majorGroupId,
            majorGroupName = existing?.majorGroupName,
            version = profileValue.version + 1,
        )
        profileValue = ProfileResponse(completed = true, profile = nextProfile, version = nextProfile.version)
        return ApiResult.Success(profileValue)
    }

    private data class Names(val schoolName: String?, val collegeName: String?, val majorName: String?)

    private fun namesFor(schoolId: String, collegeId: String, majorId: String): Names {
        val schoolName = schoolsPage.items.firstOrNull { it.id == schoolId }?.name
        val collegeName = colleges(schoolId).let { result ->
            (result as? ApiResult.Success)?.value?.items?.firstOrNull { it.id == collegeId }?.name
        }
        val majorName = majors(schoolId, collegeId).let { result ->
            (result as? ApiResult.Success)?.value?.items?.firstOrNull { it.id == majorId }?.name
        }
        return Names(schoolName, collegeName, majorName)
    }

    fun loadPreferences(): ApiResult<Preferences> = ApiResult.Success(preferences)

    fun savePreferences(next: Preferences): ApiResult<Preferences> {
        if (next.version != preferences.version) {
            return ApiResult.Failure(ApiError.VersionConflict)
        }
        preferences = next.copy(version = preferences.version + 1)
        return ApiResult.Success(preferences)
    }

    // ------------------------------------------------------------ 通知

    fun feed(category: Category): ApiResult<NoticePage> {
        val raw = feeds[category.wire] ?: return ApiResult.Success(NoticePage())
        val page = Mappers.noticePage(raw)
        return ApiResult.Success(page.copy(items = page.items.map { withFollow(it) }))
    }

    fun detail(noticeId: String): ApiResult<NoticeDetail> {
        val raw = detailsRoot[noticeId]
            ?: return ApiResult.Failure(ApiError.NoticeNotFound)
        val detail = Mappers.detail(raw)
            ?: return ApiResult.Failure(ApiError.Unknown("bad_detail", "样例详情结构不完整", null))
        return ApiResult.Success(
            detail.copy(item = withFollow(detail.item)),
        )
    }

    fun follows(): ApiResult<NoticePage> {
        val all = detailsRoot.keys.mapNotNull { id ->
            detailsRoot[id]?.let { Mappers.detail(it) }?.item?.let { withFollow(it) }
        }.filter { it.follow.starred }
            // 契约：按 followed_at 倒序、notice_id 升序；未知时间排最后。
            .sortedWith(
                compareByDescending<NoticeItem> { it.follow.followedAt ?: "" }
                    .thenBy { it.noticeId },
            )
        val base = Mappers.noticePage(followsPageJson)
        return ApiResult.Success(
            base.copy(items = all, total = all.size, offset = 0, limit = 20),
        )
    }

    fun setFollow(noticeId: String, starred: Boolean, expectedVersion: Long): ApiResult<FollowState> {
        val current = followStates[noticeId] ?: FollowState(noticeId = noticeId)
        if (expectedVersion != current.version) {
            return ApiResult.Failure(ApiError.VersionConflict)
        }
        if (current.starred == starred) {
            return ApiResult.Success(current)
        }
        val next = current.copy(
            starred = starred,
            followedAt = if (starred) OffsetDateTime.now().toString() else null,
            version = current.version + 1,
        )
        followStates[noticeId] = next
        return ApiResult.Success(next)
    }

    private fun withFollow(item: NoticeItem): NoticeItem =
        item.copy(follow = followStates[item.noticeId] ?: item.follow)

    companion object {
        private const val ASSET = "mock/scenario.json"

        /** 读取样例场景；文件缺失属于工程错误，明确返回空场景而不是崩溃。 */
        fun load(context: Context): MockScenario {
            val text = try {
                context.assets.open(ASSET).bufferedReader(Charsets.UTF_8).use { it.readText() }
            } catch (e: IOException) {
                ""
            }
            val root = JsonKit.parseObject(text) ?: emptyObject()
            return MockScenario(root)
        }
    }
}

/** 样例模式的资料/偏好实现。不联网，版本照契约递增。 */
class MockProfileRepository(private val scenario: MockScenario) : ProfileRepository {

    override suspend fun schools(prefix: String?) = scenario.schools(prefix)

    override suspend fun colleges(schoolId: String) = scenario.colleges(schoolId)

    override suspend fun majors(schoolId: String, collegeId: String) =
        scenario.majors(schoolId, collegeId)

    override suspend fun grades() = scenario.grades()

    override suspend fun load() = scenario.loadProfile()

    override suspend fun save(edit: ProfileEdit, idempotencyKey: String) =
        scenario.saveProfile(edit)

    override suspend fun loadPreferences() = scenario.loadPreferences()

    override suspend fun savePreferences(preferences: Preferences, idempotencyKey: String) =
        scenario.savePreferences(preferences)

    override suspend fun preferenceOptions(kind: PreferenceKind) = scenario.preferenceOptions(kind)

    override fun newIdempotencyKey(): String = UUID.randomUUID().toString()

    override fun resetForNewAccount() = scenario.startAsNewUser()
}

/** 样例模式的通知/关注实现。不联网。 */
class MockNoticeRepository(private val scenario: MockScenario) : NoticeRepository {

    override val feedFeature: ContractFeature
        get() = ContractFeature(available = true, phase = "MOCK", name = "通知列表")

    override val followFeature: ContractFeature
        get() = ContractFeature(available = true, phase = "MOCK", name = "我的关注")

    override suspend fun feed(category: Category?, offset: Int, limit: Int): PageResult {
        val page = mockPage(category)
        val items = page.items.drop(offset).take(limit)
        return PageResult.Fresh(page.copy(items = items, total = page.items.size))
    }

    private fun mockPage(category: Category?): NoticePage {
        if (category != null) return (scenario.feed(category) as? ApiResult.Success)?.value ?: NoticePage()
        val all = Category.tabs.flatMap { tab -> (scenario.feed(tab) as? ApiResult.Success)?.value?.items.orEmpty() }
        return NoticePage(items = all, total = all.size)
    }

    override suspend fun detail(noticeId: String): DetailResult =
        when (val result = scenario.detail(noticeId)) {
            is ApiResult.Success -> DetailResult.Fresh(result.value)
            is ApiResult.Failure -> DetailResult.Failed(result.error)
        }

    override suspend fun follows(offset: Int, limit: Int): PageResult {
        val page = (scenario.follows() as? ApiResult.Success)?.value ?: NoticePage()
        return PageResult.Fresh(page.copy(items = page.items.drop(offset).take(limit)))
    }

    override suspend fun setFollow(
        noticeId: String,
        starred: Boolean,
        expectedVersion: Long,
        idempotencyKey: String,
    ): ApiResult<FollowState> = scenario.setFollow(noticeId, starred, expectedVersion)

    override fun cachedFeed(category: Category?): NoticePage? = null

    override fun cachedDetail(noticeId: String): NoticeDetail? = null

    override fun newIdempotencyKey(): String = UUID.randomUUID().toString()
}
