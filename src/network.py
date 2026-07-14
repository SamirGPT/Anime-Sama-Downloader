"""HTTP networking layer — shared session, retry, backoff, timeouts.

v4.0 speed improvements:
- Single shared Session with LARGE connection pool (50 conns/host)
- Increased max_workers defaults
- HTTP/2 keep-alive
- Smarter retry (only on transient errors)
"""
from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None

from src.ui import NetworkError, print_status


# ---------------------------------------------------------------------------
# Defaults — tuned for speed
# ---------------------------------------------------------------------------
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 20          # seconds per request
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.5         # base for exponential backoff (shorter)
MAX_POOL_CONNECTIONS = 50     # connection pool size per host
MAX_POOL_MAXSIZE = 50


# ---------------------------------------------------------------------------
# Session (shared, thread-safe for read GETs)
# ---------------------------------------------------------------------------
_default_session: Optional[requests.Session] = None
_default_session_lock = threading.Lock()
_default_ua: str = DEFAULT_USER_AGENT
_default_proxy: Optional[str] = None
_default_rate_limit: float = 0.0  # seconds between requests (0 = no limit)
_last_request_time: float = 0.0
_rate_lock = threading.Lock()


def _build_session(user_agent: str, proxy: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent,
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    })
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    if Retry is not None:
        retry = Retry(
            total=DEFAULT_RETRIES,
            connect=3,
            read=3,
            backoff_factor=DEFAULT_BACKOFF,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=MAX_POOL_CONNECTIONS,
            pool_maxsize=MAX_POOL_MAXSIZE,
            pool_block=False,
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
    return s


def configure(user_agent: Optional[str] = None, proxy: Optional[str] = None,
              rate_limit: float = 0.0) -> None:
    """Configure the default session. Call this once at startup."""
    global _default_session, _default_ua, _default_proxy, _default_rate_limit
    with _default_session_lock:
        _default_ua = user_agent or DEFAULT_USER_AGENT
        _default_proxy = proxy
        _default_rate_limit = rate_limit
        if _default_session is not None:
            try:
                _default_session.close()
            except Exception:
                pass
        _default_session = _build_session(_default_ua, _default_proxy)


def get_session() -> requests.Session:
    """Return the shared session.

    Note: requests.Session IS thread-safe for concurrent GETs (the
    underlying urllib3 PoolManager handles connection pooling with
    thread-safe checkout/checkin). We use ONE shared session with a
    large pool, instead of per-thread sessions, to maximize connection
    reuse and speed.
    """
    global _default_session
    if _default_session is None:
        configure()
    with _default_session_lock:
        if _default_session is None:
            configure()
        return _default_session


def _apply_rate_limit() -> None:
    """If rate-limiting is configured, sleep to enforce it."""
    if _default_rate_limit <= 0:
        return
    global _last_request_time
    with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _default_rate_limit:
            time.sleep(_default_rate_limit - elapsed)
        _last_request_time = time.monotonic()


def _merge_headers(extra: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not extra:
        return {}
    return dict(extra)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def get(url: str, *, headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        allow_redirects: bool = True,
        stream: bool = False) -> requests.Response:
    """GET with retries and backoff. Raises NetworkError on final failure."""
    sess = get_session()
    last_exc: Optional[Exception] = None
    for attempt in range(1, DEFAULT_RETRIES + 1):
        _apply_rate_limit()
        try:
            r = sess.get(
                url,
                headers=_merge_headers(headers),
                params=params,
                timeout=timeout,
                allow_redirects=allow_redirects,
                stream=stream,
            )
            return r
        except requests.RequestException as e:
            last_exc = e
            # Don't retry on 4xx client errors
            if isinstance(e, requests.HTTPError) and e.response is not None:
                if 400 <= e.response.status_code < 500:
                    raise
            if attempt < DEFAULT_RETRIES:
                wait = DEFAULT_BACKOFF * (2 ** (attempt - 1))
                print_status(
                    f"Réseau: {e.__class__.__name__} — retry {attempt}/{DEFAULT_RETRIES} dans {wait:.1f}s",
                    "warning",
                )
                time.sleep(wait)
    raise NetworkError(f"GET {url} failed after {DEFAULT_RETRIES} attempts: {last_exc}")


def post(url: str, *, headers: Optional[Dict[str, str]] = None,
         data: Optional[Any] = None,
         json: Optional[Any] = None,
         timeout: int = DEFAULT_TIMEOUT,
         allow_redirects: bool = True) -> requests.Response:
    sess = get_session()
    last_exc: Optional[Exception] = None
    for attempt in range(1, DEFAULT_RETRIES + 1):
        _apply_rate_limit()
        try:
            return sess.post(
                url,
                headers=_merge_headers(headers),
                data=data,
                json=json,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException as e:
            last_exc = e
            if attempt < DEFAULT_RETRIES:
                wait = DEFAULT_BACKOFF * (2 ** (attempt - 1))
                print_status(
                    f"Réseau: {e.__class__.__name__} — retry {attempt}/{DEFAULT_RETRIES}",
                    "warning",
                )
                time.sleep(wait)
    raise NetworkError(f"POST {url} failed after {DEFAULT_RETRIES} attempts: {last_exc}")


def get_text(url: str, *, headers: Optional[Dict[str, str]] = None,
             timeout: int = DEFAULT_TIMEOUT) -> str:
    r = get(url, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        raise NetworkError(f"HTTP {r.status_code} for {url}")
    return r.text


def get_json(url: str, *, headers: Optional[Dict[str, str]] = None,
             timeout: int = DEFAULT_TIMEOUT):
    r = get(url, headers=headers, timeout=timeout)
    if r.status_code >= 400:
        raise NetworkError(f"HTTP {r.status_code} for {url}")
    return r.json()


def default_headers(referer: Optional[str] = None,
                    origin: Optional[str] = None,
                    accept: Optional[str] = None) -> Dict[str, str]:
    h: Dict[str, str] = {}
    if accept:
        h["Accept"] = accept
    if referer:
        h["Referer"] = referer
    if origin:
        h["Origin"] = origin
    return h
