"""Application composition only; business logic lives in feature packages."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi import Depends

from .core.config import Settings
from .core.db import build_engine, make_session_factory
from .core.errors import install_error_handlers
from .core.http import install_http_middleware
from .auth.router import router as auth_router
from .catalog.router import router as catalog_router
from .profile.router import router as profile_router
from .preferences.router import router as preferences_router
from .notices.router import router as notices_router
from .follows.router import router as follows_router
from . import metadata as _metadata
from .providers import require_storage_ready


def create_app(settings: Settings | None = None, clock=None):
    settings = settings or Settings.from_env()
    engine = build_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title='校园通知后端', version='0.1.0', lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    install_error_handlers(app)
    install_http_middleware(app, settings)

    @app.get('/health/live', tags=['health'])
    def live():
        return {'status': 'ok'}

    @app.get('/health/ready', tags=['health'])
    def ready(_=Depends(require_storage_ready)):
        return {'status': 'ready'}

    app.include_router(auth_router)
    app.include_router(catalog_router)
    app.include_router(profile_router)
    app.include_router(preferences_router)
    app.include_router(notices_router)
    app.include_router(follows_router)
    return app
