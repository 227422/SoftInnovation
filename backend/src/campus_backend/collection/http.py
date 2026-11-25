"""Bounded HTTP transport for audited public sources; no inherited browser sessions."""
from contextlib import contextmanager, nullcontext
import ipaddress
import math
import socket
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class FetchError(Exception):
    def __init__(self, code, message, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.retry_after = code, message, retry_after


def canonical_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))


def _origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)


def validate_url(url, allowed_hosts, *, check_dns=False):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
        port = parts.port
    except ValueError:
        raise FetchError('blocked_url', '链接格式无效') from None
    if (parts.scheme not in ('https','http') or parts.username or parts.password or port not in (None,80,443)
            or host not in {h.lower() for h in allowed_hosts}):
        raise FetchError('blocked_url', '链接不在已核验的公开来源范围内')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise FetchError('blocked_url', '不允许访问内部网络地址')
    except ValueError:
        pass
    if check_dns:
        try:
            addresses = socket.getaddrinfo(host,port or (443 if parts.scheme=='https' else 80),type=socket.SOCK_STREAM)
        except OSError:
            raise FetchError('network_error', '官网域名暂时无法解析') from None
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise FetchError('blocked_url','官网地址解析到非公开网络，未继续访问')
    return canonical_url(url)


class PublicHTTPClient:
    def __init__(self, *, transport=None, min_interval=0.4, timeout=15, backoff_store=None, clock=None):
        self.client = httpx.Client(transport=transport,timeout=httpx.Timeout(timeout,connect=10),follow_redirects=False)
        self.check_dns = transport is None
        self.min_interval = min_interval
        self._last = {}
        self._lock = threading.Lock()
        self._cooldowns = {}
        self.backoff_store = backoff_store
        self._clock = clock or time.time

    def close(self):
        self.client.close()

    def _pace(self, host):
        with self._lock:
            now = time.monotonic()
            target = max(now, self._last.get(host,0) + self.min_interval)
            self._last[host] = target
        if target > now:
            time.sleep(target-now)

    def _defer(self,host,delay,code):
        until=self._clock()+delay
        with self._lock:
            existing=self._cooldowns.get(host)
            if not existing or until>existing['until']:
                self._cooldowns[host]={'until':until,'code':code}
        if self.backoff_store:
            self.backoff_store.set_host_backoff(host,until,code)

    def _check_backoff(self,host):
        value=self.backoff_store.get_host_backoff(host) if self.backoff_store else self._cooldowns.get(host)
        if value and value['until']>self._clock():
            delay=math.ceil(value['until']-self._clock())
            raise FetchError(value['code'],'此官网正在等待重试；已有内容仍可读取',delay)

    def probe(self, url, allowed_hosts):
        return self.get(url, allowed_hosts, probe=True)

    def get(self, url, allowed_hosts, *, max_bytes=8*1024*1024, probe=False, referer=None, observe=None, host_lock=None):
        return self._request('GET', url, allowed_hosts, max_bytes=max_bytes, probe=probe,
                             referer=referer, observe=observe, host_lock=host_lock)

    def post_form(self, url, allowed_hosts, data, *, max_bytes=8*1024*1024, referer=None):
        """Read a public resource whose official endpoint requires form submission."""
        return self._request('POST', url, allowed_hosts, data=data, max_bytes=max_bytes, referer=referer)

    @contextmanager
    def _form_stream(self, method, url, *, headers, timeout, data):
        request = self.client.build_request(method, url, headers=headers, timeout=timeout,
                                            data=data if method == 'POST' else None)
        request.headers.pop('Cookie', None)
        response = self.client.send(request, stream=True)
        try:
            yield response
        finally:
            response.close()

    def _request(self, method, url, allowed_hosts, *, data=None, max_bytes, probe=False, referer=None,
                 observe=None, host_lock=None):
        form_request = method == 'POST'
        headers={'Referer':validate_url(referer,allowed_hosts)} if referer else None
        start = time.monotonic()
        for redirect in range(6):
            if time.monotonic()-start>=60:
                raise FetchError('network_error','官网读取总时限已到')
            url = validate_url(url, allowed_hosts, check_dns=self.check_dns)
            host=urlsplit(url).hostname
            try:
                with host_lock(host) if host_lock else nullcontext():
                    self._check_backoff(host)
                    self._pace(host)
                    remaining=max(1,60-(time.monotonic()-start))
                    timeout = min(15, remaining)
                    stream = (self._form_stream(method, url, timeout=timeout, headers=headers, data=data)
                              if form_request else self.client.stream('GET', url, timeout=timeout, headers=headers))
                    with stream as response:
                        audited = None
                        if observe:
                            body = bytearray()
                            truncated = False
                            try:
                                for chunk in response.iter_bytes(chunk_size=65536):
                                    room = max_bytes - len(body)
                                    body.extend(chunk[:room])
                                    if len(chunk) > room or time.monotonic() - start >= 60:
                                        truncated = True
                                        break
                            except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError, httpx.DecodingError):
                                truncated = True
                                raise
                            finally:
                                audited = {'url': url, 'status': response.status_code,
                                           'data': bytes(body), 'truncated': truncated,
                                           'media_type': response.headers.get('content-type','').split(';')[0].lower(),
                                           'encoding': response.encoding or 'utf-8',
                                           'location': response.headers.get('location')}
                                observe(audited)
                        if response.status_code in (301,302,303,307,308):
                            location = response.headers.get('location')
                            if not location:
                                raise FetchError('http_error','官网跳转缺少目标地址')
                            destination = urljoin(url, location)
                            if form_request:
                                destination = validate_url(destination, allowed_hosts)
                            if method == 'POST':
                                if response.status_code == 303:
                                    method = 'GET'
                                elif response.status_code in (301, 302):
                                    raise FetchError('blocked_url', '不自动重放含糊跳转的表单请求')
                                elif _origin(destination) != _origin(url):
                                    raise FetchError('blocked_url', '不向其他来源重发表单请求')
                            if form_request and _origin(destination) != _origin(url):
                                headers = None
                            url = destination
                            continue
                        if response.status_code == 429:
                            retry = response.headers.get('retry-after','60')
                            try:
                                seconds = max(30,int(retry))
                            except ValueError:
                                try:
                                    seconds = max(30,int((parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds()))
                                except (ValueError,TypeError):
                                    seconds = 60
                            self._defer(host,seconds,'rate_limited')
                            raise FetchError('rate_limited','官网限制访问频率，稍后重试',seconds)
                        if response.status_code in (401,403):
                            raise FetchError('access_restricted','官网限制访问或需要登录',1200)
                        if response.status_code >= 400:
                            raise FetchError('http_error',f'官网返回HTTP {response.status_code}',300)
                        if probe:
                            return {'url':url,'status':response.status_code}
                        if audited is not None:
                            if truncated:
                                raise FetchError('too_large','文件超过审计读取上限',1200)
                            return {**audited, 'headers':dict(response.headers)}
                        size = response.headers.get('content-length','')
                        if size.isdigit() and int(size)>max_bytes:
                            raise FetchError('too_large','文件超过配置的下载大小上限',1200)
                        data = bytearray()
                        for chunk in response.iter_bytes():
                            data.extend(chunk)
                            if len(data)>max_bytes:
                                raise FetchError('too_large','文件超过配置的下载大小上限',1200)
                            if time.monotonic()-start>60:
                                raise FetchError('network_error','官网读取超时')
                        content_type = response.headers.get('content-type','').split(';')[0].lower()
                        encoding = response.encoding or 'utf-8'
                        return {'url':url,'status':response.status_code,'data':bytes(data),
                                'media_type':content_type,'encoding':encoding,'headers':dict(response.headers)}
            except (httpx.TimeoutException,httpx.NetworkError,httpx.ProtocolError,httpx.DecodingError):
                self._defer(host,30,'network_error')
                raise FetchError('network_error','暂时无法连接官网，将自动重试') from None
        raise FetchError('redirect_loop','官网跳转次数过多',300)
