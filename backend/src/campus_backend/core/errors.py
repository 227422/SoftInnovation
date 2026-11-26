"""Stable, redacted errors usable by any client."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from .storage import StorageError


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


def error_response(request: Request, status: int, code: str, message: str, details=None):
    error = {'code': code, 'message': message, 'request_id': getattr(request.state, 'request_id', '')}
    if details is not None:
        error['details'] = details
    return JSONResponse({'error': error}, status_code=status, headers={'Cache-Control': 'no-store'})


def install_error_handlers(app):
    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not include Pydantic input/ctx/msg: custom validators may echo secrets.
        details = [{'field': '.'.join(str(x) for x in e['loc']), 'type': e['type']} for e in exc.errors()]
        return error_response(request, 422, 'validation_error', '输入内容不符合要求，请检查后重试', details)

    @app.exception_handler(StorageError)
    @app.exception_handler(SQLAlchemyError)
    async def storage_error(request, exc):
        return error_response(request, 503, 'storage_unavailable', '数据服务暂时不可用，请稍后重试')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, 'request_rejected', '请求无法处理')

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error_response(request, 500, 'internal_error', '服务暂时不可用，请稍后重试')
