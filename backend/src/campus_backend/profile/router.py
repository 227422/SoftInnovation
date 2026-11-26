"""Protected routes; account identity comes exclusively from the session."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from campus_backend.auth.dependencies import Principal, require_mutation, require_user
from campus_backend.providers import get_profile_store

from .ports import ProfileStore
from .schemas import ProfileResponse, ProfileUpdate
from .service import get_profile, save_profile

router = APIRouter(prefix="/v1/me/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse)
def read_profile(principal: Annotated[Principal, Depends(require_user)],
                 store: Annotated[ProfileStore, Depends(get_profile_store)]):
    return get_profile(store, principal.user_id)


@router.patch("", response_model=ProfileResponse)
def update_profile(payload: ProfileUpdate,
                   principal: Annotated[Principal, Depends(require_mutation)],
                   store: Annotated[ProfileStore, Depends(get_profile_store)],
                   idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]):
    return save_profile(store, principal.user_id, payload, idempotency_key)
