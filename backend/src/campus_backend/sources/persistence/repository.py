from datetime import datetime, timezone
from sqlalchemy import select
from campus_backend.core.persistence import storage_errors, write_transaction
from campus_backend.collection.persistence.repository import enqueue_in, owns_lease, stamp
from .models import Source


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def record(row):
    return dict(row.config) | {'state': row.status, 'last_attempt_at': iso(row.last_attempt_at),
        'last_success_at': iso(row.last_success_at), 'next_check_at': iso(row.next_check_at),
        'last_error': row.last_error, 'checks': row.checks, 'history_status': row.history_status}


class SQLAlchemySourceStore:
    def __init__(self, factory):
        self.factory = factory

    def sync(self, sources, now):
        with self.factory() as db, write_transaction(db):
            ids = {source['source_id'] for source in sources}
            for existing in db.scalars(select(Source)):
                if existing.source_id not in ids:
                    existing.config = existing.config | {'status': 'disabled'}
                    existing.status = 'disabled'
            for config in sources:
                row = db.get(Source, config['source_id'])
                if row is None:
                    db.add(Source(source_id=config['source_id'], school_id=config.get('school_id','csu'), config=config,
                                  status='pending' if config['status']=='enabled' else config['status'], next_check_at=0))
                else:
                    row.config = config
                    if config['status'] != 'enabled':
                        row.status = config['status']

    def list(self, school_id=None):
        with self.factory() as db, storage_errors():
            stmt = select(Source).order_by(Source.source_id)
            if school_id:
                stmt = stmt.where(Source.school_id == school_id)
            return [record(row) for row in db.scalars(stmt)]

    def get(self, source_id):
        with self.factory() as db, storage_errors():
            row = db.get(Source, source_id)
            return record(row) if row else None

    def schedule(self, now, interval=1200, source_ids=None, force=False):
        with self.factory() as db, write_transaction(db):
            stmt = select(Source)
            if source_ids:
                stmt = stmt.where(Source.source_id.in_(source_ids))
            if not force:
                stmt = stmt.where(Source.next_check_at <= stamp(now))
            count = 0
            for row in db.scalars(stmt):
                if row.config.get('status') != 'enabled':
                    continue
                if enqueue_in(db, f'source:{row.source_id}', 'source', row.source_id,
                              {'url': row.config['url']}, now, repeat=True):
                    row.next_check_at = stamp(now) + interval
                    count += 1
            return count

    def update_status(self, source_id, now, *, status, error=None, success=False, history_status=None, job=None):
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Source, source_id)
            if row is None:
                return False
            row.status, row.last_error, row.last_attempt_at = status, error, stamp(now)
            if success:
                row.last_success_at, row.checks = stamp(now), row.checks + 1
            if history_status:
                row.history_status = history_status
            return True
