package campus.app.feature.profile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import campus.app.core.LocalAppContainer
import campus.app.core.model.CatalogNode
import campus.app.core.model.GradeOption
import campus.app.core.model.Profile
import campus.app.core.model.ProfileEdit
import campus.app.core.network.ApiError
import campus.app.core.network.ApiResult
import campus.app.core.ui.describe
import campus.app.feature.common.LoadingBox
import campus.app.navigation.RequestGate
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

private enum class PickerField { SCHOOL, COLLEGE, MAJOR, GRADES }

private data class PickerEntry(val id: String, val label: String)

/**
 * 后端 422 的 details[].field 形如 `body.school_id`（也可能有 `header.` `query.` 前缀），
 * 这里统一取最后一段做匹配，避免前缀不同导致字段提示丢失。
 */
private fun normalizeField(field: String): String =
    field.substringAfterLast('.').trim().lowercase()

private fun fieldLabel(field: String): String = when (normalizeField(field)) {
    "school_id" -> "学校"
    "college_id" -> "学院"
    "major_id" -> "专业"
    "grade" -> "年级"
    "expected_version" -> "资料版本"
    else -> field
}

private fun validationText(error: ApiError.Validation): String {
    val labels = error.fields.map { fieldLabel(it) }
    return if (labels.isEmpty()) {
        "输入内容不符合要求：${error.message}"
    } else {
        "以下内容不符合要求：${labels.joinToString("、")}"
    }
}

/**
 * 资料页：学校 → 学院 → 专业 → 年级 四个选择项。
 *
 * 学院/专业只能选不能填，上级变更只清空正在编辑的下级，不提前写库；
 * 迟到的目录响应不得覆盖新的选择（RequestGate）；已保存资料按 id 在目录里回填。
 * 保存失败不清空已选内容，错误以短提示条给出，不占用页面版式。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileSetupScreen(
    continueLabel: String = "下一步",
    onContinue: () -> Unit,
) {
    val container = LocalAppContainer.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    // ---------- 目录数据与加载状态 ----------
    var schools by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }
    var grades by remember { mutableStateOf<List<GradeOption>>(emptyList()) }
    var colleges by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }
    var majors by remember { mutableStateOf<List<CatalogNode>>(emptyList()) }

    var initialLoading by remember { mutableStateOf(true) }
    var schoolsLoading by remember { mutableStateOf(true) }
    var schoolsError by remember { mutableStateOf<String?>(null) }
    var gradesLoading by remember { mutableStateOf(true) }
    var gradesError by remember { mutableStateOf<String?>(null) }
    var collegesLoading by remember { mutableStateOf(false) }
    var collegesError by remember { mutableStateOf<String?>(null) }
    var majorsLoading by remember { mutableStateOf(false) }
    var majorsError by remember { mutableStateOf<String?>(null) }

    // ---------- 权威值 ----------
    var version by remember { mutableStateOf(0L) }
    var profileLoaded by remember { mutableStateOf(false) }
    var profileLoading by remember { mutableStateOf(false) }
    var profileError by remember { mutableStateOf<String?>(null) }

    // ---------- 用户草稿：旋转后保留 ----------
    var draftInitialized by rememberSaveable { mutableStateOf(false) }
    var schoolId by rememberSaveable { mutableStateOf<String?>(null) }
    var schoolName by rememberSaveable { mutableStateOf<String?>(null) }
    var collegeId by rememberSaveable { mutableStateOf<String?>(null) }
    var collegeName by rememberSaveable { mutableStateOf<String?>(null) }
    var majorId by rememberSaveable { mutableStateOf<String?>(null) }
    var majorName by rememberSaveable { mutableStateOf<String?>(null) }
    var gradeValue by rememberSaveable { mutableStateOf<Int?>(null) }

    // ---------- 交互状态 ----------
    var picker by remember { mutableStateOf<PickerField?>(null) }
    var saving by remember { mutableStateOf(false) }
    var saveKey by remember { mutableStateOf<String?>(null) }
    var saveKeyEdit by remember { mutableStateOf<ProfileEdit?>(null) }

    // 目录请求代次：新的选择发出后，迟到的旧响应不得回填界面。
    val schoolGate = remember { RequestGate() }
    val gradeGate = remember { RequestGate() }
    val collegeGate = remember { RequestGate() }
    val majorGate = remember { RequestGate() }
    val profileGate = remember { RequestGate() }

    suspend fun fetchSchools() {
        val token = schoolGate.next()
        schoolsLoading = true
        schoolsError = null
        val result = container.profile.schools()
        if (!schoolGate.isCurrent(token)) return
        schoolsLoading = false
        when (result) {
            is ApiResult.Success -> {
                schools = result.value.items
                val currentSchool = schoolId
                if (currentSchool != null) {
                    result.value.items.firstOrNull { it.id == currentSchool }?.let { schoolName = it.name }
                }
            }

            is ApiResult.Failure -> {
                schools = emptyList()
                schoolsError = result.error.describe()
            }
        }
    }

    suspend fun fetchGrades() {
        val token = gradeGate.next()
        gradesLoading = true
        gradesError = null
        val result = container.profile.grades()
        if (!gradeGate.isCurrent(token)) return
        gradesLoading = false
        when (result) {
            is ApiResult.Success -> grades = result.value
            is ApiResult.Failure -> {
                grades = emptyList()
                gradesError = result.error.describe()
            }
        }
    }

    suspend fun fetchColleges(schoolIdValue: String) {
        val token = collegeGate.next()
        collegesLoading = true
        collegesError = null
        colleges = emptyList()
        val result = container.profile.colleges(schoolIdValue)
        if (!collegeGate.isCurrent(token)) return
        collegesLoading = false
        when (result) {
            is ApiResult.Success -> {
                colleges = result.value.items
                val currentCollege = collegeId
                if (currentCollege != null) {
                    result.value.items.firstOrNull { it.id == currentCollege }?.let { collegeName = it.name }
                }
            }

            is ApiResult.Failure -> collegesError = result.error.describe()
        }
    }

    suspend fun fetchMajors(schoolIdValue: String, collegeIdValue: String) {
        val token = majorGate.next()
        majorsLoading = true
        majorsError = null
        majors = emptyList()
        val result = container.profile.majors(schoolIdValue, collegeIdValue)
        if (!majorGate.isCurrent(token)) return
        majorsLoading = false
        when (result) {
            is ApiResult.Success -> {
                majors = result.value.items
                val currentMajor = majorId
                if (currentMajor != null) {
                    result.value.items.firstOrNull { it.id == currentMajor }?.let { majorName = it.name }
                }
            }

            is ApiResult.Failure -> majorsError = result.error.describe()
        }
    }

    /** 按已选学校/学院补齐下级目录（旋转恢复或资料回填后调用）。 */
    fun syncDependentCatalogs() {
        val sid = schoolId ?: return
        if (!collegesLoading && collegesError == null && colleges.isEmpty()) {
            scope.launch { fetchColleges(sid) }
        }
        val cid = collegeId
        if (cid != null && !majorsLoading && majorsError == null && majors.isEmpty()) {
            scope.launch { fetchMajors(sid, cid) }
        }
    }

    fun applyProfilePrefill(profile: Profile) {
        schoolId = profile.schoolId
        schoolName = profile.schoolName ?: profile.schoolId
        collegeId = profile.collegeId
        collegeName = profile.collegeName ?: profile.collegeId
        majorId = profile.majorId
        majorName = profile.majorName ?: profile.majorId
        gradeValue = profile.grade
        draftInitialized = true
    }

    suspend fun fetchProfile(allowPrefill: Boolean): Boolean {
        val token = profileGate.next()
        profileLoading = true
        profileError = null
        val result = container.profile.load()
        if (!profileGate.isCurrent(token)) return false
        profileLoading = false
        return when (result) {
            is ApiResult.Success -> {
                val response = result.value
                version = response.version
                profileLoaded = true
                val saved = response.profile
                if (allowPrefill && !draftInitialized && saved != null) {
                    applyProfilePrefill(saved)
                }
                syncDependentCatalogs()
                true
            }

            is ApiResult.Failure -> {
                profileLoaded = false
                profileError = result.error.describe()
                false
            }
        }
    }

    // ------------------------------------------------------------ 选择行为
    fun chooseSchool(node: CatalogNode) {
        if (node.id != schoolId) {
            collegeGate.next()
            majorGate.next()
            schoolId = node.id
            schoolName = node.name
            collegeId = null
            collegeName = null
            majorId = null
            majorName = null
            colleges = emptyList()
            collegesError = null
            majors = emptyList()
            majorsError = null
            scope.launch { fetchColleges(node.id) }
        }
        draftInitialized = true
    }

    fun chooseCollege(node: CatalogNode) {
        val sid = schoolId ?: return
        if (node.id != collegeId) {
            majorGate.next()
            collegeId = node.id
            collegeName = node.name
            majorId = null
            majorName = null
            majors = emptyList()
            majorsError = null
            scope.launch { fetchMajors(sid, node.id) }
        }
        draftInitialized = true
    }

    fun chooseMajor(node: CatalogNode) {
        majorId = node.id
        majorName = node.name
        draftInitialized = true
    }

    fun chooseGrade(option: GradeOption) {
        gradeValue = option.value
        draftInitialized = true
    }

    fun selectPickerEntry(field: PickerField, entry: PickerEntry) {
        picker = null
        when (field) {
            PickerField.SCHOOL -> schools.firstOrNull { it.id == entry.id }?.let { chooseSchool(it) }
            PickerField.COLLEGE -> colleges.firstOrNull { it.id == entry.id }?.let { chooseCollege(it) }
            PickerField.MAJOR -> majors.firstOrNull { it.id == entry.id }?.let { chooseMajor(it) }
            PickerField.GRADES -> {
                val value = entry.id.toIntOrNull()
                grades.firstOrNull { it.value == value }?.let { chooseGrade(it) }
            }
        }
    }

    fun reloadPicker(field: PickerField) {
        when (field) {
            PickerField.SCHOOL -> scope.launch { fetchSchools() }
            PickerField.COLLEGE -> {
                val sid = schoolId
                if (sid != null) scope.launch { fetchColleges(sid) }
            }

            PickerField.MAJOR -> {
                val sid = schoolId
                val cid = collegeId
                if (sid != null && cid != null) scope.launch { fetchMajors(sid, cid) }
            }

            PickerField.GRADES -> scope.launch { fetchGrades() }
        }
    }

    // ------------------------------------------------------------ 保存
    suspend fun handleSaveFailure(error: ApiError): String {
        return when (error) {
            ApiError.VersionConflict -> {
                saveKey = null
                saveKeyEdit = null
                if (fetchProfile(allowPrefill = false)) {
                    "资料已在其他设备更新，已重新读取，请确认后再保存"
                } else {
                    "资料已在其他设备更新，重新读取失败，请稍后重试"
                }
            }

            is ApiError.Validation -> {
                saveKey = null
                saveKeyEdit = null
                validationText(error)
            }

            ApiError.SchoolNotSupported -> {
                saveKey = null
                saveKeyEdit = null
                "所选学校暂未支持，请重新选择"
            }

            ApiError.CollegeNotAvailable -> {
                saveKey = null
                saveKeyEdit = null
                "所选学院暂不可用，请重新选择"
            }

            ApiError.MajorNotAvailable -> {
                saveKey = null
                saveKeyEdit = null
                "所选专业暂不可用，请重新选择"
            }

            ApiError.KeyPayloadConflict -> {
                saveKey = null
                saveKeyEdit = null
                "这次提交与之前的记录不一致，请重新保存"
            }

            ApiError.SessionInvalid -> {
                saveKey = null
                saveKeyEdit = null
                error.describe() + "。你的选择已保留"
            }

            else -> error.describe() + "。你的选择已保留，可重试保存"
        }
    }

    fun save() {
        if (saving) return

        val missing = buildList {
            if (schoolId == null) add("学校")
            if (collegeId == null) add("学院")
            if (majorId == null) add("专业")
            if (gradeValue == null) add("年级")
        }
        if (missing.isNotEmpty()) {
            scope.launch {
                snackbar.showSnackbar(
                    message = "请先选择" + missing.joinToString("、"),
                    duration = SnackbarDuration.Short,
                )
            }
            return
        }
        if (!profileLoaded) {
            scope.launch {
                snackbar.showSnackbar(
                    message = "资料读取失败，请先重试",
                    duration = SnackbarDuration.Short,
                )
            }
            return
        }

        val edit = ProfileEdit(
            schoolId = schoolId.orEmpty(),
            collegeId = collegeId.orEmpty(),
            majorId = majorId.orEmpty(),
            grade = gradeValue ?: 0,
            // 本产品只面向本科生，保存时统一按本科身份提交。
            educationStage = "undergraduate",
            expectedVersion = version,
        )
        // 同一次逻辑保存（正文完全一致）的多次重试复用同一个幂等键。
        val key = if (saveKey != null && saveKeyEdit == edit) {
            saveKey.orEmpty()
        } else {
            container.profile.newIdempotencyKey().also {
                saveKey = it
                saveKeyEdit = edit
            }
        }

        saving = true
        scope.launch {
            when (val result = container.profile.save(edit, key)) {
                is ApiResult.Success -> {
                    saving = false
                    saveKey = null
                    saveKeyEdit = null
                    version = result.value.version
                    onContinue()
                }

                is ApiResult.Failure -> {
                    val message = handleSaveFailure(result.error)
                    saving = false
                    snackbar.showSnackbar(message = message, duration = SnackbarDuration.Long)
                }
            }
        }
    }

    LaunchedEffect(container) {
        initialLoading = true
        coroutineScope {
            launch { fetchSchools() }
            launch { fetchGrades() }
            launch { fetchProfile(allowPrefill = true) }
        }
        initialLoading = false
    }

    // ------------------------------------------------------------ 界面
    val schoolDisplay = schoolName?.takeIf { it.isNotBlank() } ?: schoolId
    val collegeDisplay = collegeName?.takeIf { it.isNotBlank() } ?: collegeId
    val majorDisplay = majorName?.takeIf { it.isNotBlank() } ?: majorId
    val gradeDisplay = gradeValue?.let { value ->
        grades.firstOrNull { it.value == value }?.label ?: "第 $value 年级"
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text("设置我的身份") }) },
    ) { padding ->
        if (initialLoading) {
            Column(modifier = Modifier.padding(padding).fillMaxSize()) {
                LoadingBox("正在加载…")
            }
        } else {
            Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                if (profileLoading) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        Text("正在读取已保存资料…", style = MaterialTheme.typography.bodySmall)
                    }
                }
                profileError?.let { message ->
                    OutlinedCard(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(
                                text = "已保存资料读取失败：$message",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.error,
                            )
                            TextButton(onClick = { scope.launch { fetchProfile(allowPrefill = true) } }) {
                                Text("重试")
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                }

                SelectorRow(
                    label = "学校",
                    value = schoolDisplay,
                    placeholder = when {
                        schoolsLoading -> "加载中…"
                        schoolsError != null -> "加载失败，请重试"
                        schools.isEmpty() -> "暂无可选项"
                        else -> "未选择"
                    },
                    enabled = !schoolsLoading && schoolsError == null && !saving,
                    onClick = { picker = PickerField.SCHOOL },
                )
                if (schoolsError != null) {
                    TextButton(onClick = { scope.launch { fetchSchools() } }) { Text("重新加载学校") }
                }

                SelectorRow(
                    label = "学院",
                    value = collegeDisplay,
                    placeholder = when {
                        schoolId == null -> "请先选择学校"
                        collegesLoading -> "加载中…"
                        collegesError != null -> "加载失败，请重试"
                        colleges.isEmpty() -> "暂无可选项"
                        else -> "未选择"
                    },
                    enabled = schoolId != null && !collegesLoading && collegesError == null && !saving,
                    onClick = { picker = PickerField.COLLEGE },
                )
                if (collegesError != null) {
                    TextButton(onClick = {
                        val sid = schoolId
                        if (sid != null) scope.launch { fetchColleges(sid) }
                    }) { Text("重新加载学院") }
                }

                SelectorRow(
                    label = "专业",
                    value = majorDisplay,
                    placeholder = when {
                        collegeId == null -> "请先选择学院"
                        majorsLoading -> "加载中…"
                        majorsError != null -> "加载失败，请重试"
                        majors.isEmpty() -> "暂无可选项"
                        else -> "未选择"
                    },
                    enabled = collegeId != null && !majorsLoading && majorsError == null && !saving,
                    onClick = { picker = PickerField.MAJOR },
                )
                if (majorsError != null) {
                    TextButton(onClick = {
                        val sid = schoolId
                        val cid = collegeId
                        if (sid != null && cid != null) scope.launch { fetchMajors(sid, cid) }
                    }) { Text("重新加载专业") }
                }

                SelectorRow(
                    label = "年级",
                    value = gradeDisplay,
                    placeholder = when {
                        gradesLoading -> "加载中…"
                        gradesError != null -> "加载失败，请重试"
                        grades.isEmpty() -> "暂无可选项"
                        else -> "未选择"
                    },
                    enabled = !gradesLoading && gradesError == null && !saving,
                    onClick = { picker = PickerField.GRADES },
                )
                if (gradesError != null) {
                    TextButton(onClick = { scope.launch { fetchGrades() } }) { Text("重新加载年级") }
                }

                Spacer(Modifier.height(24.dp))

                Button(
                    onClick = { save() },
                    enabled = !saving,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (saving) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                        Spacer(Modifier.size(8.dp))
                        Text("保存中…")
                    } else {
                        Text(continueLabel)
                    }
                }
                TextButton(onClick = onContinue, enabled = !saving, modifier = Modifier.fillMaxWidth()) {
                    Text("先跳过，以后再说")
                }

                Spacer(Modifier.height(16.dp))
            }
        }
    }

    // ------------------------------------------------------------ 选择弹窗
    val pickerField = picker
    if (pickerField != null) {
        val pickerOptions: List<PickerEntry> = when (pickerField) {
            PickerField.SCHOOL -> schools.map { PickerEntry(it.id, it.name) }
            PickerField.COLLEGE -> colleges.map { PickerEntry(it.id, it.name) }
            PickerField.MAJOR -> majors.map { PickerEntry(it.id, it.name) }
            PickerField.GRADES -> grades.map { PickerEntry(it.value.toString(), it.label) }
        }
        val pickerTitle = when (pickerField) {
            PickerField.SCHOOL -> "选择学校"
            PickerField.COLLEGE -> "选择学院"
            PickerField.MAJOR -> "选择专业"
            PickerField.GRADES -> "选择年级"
        }
        AlertDialog(
            onDismissRequest = { picker = null },
            title = { Text(pickerTitle) },
            text = {
                Column {
                    if (pickerOptions.isEmpty()) {
                        Text("暂无可选项", style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { reloadPicker(pickerField) }) { Text("重新加载") }
                    } else {
                        LazyColumn(modifier = Modifier.heightIn(max = 360.dp)) {
                            items(pickerOptions, key = { it.id }) { entry ->
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable { selectPickerEntry(pickerField, entry) }
                                        .padding(vertical = 12.dp),
                                ) {
                                    Text(entry.label, style = MaterialTheme.typography.bodyLarge)
                                    HorizontalDivider(modifier = Modifier.padding(top = 10.dp))
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { picker = null }) { Text("关闭") }
            },
        )
    }
}

@Composable
private fun SelectorRow(
    label: String,
    value: String?,
    placeholder: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    OutlinedCard(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(enabled = enabled, onClick = onClick)
                .padding(14.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Text(
                text = value ?: placeholder,
                style = MaterialTheme.typography.bodyMedium,
                color = if (value != null) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
    }
}
