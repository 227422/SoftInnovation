"""Browser transport safeguards shared by feature routers."""
import uuid

from starlette.middleware.cors import CORSMiddleware

from .errors import error_response
from .body_limit import BodyLimitMiddleware


def install_http_middleware(app, settings):
    app.add_middleware(BodyLimitMiddleware, max_bytes=65536)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=True,
                       allow_methods=['GET', 'POST', 'PATCH'],
                       allow_headers=['Content-Type', 'X-CSRF-Token', 'Idempotency-Key'])

    @app.middleware('http')
    async def transport(request, call_next):
        request.state.request_id = uuid.uuid4().hex
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            origin = request.headers.get('origin')
            if origin is not None and origin not in settings.allowed_origins:
                return error_response(request, 403, 'origin_forbidden', '不允许从此来源提交请求')
            if request.url.path in ('/v1/auth/register', '/v1/auth/login', '/v1/me/profile', '/v1/me/preferences'):
                if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                    return error_response(request, 415, 'json_required', '请使用JSON提交数据')
            length = request.headers.get('content-length')
            if length and (not length.isdigit() or int(length) > 65536):
                return error_response(request, 413, 'payload_too_large', '提交内容过大')
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path.startswith('/v1/'):
            response.headers['Cache-Control'] = 'no-store'
        return response
