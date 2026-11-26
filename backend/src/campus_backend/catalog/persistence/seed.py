"""Offline reviewed seed import. No network access at startup or import."""
import json
from importlib.resources import files

from sqlalchemy.orm import Session

from campus_backend.core.persistence import storage_errors

from .models import School, College, Major


def load_seed() -> dict:
    return json.loads(files('campus_backend.catalog').joinpath('data/csu.json').read_text(encoding='utf-8'))


def seed_catalog(db: Session) -> None:
    """Upsert the reviewed source, atomically; stable IDs preserve profile references."""
    seed = load_seed()
    source = seed['source']
    school = {**seed['school'], 'source_url': source['url'],
              'source_version': source['content_version'],
              'source_checked_on': source['checked_on'], 'coverage': source['scope']}
    with storage_errors():
        try:
            for model, items in ((School, [school]), (College, seed['colleges']), (Major, seed['majors'])):
                for item in items:
                    current = db.get(model, item['id'])
                    if current is None:
                        db.add(model(**item))
                    else:
                        for key, value in item.items():
                            setattr(current, key, value)
                db.flush()
            db.commit()
        except Exception:
            db.rollback()
            raise
