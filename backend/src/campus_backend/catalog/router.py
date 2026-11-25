from typing import Annotated

from fastapi import APIRouter, Depends, Query

from campus_backend.providers import get_catalog_store
from .ports import CatalogStore
from .preferences import (
    PreferenceKind, PreferenceOptions, PreferencesCatalog, list_preferences_options, load_preferences_catalog,
)
from .schemas import CatalogItems, CollegeItem, GradeItems, MajorItem, SchoolItem
from .service import list_schools, list_colleges, list_majors, list_school_majors

router = APIRouter(prefix='/v1/catalog', tags=['catalog'])


def _items(items: list[dict], empty_message: str) -> dict:
    return {'items': items, 'message': None if items else empty_message}


@router.get('/schools', response_model=CatalogItems[SchoolItem])
def schools(prefix: str = Query('', max_length=200), store: CatalogStore = Depends(get_catalog_store)):
    return _items(list_schools(store, prefix), '暂未支持该学校，请重新选择')


@router.get('/schools/{school_id}/colleges', response_model=CatalogItems[CollegeItem])
def colleges(school_id: str, store: CatalogStore = Depends(get_catalog_store)):
    return _items(list_colleges(store, school_id), '该学校暂未配置学院数据')


@router.get('/schools/{school_id}/colleges/{college_id}/majors', response_model=CatalogItems[MajorItem])
def majors(school_id: str, college_id: str, store: CatalogStore = Depends(get_catalog_store)):
    return _items(list_majors(store, school_id, college_id), '该学院暂未配置可选专业')


@router.get('/grades', response_model=GradeItems)
def grades():
    return {'items': [{'value': grade, 'label': f'{grade}年级'} for grade in range(1, 9)]}


@router.get('/preferences', response_model=PreferenceOptions)
def preferences(kind: PreferenceKind, catalog: Annotated[PreferencesCatalog, Depends(load_preferences_catalog)]):
    return list_preferences_options(catalog, kind)
