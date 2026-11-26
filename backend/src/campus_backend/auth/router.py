from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from campus_backend.providers import get_auth_store
from .dependencies import Principal, require_mutation, require_user
from .ports import AuthStore
from .schemas import Account, Credentials, SessionView
from .service import SESSION_SECONDS, charge_attempt, login_account, logout_session, register_account


router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _view(user_id: str, email: str, expires_at: int, csrf_token: str) -> SessionView:
    return SessionView(user=Account(id=user_id, email=email), expires_at=expires_at, csrf_token=csrf_token)


def _authenticate(body: Credentials, request: Request, response: Response, store: AuthStore, action: str):
    now = request.app.state.clock()
    email = str(body.email).casefold()
    charge_attempt(store, action, email, request.client.host if request.client else "unknown", now)
    operation = register_account if action == "register" else login_account
    user, session, raw_token = operation(store, email, body.password.get_secret_value(), now)
    settings = request.app.state.settings
    response.set_cookie(
        key=settings.cookie_name, value=raw_token, max_age=SESSION_SECONDS,
        expires=datetime.fromtimestamp(session.expires_at, timezone.utc),
        path="/", secure=settings.cookie_secure, httponly=True, samesite="lax",
    )
    return _view(user.id, user.email, session.expires_at, session.csrf_token)


@router.post("/register", status_code=201, response_model=SessionView)
def register(body: Credentials, request: Request, response: Response, store: AuthStore = Depends(get_auth_store)):
    return _authenticate(body, request, response, store, "register")


@router.post("/login", response_model=SessionView)
def login(body: Credentials, request: Request, response: Response, store: AuthStore = Depends(get_auth_store)):
    return _authenticate(body, request, response, store, "login")


@router.get("/session", response_model=SessionView)
def session(principal: Principal = Depends(require_user)):
    return _view(principal.user_id, principal.email, principal.expires_at, principal.csrf_token)


@router.post("/refresh", response_model=SessionView)
def refresh(principal: Principal = Depends(require_mutation)):
    # Recovery is deliberately read-only: neither DB expiry nor cookie is renewed.
    return _view(principal.user_id, principal.email, principal.expires_at, principal.csrf_token)


@router.post("/logout", status_code=204)
def logout(request: Request, principal: Principal = Depends(require_mutation), store: AuthStore = Depends(get_auth_store)):
    logout_session(store, principal.session_id, request.app.state.clock())
    settings = request.app.state.settings
    response = Response(status_code=204)
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure,
                           httponly=True, samesite="lax")
    return response
