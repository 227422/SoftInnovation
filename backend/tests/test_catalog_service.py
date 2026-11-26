"""Business rules run against plain catalog data without a database session."""

import pytest

from campus_backend.catalog.ports import SchoolRecord, CollegeRecord, MajorRecord
from campus_backend.catalog.service import (
    list_schools, list_colleges, list_majors, list_school_majors, validate_selection,
)
from campus_backend.core.errors import AppError


def school(id, name, enabled=True):
    return SchoolRecord(id=id, name=name, enabled=enabled, code='S', notes='reviewed',
                           source_url='https://example.test/source', source_version='v1',
                           source_checked_on='2026-10-30', coverage='fixture')


def college(id, school_id, enabled=True):
    return CollegeRecord(id=id, school_id=school_id, name=id, code='C', notes='', enabled=enabled)


def major(id, school_id, college_id, enabled=True):
    return MajorRecord(id=id, school_id=school_id, college_id=college_id,
                           name=id, code='M', notes='', degree='本科', duration='四年', enabled=enabled)


class FakeCatalogStore:
    def __init__(self):
        self.schools = [school('s', '中南大学'), school('off', '中停用', False),
                        school('percent', '中%字面'), school('latin', 'Case University')]
        self.colleges = [college('c', 's'), college('off-c', 's', False), college('foreign-c', 'percent')]
        self.majors = [major('m', 's', 'c'), major('off-m', 's', 'c', False),
                       major('hidden-parent', 's', 'off-c'), major('wrong-parent', 's', 'foreign-c')]

    def get_school(self, id):
        return next((item for item in self.schools if item.id == id), None)

    def get_college(self, id):
        return next((item for item in self.colleges if item.id == id), None)

    def get_major(self, id):
        return next((item for item in self.majors if item.id == id), None)

    def find_schools(self, prefix):
        # Deliberately includes disabled rows and case-insensitive matches, as a DB may.
        return [item for item in self.schools if item.name.lower().startswith(prefix.lower())]

    def find_colleges(self, school_id):
        return [item for item in self.colleges if item.school_id == school_id]

    def find_majors(self, school_id, college_id):
        return [item for item in self.majors
                if item.school_id == school_id and item.college_id == college_id]

    def find_school_majors(self, school_id):
        return [item for item in self.majors if item.school_id == school_id]


def test_plain_store_listing_enforces_enabled_literal_prefix_and_presentation():
    store = FakeCatalogStore()
    assert [item['id'] for item in list_schools(store, '中')] == ['percent', 's']
    assert [item['id'] for item in list_schools(store, '中%')] == ['percent']
    assert list_schools(store, 'case') == []
    assert list_schools(store, '%') == []
    assert list_schools(store, '中南')[0]['source'] == {
        'url': 'https://example.test/source', 'content_version': 'v1', 'checked_on': '2026-10-30',
    }
    assert [item['id'] for item in list_colleges(store, 's')] == ['c']
    assert [item['id'] for item in list_majors(store, 's', 'c')] == ['m']
    assert [item['id'] for item in list_school_majors(store, 's')] == ['m']


def test_plain_store_selection_rejects_disabled_and_mismatched_relationships():
    store = FakeCatalogStore()
    selection = validate_selection(store, 's', 'c', 'm')
    assert (selection.school_id, selection.school_name, selection.college_id,
            selection.college_name, selection.major_id, selection.major_name) == (
        's', '中南大学', 'c', 'c', 'm', 'm')
    for ids, code in [
        (('missing', 'c', 'm'), 'school_not_supported'),
        (('off', 'c', 'm'), 'school_not_supported'),
        (('s', 'off-c', 'hidden-parent'), 'college_not_available'),
        (('s', 'foreign-c', 'wrong-parent'), 'college_not_available'),
        (('s', 'c', 'off-m'), 'major_not_available'),
        (('s', 'c', 'hidden-parent'), 'major_not_available'),
        (('s', 'c', 'missing'), 'major_not_available'),
    ]:
        with pytest.raises(AppError) as error:
            validate_selection(store, *ids)
        assert error.value.code == code
