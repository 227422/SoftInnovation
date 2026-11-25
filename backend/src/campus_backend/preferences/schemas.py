"""Full replacement input and authoritative preference snapshot."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from campus_backend.core.versions import ExpectedVersion, Version

PreferenceId = Annotated[StrictStr, Field(min_length=1, max_length=128)]
PreferenceIds = Annotated[
    list[PreferenceId], Field(max_length=100, json_schema_extra={"uniqueItems": True}),
]


class PreferenceSelection(BaseModel):
    course_ids: PreferenceIds
    skill_ids: PreferenceIds
    goal_ids: PreferenceIds
    interest_ids: PreferenceIds


class PreferencesUpdate(PreferenceSelection):
    model_config = ConfigDict(extra="forbid")

    expected_version: ExpectedVersion


class PreferencesView(PreferenceSelection):
    version: Version
