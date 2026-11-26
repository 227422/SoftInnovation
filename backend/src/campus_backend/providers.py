"""The single composition point for concrete storage adapters.

HTTP dependencies request a feature port; only this file chooses the concrete
database implementation. FastAPI shares get_db's Session within each request.
Imports inside providers avoid coupling feature module import order.
"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .core.db import get_db
from .core.persistence import check_ready


def get_auth_store(db: Session = Depends(get_db)):
    from .auth.persistence.repository import SQLAlchemyAuthStore
    return SQLAlchemyAuthStore(db)


def get_catalog_store(db: Session = Depends(get_db)):
    from .catalog.persistence.repository import SQLAlchemyCatalogStore
    return SQLAlchemyCatalogStore(db)


def get_profile_store(db: Session = Depends(get_db)):
    from .profile.persistence.repository import SQLAlchemyProfileStore
    return SQLAlchemyProfileStore(db)


def get_preferences_store(db: Session = Depends(get_db)):
    from .preferences.persistence.repository import SQLAlchemyPreferencesStore
    return SQLAlchemyPreferencesStore(db)


def get_follow_store(db: Session = Depends(get_db)):
    from .follows.persistence.repository import SQLAlchemyFollowStore
    return SQLAlchemyFollowStore(db)


def require_storage_ready(db: Session = Depends(get_db)):
    check_ready(db)


def get_source_store(request: Request):
    from .sources.persistence.repository import SQLAlchemySourceStore
    return SQLAlchemySourceStore(request.app.state.session_factory)


def get_notice_store(request: Request):
    from .notices.persistence.repository import SQLAlchemyNoticeStore
    return SQLAlchemyNoticeStore(request.app.state.session_factory)


def get_job_store(request: Request):
    from .collection.persistence.repository import SQLAlchemyJobStore
    return SQLAlchemyJobStore(request.app.state.session_factory)


def build_collector(settings, *, clock=None, http=None):
    from .core.db import build_engine, make_session_factory
    from .core.artifacts import AssetStore
    from .sources.persistence.repository import SQLAlchemySourceStore
    from .notices.persistence.repository import SQLAlchemyNoticeStore
    from .collection.persistence.repository import SQLAlchemyJobStore
    from .collection.http import PublicHTTPClient
    from .collection.worker import CollectorWorker
    engine=build_engine(settings.database_url)
    factory=make_session_factory(engine)
    jobs=SQLAlchemyJobStore(factory)
    worker=CollectorWorker(SQLAlchemySourceStore(factory),jobs,SQLAlchemyNoticeStore(factory),
                            AssetStore(settings.collector_data_dir/'assets'),http or PublicHTTPClient(backoff_store=jobs,clock=(lambda:clock().timestamp()) if clock else None),clock=clock)
    return worker,engine


def build_fact_worker(run_dir, *, replay=None, transport=None, clock=None):
    """Compose the standalone S2 worker and its model without an HTTP route or database."""
    import os

    from .classification.adapters.replay import ReplayModel
    from .classification.adapters.responses import (
        CONTEXT_MARGIN, INPUT_TOKEN_LIMIT, MAX_INPUT_BYTES, MAX_RESPONSE_BYTES, OUTPUT_TOKEN_LIMIT,
        PROCESS_CONCURRENCY_LIMIT,
        RESPONSES_PROTOCOL, ResponsesConfig, ResponsesModel,
    )
    from .classification.fact_worker import FactWorker
    from .classification.persistence.local_runs import LocalFactRunStore
    from .classification.run_contract import FactRunError, RunMethod

    if replay is not None:
        model = ReplayModel(replay)
        method = RunMethod(provider='synthetic-replay-1', fixture_digest=model.fingerprint, token_counts_per_call=0)
    else:
        base_url = os.environ.get('S2_RESPONSES_BASE_URL')
        model_name = os.environ.get('S2_RESPONSES_MODEL')
        context_limit = os.environ.get('S2_RESPONSES_CONTEXT_LIMIT')
        key = os.environ.get('S2_RESPONSES_API_KEY')
        if not all((base_url, model_name, context_limit, key)):
            raise FactRunError('missing_model_configuration')
        try:
            config = ResponsesConfig(base_url, model_name, int(context_limit), key)
        except ValueError:
            raise FactRunError('invalid_model_configuration') from None
        model = ResponsesModel(config, transport=transport)
        method = RunMethod(
            provider=RESPONSES_PROTOCOL, endpoint=config.base_url, model=config.model, context_limit=config.context_limit,
            input_token_limit=INPUT_TOKEN_LIMIT, output_token_limit=OUTPUT_TOKEN_LIMIT, context_margin=CONTEXT_MARGIN,
            max_prompt_bytes=MAX_INPUT_BYTES, max_response_bytes=MAX_RESPONSE_BYTES, token_counts_per_call=1,
            process_concurrency_limit=PROCESS_CONCURRENCY_LIMIT,
        )
    return FactWorker(LocalFactRunStore(run_dir), model, method, **({'clock': clock} if clock is not None else {}))
