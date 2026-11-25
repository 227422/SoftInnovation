"""Followed notices are the same read model as the feed, filtered by account stars."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from campus_backend.auth.dependencies import Principal, require_mutation, require_user
from campus_backend.core.errors import AppError
from campus_backend.notices.ports import NoticeStore
from campus_backend.notices.service import list_notices, public_page
from campus_backend.profile.ports import ProfileStore
from campus_backend.providers import get_follow_store, get_notice_store, get_profile_store

from .persistence.repository import SQLAlchemyFollowStore, empty_view
from .schemas import FollowUpdate, FollowView

router = APIRouter(prefix='/v1/me', tags=['follows'])


@router.get('/follows')
def my_follows(request: Request, principal: Annotated[Principal, Depends(require_user)],
               notices: Annotated[NoticeStore, Depends(get_notice_store)],
               profiles: Annotated[ProfileStore, Depends(get_profile_store)],
               follows: Annotated[SQLAlchemyFollowStore, Depends(get_follow_store)],
               offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=100)] = 50):
    starred = set(follows.starred_ids(principal.user_id))
    page = list_notices(notices, profiles.get_profile(principal.user_id), now=request.app.state.clock(),
                        offset=offset, limit=limit, only_ids=starred)
    states = follows.starred(principal.user_id, [item['notice_id'] for item in page['items']])
    for item in page['items']:
        item['follow'] = states.get(item['notice_id']) or empty_view(item['notice_id'], version=1)
    return public_page(page)


@router.put('/notices/{notice_id}/follow', response_model=FollowView)
def set_follow(notice_id: str, payload: FollowUpdate, request: Request,
               principal: Annotated[Principal, Depends(require_mutation)],
               notices: Annotated[NoticeStore, Depends(get_notice_store)],
               follows: Annotated[SQLAlchemyFollowStore, Depends(get_follow_store)]):
    row = notices.get(notice_id)
    if row is None:
        raise AppError(404, 'notice_not_found', '未找到该通知')
    view = follows.set(principal.user_id, notice_id, payload.starred, payload.expected_version,
                       request.app.state.clock().timestamp())
    if view is None:
        raise AppError(409, 'version_conflict', '关注状态已在其他设备更新，请刷新后重试')
    return view
