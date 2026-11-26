"""Bound actual ASGI body bytes, including requests without Content-Length."""
from starlette.requests import Request

from .errors import error_response


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = 65536):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        parts, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > self.max_bytes:
                response = error_response(Request(scope), 413, 'payload_too_large', '提交内容过大')
                return await response(scope, receive, send)
            parts.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(parts)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
