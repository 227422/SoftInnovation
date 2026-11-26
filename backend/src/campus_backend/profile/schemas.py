"""Full-save input and authoritative profile response contracts."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from campus_backend.core.versions import ExpectedVersion, Version

from .ports import EducationStage

Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128)]
AdmissionYear = Annotated[StrictInt, Field(ge=1900, le=2100)]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school_id: Identifier
    college_id: Identifier
    major_id: Identifier
    grade: Annotated[StrictInt, Field(ge=1, le=8)]
    expected_version: ExpectedVersion
    education_stage: EducationStage | None = Field(default_factory=lambda: None)
    admission_year: AdmissionYear | None = None

    @field_validator("education_stage", mode="before", json_schema_input_type=EducationStage)
    @classmethod
    def reject_explicit_null_stage(cls, value):
        if value is None:
            raise ValueError("education_stage must be undergraduate when supplied")
        return value


class MajorGroupView(BaseModel):
    id: str
    name: str


class ProfileView(BaseModel):
    # Old saved snapshots can omit extension fields; serialization always emits them.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    school_id: str
    school_name: str
    college_id: str
    college_name: str
    major_id: str
    major_name: str
    grade: Annotated[int, Field(ge=1, le=8)]
    version: Version
    education_stage: EducationStage | None = None
    admission_year: AdmissionYear | None = None
    major_group: MajorGroupView | None = None


class ProfileResponse(BaseModel):
    completed: bool
    profile: ProfileView | None
    version: Version
