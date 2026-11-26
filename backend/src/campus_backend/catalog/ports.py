"""Plain catalog records and the database-independent lookup contract."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SchoolRecord:
    id: str
    name: str
    code: str = ''
    enabled: bool = True
    notes: str = ''
    source_url: str = ''
    source_version: str = ''
    source_checked_on: str = ''
    coverage: str = ''


@dataclass(frozen=True)
class CollegeRecord:
    id: str
    school_id: str
    name: str
    code: str = ''
    enabled: bool = True
    notes: str = ''


@dataclass(frozen=True)
class MajorRecord:
    id: str
    school_id: str
    college_id: str
    name: str
    code: str = ''
    enabled: bool = True
    notes: str = ''
    degree: str = ''
    duration: str = ''


class CatalogStore(Protocol):
    """Read records; services decide whether they are enabled and selectable."""

    def get_school(self, id: str) -> SchoolRecord | None: ...
    def get_college(self, id: str) -> CollegeRecord | None: ...
    def get_major(self, id: str) -> MajorRecord | None: ...
    def find_schools(self, prefix: str) -> list[SchoolRecord]: ...
    def find_colleges(self, school_id: str) -> list[CollegeRecord]: ...
    def find_majors(self, school_id: str, college_id: str) -> list[MajorRecord]: ...
    def find_school_majors(self, school_id: str) -> list[MajorRecord]: ...
