"""SQLAlchemy catalog reads, converted to plain immutable records."""
from dataclasses import fields

from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_backend.core.persistence import storage_errors
from ..ports import CollegeRecord, MajorRecord, SchoolRecord
from .models import College, Major, School


def _record(record_type, row):
    if row is None:
        return None
    return record_type(**{field.name: getattr(row, field.name) for field in fields(record_type)})


class SQLAlchemyCatalogStore:
    def __init__(self, db: Session):
        self.db = db

    def get_school(self, id: str) -> SchoolRecord | None:
        with storage_errors():
            return _record(SchoolRecord, self.db.get(School, id))

    def get_college(self, id: str) -> CollegeRecord | None:
        with storage_errors():
            return _record(CollegeRecord, self.db.get(College, id))

    def get_major(self, id: str) -> MajorRecord | None:
        with storage_errors():
            return _record(MajorRecord, self.db.get(Major, id))

    def find_schools(self, prefix: str) -> list[SchoolRecord]:
        with storage_errors():
            # Escape LIKE metacharacters; services additionally enforce exact case.
            rows = self.db.scalars(select(School).where(
                School.name.startswith(prefix, autoescape=True)
            ))
            return [_record(SchoolRecord, row) for row in rows]

    def find_colleges(self, school_id: str) -> list[CollegeRecord]:
        with storage_errors():
            rows = self.db.scalars(select(College).where(College.school_id == school_id))
            return [_record(CollegeRecord, row) for row in rows]

    def find_majors(self, school_id: str, college_id: str) -> list[MajorRecord]:
        with storage_errors():
            rows = self.db.scalars(select(Major).where(
                Major.school_id == school_id, Major.college_id == college_id
            ))
            return [_record(MajorRecord, row) for row in rows]

    def find_school_majors(self, school_id: str) -> list[MajorRecord]:
        with storage_errors():
            rows = self.db.scalars(select(Major).where(Major.school_id == school_id))
            return [_record(MajorRecord, row) for row in rows]
