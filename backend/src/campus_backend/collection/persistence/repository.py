"""SQLite durable queue. Leasing and mutations serialize inside short transactions."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import and_, case, func, or_, select
from campus_backend.core.persistence import storage_errors, write_transaction
from .models import Job,HostLimit


def stamp(now):
    return now.timestamp()


def job_record(row):
    return {key: getattr(row, key) for key in ('id', 'kind', 'source_id', 'payload', 'state', 'due_at',
                                              'lease_token', 'lease_until', 'attempts', 'last_error')}


def enqueue_in(db, job_id, kind, source_id, payload, now, repeat=False):
    job = db.get(Job, job_id)
    if job is None:
        db.add(Job(id=job_id, kind=kind, source_id=source_id, payload=payload, state='pending',
                   due_at=stamp(now), updated_at=stamp(now), attempts=0))
        return True
    if repeat and job.state == 'done':
        job.state, job.payload, job.due_at, job.updated_at = 'pending', payload, stamp(now), stamp(now)
        job.attempts, job.last_error = 0, None
        return True
    return False


def owns_lease(db, job, now):
    if job is None:
        return True
    row = db.get(Job, job['id'])
    return bool(row and row.state == 'running' and row.lease_token == job['lease_token']
                and row.lease_until is not None and row.lease_until >= stamp(now))


class SQLAlchemyJobStore:
    def __init__(self, factory):
        self.factory = factory

    def enqueue(self, job_id, kind, source_id, payload, now, *, repeat=False, parent=None):
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db,parent,now):
                return False
            return enqueue_in(db, job_id, kind, source_id, payload, now, repeat)

    def claim(self, now, lease_seconds=600, kinds=None, source_ids=None):
        with self.factory() as db, write_transaction(db):
            eligible = or_(and_(Job.state == 'pending', Job.due_at <= stamp(now)),
                           and_(Job.state == 'running', Job.lease_until < stamp(now)))
            stmt = select(Job).where(eligible)
            if kinds:
                stmt = stmt.where(Job.kind.in_(kinds))
            if source_ids:
                stmt = stmt.where(Job.source_id.in_(source_ids))
            row = db.scalar(stmt.order_by(case((Job.kind == 'source', 0), (Job.due_at <= stamp(now)-300,1),
                                               (Job.kind == 'document', 2), (Job.kind == 'detail', 3), else_=4),
                                           Job.due_at, Job.id).limit(1))
            if row is None:
                return None
            row.state, row.lease_token = 'running', uuid4().hex
            # At most 30 downloads, each bounded to 60s; OCR has a separate 300s ceiling.
            duration=max(lease_seconds,2400) if row.kind=='detail' else lease_seconds
            row.lease_until, row.updated_at = stamp(now) + duration, stamp(now)
            row.attempts += 1
            return job_record(row)

    def finish(self, job, now):
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Job, job['id'])
            row.state, row.lease_token, row.lease_until = 'done', None, None
            row.updated_at, row.last_error = stamp(now), None
            return True

    def retry(self, job, now, *, delay=30, error='retry'):
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Job, job['id'])
            row.state, row.lease_token, row.lease_until = 'pending', None, None
            row.due_at, row.updated_at, row.last_error = stamp(now) + delay, stamp(now), error[:1000]
            return True

    def counts(self):
        with self.factory() as db, storage_errors():
            result = {state: 0 for state in ('pending', 'running', 'done')}
            result.update(dict(db.execute(select(Job.state, func.count()).group_by(Job.state)).all()))
            return result

    def list_jobs(self, *, limit=100):
        with self.factory() as db, storage_errors():
            return [job_record(row) for row in db.scalars(select(Job).order_by(Job.updated_at.desc()).limit(limit))]

    def get_host_backoff(self,host):
        with self.factory() as db,storage_errors():
            row=db.get(HostLimit,host)
            return {'until':row.retry_at,'code':row.code} if row else None

    def history_pending(self,source_id,exclude_id):
        with self.factory() as db,storage_errors():
            return bool(db.scalar(select(Job.id).where(Job.source_id==source_id,Job.kind=='history',
                Job.state.in_(('pending','running')),Job.id!=exclude_id).limit(1)))

    def set_host_backoff(self,host,until,code):
        with self.factory() as db,write_transaction(db):
            row=db.get(HostLimit,host)
            if row is None:
                db.add(HostLimit(host=host,retry_at=until,code=code))
            elif until>row.retry_at:
                row.retry_at,row.code=until,code
