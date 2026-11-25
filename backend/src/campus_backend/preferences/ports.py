"""Account-scoped reads and atomic preference/replay writes."""
from dataclasses import dataclass
from typing import ContextManager, Protocol

from .schemas import PreferencesView


@dataclass(frozen=True)
class PreferenceReplay:
    request_hash: str
    result: PreferencesView


class PreferencesTransaction(Protocol):
    """Serialize writers before replay, and commit the snapshot and replay together."""

    def get_replay(self, user_id: str, key: str) -> PreferenceReplay | None: ...
    def save_preferences(self, user_id: str, snapshot: PreferencesView, expected_version: int) -> bool: ...
    def add_replay(self, user_id: str, key: str, replay: PreferenceReplay) -> None: ...


class PreferencesStore(Protocol):
    def get_preferences(self, user_id: str) -> PreferencesView | None: ...
    def transaction(self) -> ContextManager[PreferencesTransaction]: ...
