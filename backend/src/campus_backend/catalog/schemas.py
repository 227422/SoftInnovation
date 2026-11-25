"""HTTP directory views, including the existing catalog metadata."""
from typing import Annotated

from pydantic import BaseModel, Field


class CatalogItems[Item](BaseModel):
    items: list[Item]
    message: str | None


class SchoolSource(BaseModel):
    url: str
    content_version: str
    checked_on: str


class SchoolItem(BaseModel):
    id: str
    name: str
    code: str
    notes: str
    source: SchoolSource
    coverage: str


class CollegeItem(BaseModel):
    id: str
    school_id: str
    name: str
    code: str
    notes: str


class MajorItem(CollegeItem):
    college_id: str
    degree: str
    duration: str


class GradeItem(BaseModel):
    value: Annotated[int, Field(ge=1, le=8)]
    label: str


class GradeItems(BaseModel):
    items: list[GradeItem]
