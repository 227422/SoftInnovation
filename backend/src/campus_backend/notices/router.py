from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from campus_backend.auth.dependencies import Principal, require_user
from campus_backend.follows.persistence.repository import SQLAlchemyFollowStore, empty_view
from campus_backend.profile.ports import ProfileStore
from campus_backend.providers import get_follow_store, get_notice_store, get_source_store, get_profile_store
from campus_backend.sources.ports import SourceStore
from .ports import NoticeStore
from .service import get_notice, list_notices, public_detail, public_page

router=APIRouter(prefix='/v1/me/notices',tags=['notices'])


def _attach_follow(payload, follows, user_id):
    """每次读取都带上当前账号的关注状态，前端不用再单独请求。"""
    items = payload['items'] if 'items' in payload else [payload]
    states = follows.starred(user_id, [item['notice_id'] for item in items])
    for item in items:
        item['follow'] = states.get(item['notice_id']) or empty_view(item['notice_id'])
    return payload


@router.get('')
def feed(request:Request,principal:Annotated[Principal,Depends(require_user)],
         notices:Annotated[NoticeStore,Depends(get_notice_store)],profiles:Annotated[ProfileStore,Depends(get_profile_store)],
         follows:Annotated[SQLAlchemyFollowStore,Depends(get_follow_store)],
         offset:Annotated[int,Query(ge=0)]=0,limit:Annotated[int,Query(ge=1,le=100)]=50):
    page=list_notices(notices,profiles.get_profile(principal.user_id),now=request.app.state.clock(),offset=offset,limit=limit)
    return public_page(_attach_follow(page,follows,principal.user_id))


@router.get('/{notice_id}')
def detail(notice_id:str,request:Request,principal:Annotated[Principal,Depends(require_user)],
           notices:Annotated[NoticeStore,Depends(get_notice_store)],sources:Annotated[SourceStore,Depends(get_source_store)],
           follows:Annotated[SQLAlchemyFollowStore,Depends(get_follow_store)],
           profiles:Annotated[ProfileStore,Depends(get_profile_store)]):
    payload=get_notice(notices,sources,profiles.get_profile(principal.user_id),notice_id,now=request.app.state.clock())
    return public_detail(_attach_follow(payload,follows,principal.user_id))
