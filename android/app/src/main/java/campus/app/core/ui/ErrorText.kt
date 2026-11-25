package campus.app.core.ui

import campus.app.core.network.ApiError

/**
 * 错误码 → 用户可读文案。
 *
 * 集中一处，保证同一个错误在所有页面说法一致；
 * 也保证"会话失效""网络失败""接口未上线"不会用同一句话，避免误导用户。
 */
fun ApiError.describe(): String = when (this) {
    ApiError.InvalidCredentials -> "邮箱或密码不正确"
    ApiError.SessionInvalid -> "登录状态已失效，请重新登录"
    ApiError.CsrfInvalid -> "安全校验已失效，请刷新后重试"
    ApiError.OriginForbidden -> "当前来源不被服务接受，请检查访问方式"
    ApiError.RequestRejected -> "请求无法处理，请检查输入后重试"
    ApiError.EmailInUse -> "该邮箱已被注册，可以直接登录"
    ApiError.VersionConflict -> "内容已被其他设备更新，请重新读取后再保存"
    ApiError.KeyPayloadConflict -> "这次提交与之前的记录不一致，请重新操作"
    ApiError.FeedChanged -> "列表已变化，正在重新读取第一页"
    is ApiError.Validation -> if (fields.isEmpty()) {
        "输入内容不符合要求：$message"
    } else {
        "输入内容不符合要求：${fields.joinToString("、")}"
    }
    ApiError.MajorNotAvailable -> "所选专业已不可用，请重新选择"
    ApiError.SchoolNotSupported -> "所选学校暂未支持"
    ApiError.CollegeNotAvailable -> "所选学院暂不可用，请重新选择"
    ApiError.NoticeNotFound -> "这条通知暂不可用"
    ApiError.PayloadTooLarge -> "提交内容过大，请减少内容后重试"
    ApiError.JsonRequired -> "请使用应用内表单提交"
    ApiError.RateLimited -> "操作过于频繁，请稍后再试"
    is ApiError.NetworkUnavailable -> "网络不可用，请检查网络后重试"
    is ApiError.ServiceUnavailable -> "服务暂时不可用，请稍后重试"
    is ApiError.ContractPending -> "该功能尚未上线（后端计划 $phase 阶段实现）"
    is ApiError.Unknown -> "服务返回了无法识别的结果，请稍后重试"
}
