"""Authenticated preference reads and CSRF-protected writes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from campus_backend.auth.dependencies import Principal, require_mutation, require_user
from campus_backend.catalog.preferences import PreferencesCatalog, load_preferences_catalog
from campus_backend.providers import get_preferences_store

from .ports import PreferencesStore
from .schemas import PreferencesUpdate, PreferencesView
from .service import get_preferences, save_preferences

router = APIRouter(prefix="/v1/me/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesView)
def read_preferences(
    principal: Annotated[Principal, Depends(require_user)],
    store: Annotated[PreferencesStore, Depends(get_preferences_store)],
):
    return get_preferences(store, principal.user_id)


@router.patch("", response_model=PreferencesView)
def update_preferences(
    payload: PreferencesUpdate,
    principal: Annotated[Principal, Depends(require_mutation)],
    store: Annotated[PreferencesStore, Depends(get_preferences_store)],
    catalog: Annotated[PreferencesCatalog, Depends(load_preferences_catalog)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
):
    return save_preferences(store, catalog, principal.user_id, payload, idempotency_key)
