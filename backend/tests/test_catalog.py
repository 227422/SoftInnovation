"""Catalog boundary tests; the second school is a fictional fixture only."""
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from campus_backend.catalog.models import School, College, Major
from campus_backend.catalog.persistence.repository import SQLAlchemyCatalogStore
from campus_backend.core.storage import StorageError
from campus_backend.core.db import Base
from campus_backend.core.errors import AppError
from campus_backend.catalog.service import (
    list_schools, list_colleges, list_majors, list_school_majors, validate_selection,
)
from campus_backend.catalog.seed import seed_catalog, load_seed


@pytest.fixture
def catalog_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            School(id='s1', name='中南大学'),
            School(id='s2', name='测试第二学校'),
            School(id='s3', name='中停用学校', enabled=False),
            School(id='s4', name='中%字面学校'),
            College(id='c1', school_id='s1', name='计算机学院'),
            College(id='c2', school_id='s1', name='法学院'),
            College(id='c3', school_id='s2', name='虚构学院'),
            College(id='c4', school_id='s1', name='停用学院', enabled=False),
            Major(id='m1', school_id='s1', college_id='c1', name='计算机科学与技术'),
            Major(id='m2', school_id='s1', college_id='c2', name='法学'),
            Major(id='m3', school_id='s2', college_id='c3', name='虚构专业'),
            Major(id='m4', school_id='s1', college_id='c1', name='停用专业', enabled=False),
        ])
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def catalog_store(catalog_db):
    return SQLAlchemyCatalogStore(catalog_db)


def test_prefix_is_official_literal_and_enabled(catalog_store):
    assert [s['name'] for s in list_schools(catalog_store, '中')] == ['中%字面学校', '中南大学']
    assert list_schools(catalog_store, '南') == []
    assert list_schools(catalog_store, '%') == []
    assert list_schools(catalog_store, '_') == []
    assert [s['name'] for s in list_schools(catalog_store, '中%')] == ['中%字面学校']


def test_empty_catalog_is_success_and_invalid_parents_are_errors(catalog_store):
    assert list_colleges(catalog_store, 's4') == []
    assert list_majors(catalog_store, 's1', 'c2')[0]['name'] == '法学'
    for school_id, college_id in [('unknown', 'c1'), ('s1', 'c3'), ('s1', 'c4')]:
        with pytest.raises(AppError):
            list_majors(catalog_store, school_id, college_id)
    with pytest.raises(AppError):
        list_colleges(catalog_store, 's3')


def test_valid_selection_uses_canonical_names_and_all_relationships(catalog_store):
    selection = validate_selection(catalog_store, 's1', 'c1', 'm1')
    assert (selection.school_name, selection.college_name, selection.major_name) == (
        '中南大学', '计算机学院', '计算机科学与技术')
    for ids in [('bad', 'c1', 'm1'), ('s1', 'c3', 'm3'), ('s1', 'c1', 'm2'),
                ('s1', 'c1', 'm4'), ('s1', 'c1', 'bad'), ('s3', 'c1', 'm1')]:
        with pytest.raises(AppError):
            validate_selection(catalog_store, *ids)
    assert {m['id'] for m in list_school_majors(catalog_store, 's1')} == {'m1', 'm2'}


def test_seed_is_complete_offline_and_idempotent(catalog_db, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # Package seed must not depend on the launch directory.
    seed = load_seed()
    assert seed['source']['content_version'] == '2026年8月'
    assert seed['source']['checked_on'] == '2026-10-30'
    assert seed['school']['name'] == '中南大学'
    assert len(seed['colleges']) == 31
    assert len(seed['majors']) == 101
    assert len({m['id'] for m in seed['majors']}) == 101
    assert sum('停止招生' in m['notes'] for m in seed['majors']) == 12
    seed_catalog(catalog_db)
    counts = [catalog_db.scalar(select(func.count()).select_from(m)) for m in (School, College, Major)]
    seed_catalog(catalog_db)
    assert counts == [catalog_db.scalar(select(func.count()).select_from(m)) for m in (School, College, Major)]
    csu = catalog_db.get(School, seed['school']['id'])
    assert csu.source_version == '2026年8月'
    assert all(m['enabled'] for m in seed['majors'] if '停止招生' in m['notes'])
    clinical = [m for m in seed['majors'] if m['code'] == '100201K']
    assert {m['duration'] for m in clinical} == {'五年', '八年'}


def test_http_directory_returns_source_empty_messages_and_clear_404(client, db):
    schools = client.get('/v1/catalog/schools', params={'prefix': '中'}).json()
    assert len(schools['items']) == 1
    school = schools['items'][0]
    assert school['name'] == '中南大学'
    assert school['source']['content_version'] == '2026年8月'
    assert '停止招生' in school['coverage']
    for prefix in ('南', '%', '_'):
        response = client.get('/v1/catalog/schools', params={'prefix': prefix})
        assert response.status_code == 200
        assert response.json() == {'items': [], 'message': '暂未支持该学校，请重新选择'}
    colleges = client.get(f"/v1/catalog/schools/{school['id']}/colleges").json()['items']
    assert len(colleges) == 31
    computer = next(c for c in colleges if c['name'] == '计算机学院')
    # Selecting a college loads its full options without any typed search input.
    majors = client.get(f"/v1/catalog/schools/{school['id']}/colleges/{computer['id']}/majors").json()['items']
    assert len(majors) == 5
    assert any(m['name'] == '物联网工程' and m['notes'] == '停止招生' for m in majors)
    assert client.get('/v1/catalog/schools/missing/colleges').status_code == 404
    assert client.get('/v1/catalog/schools/csu/colleges/missing/majors').status_code == 404
    db.add(School(id='fictional-empty', name='虚构空学校'))
    db.flush()
    db.add(College(id='fictional-empty-college', school_id='fictional-empty', name='虚构空学院'))
    db.commit()
    empty = client.get('/v1/catalog/schools/fictional-empty/colleges/fictional-empty-college/majors')
    assert empty.json() == {'items': [], 'message': '该学院暂未配置可选专业'}
    grades = client.get('/v1/catalog/grades').json()['items']
    assert [g['value'] for g in grades] == list(range(1, 9))


def test_http_catalog_database_failure_is_503_not_empty(app, client):
    from sqlalchemy.exc import OperationalError
    from campus_backend.core.db import get_db

    class BrokenSession:
        def scalars(self, *args, **kwargs):
            raise OperationalError('sensitive-private-query', {}, Exception('private-db-error'))

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get('/v1/catalog/schools', params={'prefix': '中'})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'storage_unavailable'
    assert 'items' not in response.json()
    assert 'private' not in response.text
    assert '暂未支持' not in response.text


def test_seed_failure_rolls_back_prior_flushed_rows(catalog_db, monkeypatch):
    from sqlalchemy.exc import OperationalError
    flush = catalog_db.flush
    calls = 0

    def fail_second_flush(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OperationalError('injected seed failure', {}, Exception('offline'))
        return flush(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(catalog_db, 'flush', fail_second_flush)
        with pytest.raises(StorageError):
            seed_catalog(catalog_db)
    assert catalog_db.get(School, 'csu') is None
    assert catalog_db.get(School, 's1').name == '中南大学'


def test_adapter_returns_detached_immutable_catalog_snapshots(catalog_db, catalog_store):
    from dataclasses import FrozenInstanceError
    from campus_backend.catalog.ports import SchoolRecord, CollegeRecord, MajorRecord

    school = catalog_store.get_school('s1')
    college = catalog_store.get_college('c1')
    major = catalog_store.get_major('m1')
    assert isinstance(school, SchoolRecord)
    assert isinstance(college, CollegeRecord)
    assert isinstance(major, MajorRecord)
    assert catalog_store.get_school('missing') is None
    assert catalog_store.get_college('missing') is None
    assert catalog_store.get_major('missing') is None
    catalog_db.get(School, 's1').name = 'changed after snapshot'
    catalog_db.commit()
    catalog_db.close()
    assert (school.name, college.school_id, major.college_id) == ('中南大学', 's1', 'c1')
    with pytest.raises(FrozenInstanceError):
        school.name = 'mutation'


@pytest.mark.parametrize('method,args', [
    ('get_school', ('s1',)), ('get_college', ('c1',)), ('get_major', ('m1',)),
    ('find_schools', ('中',)), ('find_colleges', ('s1',)),
    ('find_majors', ('s1', 'c1')), ('find_school_majors', ('s1',)),
])
def test_adapter_translates_database_errors_for_every_read(method, args):
    from sqlalchemy.exc import OperationalError

    class BrokenSession:
        def get(self, *args, **kwargs):
            raise OperationalError('private-query', {}, Exception('private-driver'))

        def scalars(self, *args, **kwargs):
            raise OperationalError('private-query', {}, Exception('private-driver'))

    with pytest.raises(StorageError) as error:
        getattr(SQLAlchemyCatalogStore(BrokenSession()), method)(*args)
    assert 'private' not in str(error.value)
