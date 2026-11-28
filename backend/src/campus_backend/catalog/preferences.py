"""Published self-report options used by the catalog and preference validation."""
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files

from pydantic import BaseModel, ConfigDict


class PreferenceKind(StrEnum):
    COURSE = "course"
    SKILL = "skill"
    GOAL = "goal"
    INTEREST = "interest"


class PreferenceOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    hint: str | None = None


class PreferenceOptions(BaseModel):
    items: tuple[PreferenceOption, ...]
    message: str | None


class PreferencesCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    course: tuple[PreferenceOption, ...]
    skill: tuple[PreferenceOption, ...]
    goal: tuple[PreferenceOption, ...]
    interest: tuple[PreferenceOption, ...]

    def options(self, kind: PreferenceKind) -> tuple[PreferenceOption, ...]:
        return getattr(self, kind.value)


@lru_cache(maxsize=1)
def load_preferences_catalog() -> PreferencesCatalog:
    data = files("campus_backend.catalog").joinpath("data/preferences.json")
    return PreferencesCatalog.model_validate_json(data.read_bytes())


def list_preferences_options(catalog: PreferencesCatalog, kind: PreferenceKind) -> PreferenceOptions:
    items = catalog.options(kind)
    if items:
        message = "这些选项仅供用户自述，非资格核验"
    elif kind == PreferenceKind.COURSE:
        message = "课程目录尚待核验，可跳过"
    else:
        message = None
    return PreferenceOptions(items=items, message=message)
