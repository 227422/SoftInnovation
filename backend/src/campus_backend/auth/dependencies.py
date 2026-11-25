import secrets

from fastapi import Depends, Request

from campus_backend.core.errors import AppError
from campus_backend.providers import get_auth_store
from .ports import AuthStore, Principal
from .service import authenticate_session


def require_user(request: Request, store: AuthStore = Depends(get_auth_store)) -> Principal:
    token = request.cookies.get(request.app.state.settings.cookie_name)
    return authenticate_session(store, token, request.app.state.clock())


def require_mutation(request: Request, principal: Principal = Depends(require_user)) -> Principal:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(supplied.encode("utf-8"), principal.csrf_token.encode("utf-8")):
        raise AppError(403, "csrf_invalid", "安全校验失败，请刷新后重试")
    return principal
