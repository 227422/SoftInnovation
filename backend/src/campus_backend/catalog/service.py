from dataclasses import dataclass

from campus_backend.core.errors import AppError
from .ports import CatalogStore, SchoolRecord, CollegeRecord, MajorRecord


@dataclass(frozen=True)
class Selection:
    school_id: str
    school_name: str
    college_id: str
    college_name: str
    major_id: str
    major_name: str


def _school(store: CatalogStore, school_id: str) -> SchoolRecord:
    school = store.get_school(school_id)
    if school is None or not school.enabled:
        raise AppError(404, 'school_not_supported', '学校不存在或暂未支持，请重新选择')
    return school


def _college(store: CatalogStore, school_id: str, college_id: str) -> CollegeRecord:
    college = store.get_college(college_id)
    if college is None or not college.enabled or college.school_id != school_id:
        raise AppError(404, 'college_not_available', '学院不存在、已停用或不属于所选学校，请重新选择')
    return college


def source_for_school(school: SchoolRecord) -> dict:
    return {'url': school.source_url, 'content_version': school.source_version,
            'checked_on': school.source_checked_on}


def _school_item(school: SchoolRecord) -> dict:
    return {'id': school.id, 'name': school.name, 'code': school.code, 'notes': school.notes,
            'source': source_for_school(school), 'coverage': school.coverage}


def _college_item(college: CollegeRecord) -> dict:
    return {'id': college.id, 'school_id': college.school_id, 'name': college.name,
            'code': college.code, 'notes': college.notes}


def _major_item(major: MajorRecord) -> dict:
    return {'id': major.id, 'school_id': major.school_id, 'college_id': major.college_id,
            'name': major.name, 'code': major.code, 'notes': major.notes,
            'degree': major.degree, 'duration': major.duration}


def list_schools(store: CatalogStore, prefix: str = '') -> list[dict]:
    # Exact literal case is a business rule, independent of database collation.
    schools = (s for s in store.find_schools(prefix) if s.enabled and s.name.startswith(prefix))
    return [_school_item(s) for s in sorted(schools, key=lambda s: (s.name, s.id))]


def list_colleges(store: CatalogStore, school_id: str) -> list[dict]:
    _school(store, school_id)
    colleges = (c for c in store.find_colleges(school_id) if c.enabled and c.school_id == school_id)
    return [_college_item(c) for c in sorted(colleges, key=lambda c: (c.name, c.id))]


def list_majors(store: CatalogStore, school_id: str, college_id: str) -> list[dict]:
    _school(store, school_id)
    _college(store, school_id, college_id)
    majors = (m for m in store.find_majors(school_id, college_id)
              if m.enabled and m.school_id == school_id and m.college_id == college_id)
    return [_major_item(m) for m in sorted(majors, key=lambda m: (m.name, m.duration, m.id))]


def list_school_majors(store: CatalogStore, school_id: str) -> list[dict]:
    _school(store, school_id)
    available_colleges = {c.id for c in store.find_colleges(school_id)
                          if c.enabled and c.school_id == school_id}
    majors = (m for m in store.find_school_majors(school_id)
              if m.enabled and m.school_id == school_id and m.college_id in available_colleges)
    return [_major_item(m) for m in sorted(majors, key=lambda m: (m.name, m.duration, m.id))]


def validate_selection(store: CatalogStore, school_id: str, college_id: str, major_id: str) -> Selection:
    school = _school(store, school_id)
    college = _college(store, school_id, college_id)
    major = store.get_major(major_id)
    if (major is None or not major.enabled or major.school_id != school_id
            or major.college_id != college_id):
        raise AppError(422, 'major_not_available', '专业不存在、已停用或不属于所选学校和学院，请重新选择')
    return Selection(school.id, school.name, college.id, college.name, major.id, major.name)
