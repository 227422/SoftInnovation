"""Versioned full saves; durable replays take precedence over business validation."""
import hashlib
import json

from campus_backend.catalog.preferences import PreferenceKind, PreferencesCatalog
from campus_backend.core.errors import AppError

from .ports import PreferenceReplay, PreferencesStore
from .schemas import PreferencesUpdate, PreferencesView


def get_preferences(store: PreferencesStore, user_id: str) -> PreferencesView:
    current = store.get_preferences(user_id)
    if current is None:
        return PreferencesView(course_ids=[], skill_ids=[], goal_ids=[], interest_ids=[], version=0)
    return current


def _validate_ids(catalog: PreferencesCatalog, selections: dict[str, list[str]]) -> None:
    invalid = []
    for kind in PreferenceKind:
        field = f"{kind.value}_ids"
        selected = selections[field]
        unique = set(selected)
        if len(unique) != len(selected) or not unique.issubset(option.id for option in catalog.options(kind)):
            invalid.append({"field": f"body.{field}", "type": "value_error"})
    if invalid:
        raise AppError(422, "validation_error", "偏好选项重复或不可用，请检查后重试", invalid)


def save_preferences(store: PreferencesStore, catalog: PreferencesCatalog, user_id: str,
                     payload: PreferencesUpdate, key: str) -> PreferencesView:
    body = payload.model_dump()
    # Canonicalize object fields while retaining array order and expected_version.
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with store.transaction() as tx:
        replay = tx.get_replay(user_id, key)
        if replay is not None:
            if replay.request_hash != request_hash:
                raise AppError(409, "key_payload_conflict", "该提交标识已用于其他内容，请使用新的提交标识")
            return replay.result

        expected_version = body.pop("expected_version")
        _validate_ids(catalog, body)
        result = PreferencesView(**body, version=expected_version + 1)
        if not tx.save_preferences(user_id, result, expected_version):
            raise AppError(409, "version_conflict", "偏好已更新，请重新读取后再保存")
        tx.add_replay(user_id, key, PreferenceReplay(request_hash, result))
    return result
