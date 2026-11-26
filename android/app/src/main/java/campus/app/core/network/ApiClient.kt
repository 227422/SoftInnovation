package campus.app.core.network

import campus.app.core.model.PreferenceKind
import campus.app.core.model.ProfileEdit
import campus.app.core.session.AuthGeneration
import campus.app.core.session.SessionView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * HTTP 客户端。只做四件事：
 * 1. 按契约拼请求（Cookie、CSRF、幂等键、JSON 正文、版本放正文）；
 * 2. 非 2xx 统一交给 [ErrorDecoder]；
 * 3. 网络异常映射成 [ApiError.NetworkUnavailable]——网络失败不等于空结果；
 * 4. 返回原始 JSON，由 Repository 决定缓存与映射。
 *
 * 页面不直接用，只通过 Repository。
 */
class ApiClient(
    baseUrl: String,
    cookieJar: CookieJar,
    private val csrfProvider: () -> String?,
    private val authGeneration: AuthGeneration = AuthGeneration(),
    okHttpClient: OkHttpClient? = null,
    fallbackBaseUrls: List<String> = emptyList(),
    private val onBaseResolved: ((String) -> Unit)? = null,
) {

    /** 本机联调可能有多个可用地址，按顺序试，记住能用的那个。 */
    private val bases: List<String> = (listOf(baseUrl) + fallbackBaseUrls).filter { it.isNotBlank() }

    @Volatile
    private var preferredBase: String? = null

    private val guardedJar = GenerationAwareCookieJar(cookieJar, authGeneration)

    private val client: OkHttpClient = okHttpClient ?: OkHttpClient.Builder()
        .cookieJar(guardedJar)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    // ---------------------------------------------------------------- 账号

    suspend fun register(email: String, password: String): ApiResult<JsonObject> =
        call("POST", "/v1/auth/register", body = credentials(email, password), withBody = true)

    suspend fun login(email: String, password: String): ApiResult<JsonObject> =
        call("POST", "/v1/auth/login", body = credentials(email, password), withBody = true)

    suspend fun session(): ApiResult<JsonObject> = call("GET", "/v1/auth/session")

    /** 刷新返回原会话与固定到期时间，不续期。需要当前 CSRF。 */
    suspend fun refresh(): ApiResult<JsonObject> =
        call("POST", "/v1/auth/refresh", csrf = true, withBody = false)

    /** 退出返回 204 无正文，并删除 Cookie。需要当前 CSRF。 */
    suspend fun logout(): ApiResult<JsonObject> =
        call("POST", "/v1/auth/logout", csrf = true, withBody = false)

    // ---------------------------------------------------------------- 目录

    suspend fun schools(prefix: String? = null): ApiResult<JsonObject> =
        call("GET", "/v1/catalog/schools", query = prefix?.let { mapOf("prefix" to it) } ?: emptyMap())

    suspend fun colleges(schoolId: String): ApiResult<JsonObject> =
        call("GET", "/v1/catalog/schools/$schoolId/colleges")

    suspend fun majors(schoolId: String, collegeId: String): ApiResult<JsonObject> =
        call("GET", "/v1/catalog/schools/$schoolId/colleges/$collegeId/majors")

    suspend fun grades(): ApiResult<JsonObject> = call("GET", "/v1/catalog/grades")

    /** 偏好目录按 kind 分别读取；message 由后端说明（例如课程目录待核验）。 */
    suspend fun preferenceCatalog(kind: PreferenceKind): ApiResult<JsonObject> =
        call("GET", "/v1/catalog/preferences", query = mapOf("kind" to kind.wire))

    // ---------------------------------------------------------------- 资料

    suspend fun profile(): ApiResult<JsonObject> = call("GET", "/v1/me/profile")

    /**
     * 资料全量保存。版本放 JSON 正文 `expected_version`（不是请求头），
     * 写请求带 8—128 字符的幂等键。
     */
    suspend fun saveProfile(edit: ProfileEdit, idempotencyKey: String = newIdempotencyKey()): ApiResult<JsonObject> {
        val body = buildJsonObject {
            put("school_id", edit.schoolId)
            put("college_id", edit.collegeId)
            put("major_id", edit.majorId)
            put("grade", edit.grade)
            put("expected_version", edit.expectedVersion)
            if (edit.admissionYearSpecified) {
                if (edit.admissionYear == null) {
                    put("admission_year", JsonNull)
                } else {
                    put("admission_year", edit.admissionYear)
                }
            }
            // education_stage 只能省略或传 "undergraduate"；显式 null 会被 422 拒绝。
            edit.educationStage?.let { put("education_stage", it) }
        }
        return call("PATCH", "/v1/me/profile", body = body, csrf = true, idempotencyKey = idempotencyKey)
    }

    // ---------------------------------------------------------------- 偏好

    suspend fun preferences(): ApiResult<JsonObject> = call("GET", "/v1/me/preferences")

    /** 四组数组全部提交，独立版本放正文；空数组表示未选择，不表示不具备。 */
    suspend fun savePreferences(
        courseIds: List<String>,
        skillIds: List<String>,
        goalIds: List<String>,
        interestIds: List<String>,
        expectedVersion: Long,
        idempotencyKey: String = newIdempotencyKey(),
    ): ApiResult<JsonObject> {
        val body = buildJsonObject {
            put("course_ids", stringArray(courseIds))
            put("skill_ids", stringArray(skillIds))
            put("goal_ids", stringArray(goalIds))
            put("interest_ids", stringArray(interestIds))
            put("expected_version", expectedVersion)
        }
        return call("PATCH", "/v1/me/preferences", body = body, csrf = true, idempotencyKey = idempotencyKey)
    }

    // ---------------------------------------------------------------- v2 通知与关注（planned）

    /**
     * 首页列表。offset>0 必须带第一页 list_revision 作为 expected_revision。
     * 该接口当前为 planned，服务端会返回 404 request_rejected。
     */
    suspend fun notices(
        categoryWire: String?,
        offset: Int = 0,
        limit: Int = 20,
    ): ApiResult<JsonObject> {
        val query = linkedMapOf(
            "offset" to offset.toString(),
            "limit" to limit.toString(),
        )
        categoryWire?.let { query["category"] = it }
        return call("GET", "/v1/me/notices", query = query)
    }

    suspend fun noticeDetail(noticeId: String): ApiResult<JsonObject> =
        call("GET", "/v1/me/notices/$noticeId")

    suspend fun follows(offset: Int = 0, limit: Int = 20): ApiResult<JsonObject> {
        val query = linkedMapOf(
            "offset" to offset.toString(),
            "limit" to limit.toString(),
        )
        return call("GET", "/v1/me/follows", query = query)
    }

    /** 关注/取消关注：提交目标状态，绝不提交 toggle；版本与幂等键按契约。 */
    suspend fun putFollow(
        noticeId: String,
        starred: Boolean,
        expectedVersion: Long,
        idempotencyKey: String = newIdempotencyKey(),
    ): ApiResult<JsonObject> {
        val body = buildJsonObject {
            put("starred", starred)
            put("expected_version", expectedVersion)
        }
        return call(
            method = "PUT",
            path = "/v1/me/notices/$noticeId/follow",
            body = body,
            csrf = true,
            idempotencyKey = idempotencyKey,
        )
    }

    // ---------------------------------------------------------------- 类型化封装

    suspend fun loginSession(email: String, password: String): ApiResult<SessionView> =
        login(email, password).map { Mappers.session(it) }

    suspend fun registerSession(email: String, password: String): ApiResult<SessionView> =
        register(email, password).map { Mappers.session(it) }

    suspend fun restoreSession(): ApiResult<SessionView> =
        session().map { Mappers.session(it) }

    suspend fun refreshSession(): ApiResult<SessionView> =
        refresh().map { Mappers.session(it) }

    suspend fun catalogSchools(prefix: String? = null) = schools(prefix).map { Mappers.catalogPage(it) }

    suspend fun catalogColleges(schoolId: String) = colleges(schoolId).map { Mappers.catalogPage(it) }

    suspend fun catalogMajors(schoolId: String, collegeId: String) =
        majors(schoolId, collegeId).map { Mappers.catalogPage(it) }

    suspend fun catalogGrades() = grades().map { Mappers.grades(it) }

    suspend fun catalogPreferences(kind: PreferenceKind) =
        preferenceCatalog(kind).map { Mappers.catalogPage(it) }

    suspend fun myProfile() = profile().map { Mappers.profileResponse(it) }

    suspend fun myPreferences() = preferences().map { Mappers.preferences(it) }

    // ---------------------------------------------------------------- 底层

    private fun credentials(email: String, password: String): JsonObject = buildJsonObject {
        put("email", email)
        put("password", password)
    }

    private fun stringArray(values: List<String>): JsonArray =
        JsonArray(values.map { JsonPrimitive(it) })

    private suspend fun call(
        method: String,
        path: String,
        query: Map<String, String> = emptyMap(),
        body: JsonObject? = null,
        csrf: Boolean = false,
        idempotencyKey: String? = null,
        withBody: Boolean = body != null,
    ): ApiResult<JsonObject> = withContext(Dispatchers.IO) {
        val generation = authGeneration.current()
        var lastFailure: ApiError? = null

        for (base in orderedBases()) {
            val url = buildUrl(base, path, query)
            if (url == null) {
                lastFailure = ApiError.Unknown("bad_base_url", "服务地址未配置", null)
                continue
            }

            val builder = Request.Builder().url(url)
            when (method) {
                "GET" -> builder.get()
                "POST", "PATCH", "PUT", "DELETE" -> {
                    val requestBody = if (withBody) {
                        (body ?: JsonObject(emptyMap())).toString().toRequestBody(jsonType)
                    } else {
                        ByteArray(0).toRequestBody(null)
                    }
                    builder.method(method, requestBody)
                    if (withBody) builder.header("Content-Type", "application/json; charset=utf-8")
                    if (csrf) csrfProvider()?.let { builder.header("X-CSRF-Token", it) }
                    idempotencyKey?.let { builder.header("Idempotency-Key", it) }
                }
                else -> return@withContext ApiResult.Failure(
                    ApiError.Unknown("bad_method", "不支持的请求方法：$method", null),
                )
            }

            val response = try {
                RequestGeneration.with(generation) {
                    client.newCall(builder.build()).execute()
                }
            } catch (e: IOException) {
                // 这个地址连不上就换下一个，不把空结果当成"没有通知"。
                lastFailure = ErrorDecoder.fromNetworkError(e.message)
                continue
            }

            response.use { resp ->
                val text = try {
                    resp.body?.string().orEmpty()
                } catch (e: IOException) {
                    ""
                }

                if (resp.isSuccessful) {
                    if (preferredBase != base) {
                        preferredBase = base
                        onBaseResolved?.invoke(base)
                    }
                    if (text.isBlank()) {
                        // 204 等无正文响应：不得强行解 JSON。
                        return@withContext ApiResult.Success(JsonObject(emptyMap()))
                    }
                    val parsed = JsonKit.parseObject(text)
                        ?: return@withContext ApiResult.Failure(
                            ApiError.Unknown("bad_json", "返回内容不是合法 JSON", resp.header("X-Request-ID")),
                        )
                    return@withContext ApiResult.Success(parsed)
                }

                val errorBody = JsonKit.parseObject(text)?.let { Mappers.errorEnvelope(it) }
                val decoded = ErrorDecoder.fromHttp(
                    status = resp.code,
                    code = errorBody?.code,
                    message = errorBody?.message,
                    requestId = errorBody?.requestId ?: resp.header("X-Request-ID"),
                    fields = errorBody?.fields.orEmpty(),
                )
                return@withContext ApiResult.Failure(decoded)
            }
        }

        ApiResult.Failure(lastFailure ?: ApiError.Unknown("bad_base_url", "服务地址未配置", null))
    }

    /** 上次成功的地址优先，避免每次请求都先撞一次失败。 */
    private fun orderedBases(): List<String> {
        val preferred = preferredBase ?: return bases
        return listOf(preferred) + bases.filter { it != preferred }
    }

    private fun buildUrl(baseUrl: String, path: String, query: Map<String, String>): HttpUrl? {
        if (baseUrl.isBlank()) return null
        val base = baseUrl.trimEnd('/').toHttpUrlOrNull() ?: return null
        val builder = base.newBuilder()
        path.trimStart('/').split('/').forEach { segment -> builder.addPathSegment(segment) }
        query.forEach { (key, value) -> builder.addQueryParameter(key, value) }
        return builder.build()
    }

    private fun newIdempotencyKey(): String = UUID.randomUUID().toString()
}

/**
 * 保留失败，成功则交给 [transform] 转换；transform 返回 null 视为结构不符，
 * 仍然是失败，而不是"空成功"。
 */
inline fun <T, R> ApiResult<T>.map(transform: (T) -> R?): ApiResult<R> = when (this) {
    is ApiResult.Success -> {
        val mapped = transform(value)
        if (mapped == null) {
            ApiResult.Failure(ApiError.Unknown("bad_payload", "返回数据结构不符合预期", null))
        } else {
            ApiResult.Success(mapped)
        }
    }
    is ApiResult.Failure -> this
}
