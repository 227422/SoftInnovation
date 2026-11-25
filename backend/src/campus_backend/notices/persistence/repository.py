"""Atomic source snapshot + downstream job writes; old results cannot become current."""
from datetime import datetime, timezone
from sqlalchemy import select
from campus_backend.classification.collected_facts import (
    validate_collected_raw_reference,
    validate_collected_rule_facts,
)
from campus_backend.core.artifacts import validate_artifact
from campus_backend.core.persistence import storage_errors, write_transaction
from campus_backend.collection.persistence.repository import enqueue_in, owns_lease, stamp
from .models import Notice, NoticeSource, NoticeVersion


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


class SQLAlchemyNoticeStore:
    def __init__(self, factory):
        self.factory = factory

    def save_raw(self, raw, now, *, job=None):
        validate_artifact(raw, 'raw')
        key, version, payload = raw['notice_id'], raw['content_version'], raw['payload']
        fetch_started = datetime.fromisoformat(raw['created_at']).timestamp()
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Notice, key)
            if row is None:
                row = Notice(id=key, school_id=payload.get('school_id','csu'), source_id=payload['source_id'],
                             source_url=payload['source_url'], title=payload['title'], first_seen_at=stamp(now),
                             last_seen_at=stamp(now), latest_version=version, fetch_status='processing')
                db.add(row)
                db.flush()
            row.last_seen_at = stamp(now)
            if db.get(NoticeSource, (key, payload['source_id'])) is None:
                db.add(NoticeSource(notice_id=key, source_id=payload['source_id']))
            if row.last_fetch_started_at is not None and fetch_started < row.last_fetch_started_at:
                return False
            prior = db.get(NoticeVersion, (key, version))
            if prior is not None and row.latest_version == version:
                row.last_fetch_started_at = fetch_started
                if row.current_version == version and prior.document:
                    row.fetch_status = prior.document['payload'].get('body_status','title_only')
                    row.fetch_error = None
                    row.last_success_at = stamp(now)
                return False
            # A transient fetch/parse failure must not replace a successful body.
            if payload.get('body_status') == 'title_only' and row.current_version:
                current = db.get(NoticeVersion, (key, row.current_version))
                if current and current.document and current.document['payload'].get('content'):
                    row.fetch_status, row.fetch_error = 'stale', payload.get('access_reason','正文暂不可读')
                    return False
            if payload.get('body_status') == 'title_only':
                pending=db.get(NoticeVersion,(key,row.latest_version))
                if pending and pending.raw['payload'].get('body_status') in ('full','partial') and (
                        pending.raw['payload'].get('html') or pending.raw['payload'].get('assets')):
                    row.fetch_status,row.fetch_error='stale',payload.get('access_reason','新一次读取失败，保留已取得原件')
                    return False
            if prior is None:
                db.add(NoticeVersion(notice_id=key, content_version=version, raw=raw, created_at=stamp(now)))
            row.latest_version, row.fetch_status, row.fetch_error = version, 'processing', None
            row.last_fetch_started_at = fetch_started
            enqueue_in(db, f'document:{key}:{version}', 'document', payload['source_id'],
                       {'notice_id':key,'content_version':version}, now, repeat=True)
            return True

    def publish(self, document, analysis, now, *, job=None):
        validate_artifact(document, 'document')
        validate_artifact(analysis, 'analysis')
        notice_id, content_version = document['notice_id'], document['content_version']
        if (notice_id, content_version) != (analysis['notice_id'], analysis['content_version']):
            raise ValueError('Analysis and document versions differ')
        facts = validate_collected_rule_facts(document, analysis, require_current_method=True)
        if facts is not None and job is not None and (
            job['id'] != f'document:{notice_id}:{content_version}' or job['kind'] != 'document'
        ):
            return False
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Notice, notice_id)
            if row is None or row.latest_version != content_version:
                return False
            version = db.get(NoticeVersion, (row.id, row.latest_version))
            if facts is not None:
                validate_collected_raw_reference(document, version.raw)
            if row.current_version:
                previous = db.get(NoticeVersion, (row.id, row.current_version))
                previous_body = previous.document['payload'] if previous.document else {}
                next_body = document['payload']
                if (previous_body.get('content') and not next_body.get('content')) or (
                        previous_body.get('body_status') in ('full','complete') and next_body.get('body_status') in ('partial','title_only')):
                    row.fetch_status, row.fetch_error = 'stale', '新版本提取失败，保留上次成功正文'
                    return False
                if previous_body.get('content') and next_body.get('body_status') in ('partial','title_only'):
                    old_text={s.get('text','') for s in previous_body.get('segments',[]) if s.get('text')}
                    new_text={s.get('text','') for s in next_body.get('segments',[]) if s.get('text')}
                    preserved=(old_text<=new_text) if old_text else previous_body['content'] in next_body.get('content','')
                    if not preserved:
                        row.fetch_status,row.fetch_error='stale','部分文件暂不可读，保留上一版本成功内容；新版本待核对'
                        return False
            version.document, version.analysis, version.processed_at = document, analysis, stamp(now)
            row.current_version, row.title = row.latest_version, version.raw['payload']['title']
            row.fetch_status, row.fetch_error = document['payload'].get('body_status','title_only'), None
            row.last_success_at = stamp(now)
            if row.admitted_at is None and analysis['payload'].get('lifecycle',{}).get('admitted'):
                row.admitted_at = stamp(now)
            return True

    def record_failure(self, notice_id, code, message, now, *, job=None, fetch_started_at=None, expected_version=None):
        with self.factory() as db, write_transaction(db):
            if not owns_lease(db, job, now):
                return False
            row = db.get(Notice, notice_id)
            if row and expected_version is not None and row.latest_version!=expected_version:
                return False
            if row and fetch_started_at is not None and row.last_fetch_started_at is not None and stamp(fetch_started_at)<row.last_fetch_started_at:
                return False
            if row:
                row.fetch_status, row.fetch_error = code, message
            return bool(row)

    def raw(self, notice_id, content_version):
        with self.factory() as db, storage_errors():
            row = db.get(NoticeVersion, (notice_id, content_version))
            return row.raw if row else None

    def _record(self, db, row):
        current = db.get(NoticeVersion, (row.id, row.current_version or row.latest_version))
        return {'notice_id':row.id, 'school_id':row.school_id, 'source_id':row.source_id,
                'source_ids':list(db.scalars(select(NoticeSource.source_id).where(NoticeSource.notice_id==row.id))),
                'source_url':row.source_url, 'title':row.title, 'first_seen_at':iso(row.first_seen_at),
                'last_seen_at':iso(row.last_seen_at), 'last_success_at':iso(row.last_success_at),
                'admitted_at':iso(row.admitted_at),
                'latest_version':row.latest_version, 'current_version':row.current_version,
                'fetch_status':row.fetch_status, 'fetch_error':row.fetch_error,
                'raw':current.raw if current else None, 'document':current.document if current else None,
                'analysis':current.analysis if current else None}

    def get(self, notice_id):
        with self.factory() as db, storage_errors():
            row = db.get(Notice, notice_id)
            return self._record(db,row) if row else None

    def list(self, school_id='csu', *, limit=None):
        with self.factory() as db, storage_errors():
            stmt = select(Notice).where(Notice.school_id==school_id).order_by(Notice.last_seen_at.desc(),Notice.id)
            if limit is not None:
                stmt = stmt.limit(limit)
            rows = db.scalars(stmt)
            return [self._record(db,row) for row in rows]

    def refresh_candidates(self, source_id):
        with self.factory() as db, storage_errors():
            rows=db.scalars(select(Notice).join(NoticeSource,NoticeSource.notice_id==Notice.id).where(NoticeSource.source_id==source_id))
            result=[]
            for row in rows:
                version=db.get(NoticeVersion,(row.id,row.current_version or row.latest_version))
                analysis=version.analysis['payload'] if version and version.analysis else {}
                if analysis.get('lifecycle',{}).get('admitted') is False:
                    continue
                result.append({'title':row.title,'url':row.source_url,
                               'published_at':version.raw['payload'].get('published_at') if version else None})
            return result
