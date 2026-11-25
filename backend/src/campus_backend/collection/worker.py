"""Small restartable scheduler. Jobs and stages use ports, never database sessions."""
import logging
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from campus_backend.classification.collected_facts import analyze_collected_document
from campus_backend.documents.service import extract_document
from campus_backend.core.storage import StorageError
from .html import decode_html, parse_list, ParseError
from .http import FetchError
from .service import CollectionService, job_id, notice_id, title_only

logger=logging.getLogger(__name__)


class CollectorWorker:
    def __init__(self,sources,jobs,notices,assets,http,*,clock=None,ocr=None):
        self.sources,self.jobs,self.notices=sources,jobs,notices
        self.assets,self.http,self.ocr=assets,http,ocr
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.collection=CollectionService(http,assets)

    def _list(self,source,job):
        url=job['payload']['url']
        if source.get('direct_article'):
            parsed={'items':[{'url':url,'title':source.get('article_title') or source.get('direct_article_title') or source['name'],'published_at':source.get('published_at')}],'next_urls':[]}
        else:
            response=self.http.get(url,source['allowed_hosts'])
            parsed=parse_list(decode_html(response),source,response['url'])
        for item in parsed['items']:
            self.jobs.enqueue(job_id('detail',source['source_id'],item['url']),'detail',source['source_id'],item,
                              self.clock(),repeat=job['kind']=='source',parent=job)
        if job['kind']=='source':
            for item in self.notices.refresh_candidates(source['source_id']):
                self.jobs.enqueue(job_id('detail',source['source_id'],item['url']),'detail',source['source_id'],item,
                                  self.clock(),repeat=True,parent=job)
        history_added=False
        for next_url in parsed['next_urls']:
            added=self.jobs.enqueue(job_id('history',source['source_id'],next_url),'history',source['source_id'],
                                    {'url':next_url},self.clock(),parent=job)
            history_added=history_added or added
        mode=source.get('history_mode')
        if mode in ('unknown','restricted'):
            history_status=mode
        elif self.jobs.history_pending(source['source_id'],job['id']):
            history_status='running'
        elif parsed['next_urls'] or job['kind']=='history' or mode in ('single_page','direct') or source.get('direct_article'):
            history_status='complete'
        else:
            history_status='unknown'
        self.sources.update_status(source['source_id'],self.clock(),status='checking' if source.get('direct_article') else 'ready',
                                   success=job['kind']=='source' and not source.get('direct_article'),
                                   history_status=history_status,job=job)

    def _detail(self,source,job):
        item=job['payload']
        job['fetch_started_at']=self.clock()
        host=urlsplit(item['url']).hostname
        if host in source.get('title_only_hosts',[]):
            raw=title_only(source,item,code='external_title_only',message='公开栏目提供外部链接，本阶段仅收录标题和官方跳转',now=job['fetch_started_at'])
        else:
            raw=self.collection.article(source,item,now=job['fetch_started_at'])
        self.notices.save_raw(raw,self.clock(),job=job)
        if source.get('direct_article'):
            self.sources.update_status(source['source_id'],self.clock(),status='ready',success=True,job=job)
        retry=next((error for error in raw.get('errors',[]) if error.get('code') in ('network_error','rate_limited','http_error')),None)
        if retry:
            self.jobs.retry(job,self.clock(),delay=30 if retry['code']=='network_error' else 300,error=f"{retry['code']}:部分附件待重试")
            return False
        return True

    def _document(self,source,job):
        current=self.notices.get(job['payload']['notice_id'])
        if current and current['latest_version']!=job['payload']['content_version']:
            return True
        raw=self.notices.raw(job['payload']['notice_id'],job['payload']['content_version'])
        if raw is None:
            raise ValueError('Document task refers to a missing original')
        document=extract_document(raw,self.assets.root,ocr=self.ocr,now=self.clock())
        analysis=analyze_collected_document(document,now=self.clock())
        published=self.notices.publish(document,analysis,self.clock(),job=job)
        if not published:
            current=self.notices.get(job['payload']['notice_id'])
            if current and current['latest_version']!=job['payload']['content_version']:
                return True
        # Empty OCR is a stable reading gap, not evidence of a transient outage.
        # Keep the partial artifact; changed originals or explicit reprocessing
        # can retry it without repeatedly spending OCR on unchanged QR images.
        transient={'ocr_unavailable','ocr_timeout','ocr_failed','document_timeout','asset_unavailable','extraction_failed'}
        if any(error.get('code') in transient for error in document.get('errors',[])):
            self.jobs.retry(job,self.clock(),delay=min(1200,60*max(1,job['attempts'])),error='document_retry:部分识别暂未完成')
            return False
        return True

    def tick(self,*,max_jobs=20,source_ids=None,schedule=True,kinds=None):
        scheduled=self.sources.schedule(self.clock(),source_ids=source_ids) if schedule else 0
        stats={'scheduled':scheduled,'processed':0,'failed':0}
        for _ in range(max_jobs):
            job=self.jobs.claim(self.clock(),kinds=kinds,source_ids=source_ids)
            if job is None:
                break
            source=self.sources.get(job['source_id'])
            try:
                if not source or source.get('status')!='enabled':
                    self.jobs.finish(job,self.clock())
                    continue
                if job.get('last_error','') and job['last_error'].startswith('network_error:'):
                    probe_url=job['payload'].get('url',source['url'])
                    self.http.probe(probe_url,source['allowed_hosts'])
                if job['kind'] in ('source','history'):
                    self._list(source,job)
                elif job['kind']=='detail':
                    if not self._detail(source,job):
                        stats['failed']+=1
                        continue
                elif job['kind']=='document':
                    if not self._document(source,job):
                        stats['failed']+=1
                        continue
                else:
                    raise ValueError('Unsupported durable job kind')
                self.jobs.finish(job,self.clock())
                stats['processed']+=1
            except (FetchError,ParseError) as exc:
                delay=30 if exc.code=='network_error' else (getattr(exc,'retry_after',None) or 300)
                if job['kind']=='detail':
                    item=job['payload']
                    started=job.get('fetch_started_at',self.clock())
                    raw=title_only(source,item,code=exc.code,message=exc.message,now=started)
                    self.notices.save_raw(raw,self.clock(),job=job)
                    self.notices.record_failure(notice_id(item['url']),exc.code,exc.message,self.clock(),job=job,fetch_started_at=started)
                    if source.get('direct_article'):
                        self.sources.update_status(source['source_id'],self.clock(),status=exc.code,error=exc.message,job=job)
                else:
                    self.sources.update_status(source['source_id'],self.clock(),status=exc.code,error=exc.message,job=job)
                self.jobs.retry(job,self.clock(),delay=delay,error=f'{exc.code}:{exc.message}')
                stats['failed']+=1
            except Exception as exc:
                # Public messages omit paths, credentials and raw exception payloads.
                logger.warning('collector task failed id=%s kind=%s error_type=%s',job['id'],job['kind'],type(exc).__name__)
                if job['kind']=='document':
                    self.notices.record_failure(job['payload']['notice_id'],'processing_error','识别暂未完成，保留上次成功结果',self.clock(),job=job,expected_version=job['payload']['content_version'])
                elif job['kind'] in ('source','history'):
                    self.sources.update_status(source['source_id'],self.clock(),status='processing_error',error='栏目处理异常，等待自动重试',job=job)
                self.jobs.retry(job,self.clock(),delay=60,error='processing_error:处理暂未完成，保留上次成功结果')
                stats['failed']+=1
        return stats

    def run_forever(self,*,stop=None,duration=None,max_jobs=10,kinds=None,schedule=True):
        began=time.monotonic()
        while not (stop and stop.is_set()):
            if duration is not None and time.monotonic()-began>=duration:
                break
            try:
                result=self.tick(max_jobs=max_jobs,kinds=kinds,schedule=schedule)
                if result['processed'] or result['failed']:
                    logger.info('collector tick %s',result)
                else:
                    time.sleep(1)
            except StorageError:
                logger.warning('collector storage unavailable; retrying in 5 seconds')
                time.sleep(5)
