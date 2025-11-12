"""
Shared HTTP session + cache + timeouts for all services.

Implements:
- get_session(): thread-local requests.Session with retry + pooling
- reset_session_pool(): rebuild session on next use
- timed_get(): (connect, read) timeouts with total wall-clock budget

Derived from Ahab HTTP implementation (2025-10-08) without behavior changes.
"""

from __future__ import annotations
import os
import threading
import queue
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def _parse_timeout_env(env_name: str = "HTTP_TIMEOUT", default: str = "10,45,90") -> Tuple[float, float, float]:
    raw = (os.getenv(env_name) or default).strip()
    try:
        if "," in raw:
            parts = [p.strip() for p in raw.split(",")]
            if len(parts) != 3:
                raise ValueError("Expected 3 comma-separated values")
            ct, rt, tt = (float(parts[0]), float(parts[1]), float(parts[2]))
            ct = max(0.1, ct)
            rt = max(0.5, rt)
            tt = max(rt, tt)
            return ct, rt, tt
        else:
            v = float(raw)
            v = max(0.5, v)
            return v, v, max(30.0, 2.0 * v)
    except Exception:
        return 10.0, 45.0, 90.0


def _env_float(name: str, default: str) -> float:
    try:
        return float(str(os.getenv(name, default)).strip().strip('"').strip("'"))
    except Exception:
        return float(default)


def _env_csv_ints(name: str, default: str) -> set[int]:
    raw = str(os.getenv(name, default)).strip().strip('"').strip("'")
    out: set[int] = set()
    for part in raw.split(','):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except Exception:
            continue
    return out


try:
    BACKOFF_FACTOR = _env_float("HTTP_STATUS_BACKOFF", "0.5")
except Exception:
    BACKOFF_FACTOR = 0.5

# By default, DO NOT retry on HTTP status codes (let higher-level pager handle 429/5xx)
DEFAULT_STATUS_FORCELIST = {408, 500, 502, 503, 504}  # 429 excluded by default
STATUS_RETRY_ENABLED = str(os.getenv("RETRY_ON_STATUS", "0")).lower() in {"1","true","yes","on"}
STATUS_FORCELIST = _env_csv_ints("RETRY_STATUS_CODES", ",".join(str(c) for c in DEFAULT_STATUS_FORCELIST)) if STATUS_RETRY_ENABLED else set()


def _build_session() -> requests.Session:
    sess = requests.Session()
    retry = Retry(
        total=int(os.getenv("RETRY_TOTAL", "3")),
        connect=int(os.getenv("RETRY_CONNECT", "2")),
        read=int(os.getenv("RETRY_READ", "2")),
        backoff_factor=BACKOFF_FACTOR,
        status_forcelist=STATUS_FORCELIST,
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    try:
        workers = int(os.getenv("WORKERS", "1"))
    except Exception:
        workers = 1
    pool = max(10, max(1, workers) * 2)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool, pool_block=True)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


# Thread-local session pool, one per worker
_TLS = threading.local()


def _get_max_session_uses() -> int:
    try:
        value = int(os.getenv("HTTP_SESSION_MAX_USES", "1000"))
        return value if value > 0 else 0
    except Exception:
        return 1000


def _increment_session_use(session: requests.Session) -> None:
    try:
        tls_session = getattr(_TLS, "session", None)
        if session is not tls_session:
            return
        uses = getattr(_TLS, "session_uses", 0) + 1
        setattr(_TLS, "session_uses", uses)
        max_uses = _get_max_session_uses()
        if max_uses and uses >= max_uses:
            try:
                session.close()
            except Exception:
                pass
            setattr(_TLS, "session", None)
            setattr(_TLS, "session_uses", 0)
            logger.info("Recycled HTTP session after %s uses", uses)
    except Exception:
        pass


def get_session() -> requests.Session:
    """Get a thread-local Session configured with retries and pooling."""
    sess = getattr(_TLS, "session", None)
    if sess is None:
        sess = _build_session()
        setattr(_TLS, "session", sess)
        setattr(_TLS, "session_uses", 0)
    return sess


def reset_session_pool() -> None:
    """Close and drop the current thread-local Session (recreated on next get)."""
    try:
        sess = getattr(_TLS, "session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
        setattr(_TLS, "session", None)
        setattr(_TLS, "session_uses", 0)
    except Exception:
        pass


def timed_get(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """GET with connect/read timeouts and a total wall-clock budget via HTTP_TIMEOUT.

    The total timeout is enforced by a monotonic clock around the single call; we rely on
    urllib3 Retry for internal retries.
    """
    import time as _time

    ct, rt, tt = _parse_timeout_env("HTTP_TIMEOUT", "10,45,90")
    start = _time.monotonic()
    remaining = tt - (_time.monotonic() - start)
    if remaining <= 0:
        raise requests.exceptions.Timeout(f"Total timeout exceeded ({tt}s) for {url}")

    force_total = str(os.getenv("FORCE_TOTAL_TIMEOUT", "1")).lower() in {"1", "true", "yes", "on"}
    if force_total and tt > 0:
        q: "queue.Queue[tuple[bool, object]]" = queue.Queue(maxsize=1)

        def _worker():
            # Use a fresh session in this helper thread to avoid sharing Sessions across threads
            # (requests Sessions are not thread-safe). Reuse our adapter configuration.
            local_sess = None
            try:
                local_sess = _build_session()
                r = local_sess.get(url, params=params, timeout=(ct, rt))
                q.put((True, r))
            except Exception as e:  # pragma: no cover
                q.put((False, e))
            finally:
                try:
                    if local_sess is not None:
                        local_sess.close()
                except Exception:
                    pass

        thr = threading.Thread(target=_worker, name="ahab-http-get", daemon=True)
        thr.start()
        try:
            ok, val = q.get(timeout=tt)
        except queue.Empty:
            try:
                # Recycle session on overrun to avoid stuck connections
                try:
                    session.close()
                except Exception:
                    pass
                setattr(_TLS, "session", None)
            except Exception:
                pass
            try:
                logger.debug("HTTP forced total-timeout after %.2fs url=%s params=%s", tt, url, params or {})
            except Exception:
                pass
            raise requests.exceptions.Timeout(f"Total timeout exceeded ({tt}s) for {url}")
        if not ok:
            # Propagate exception from worker
            if isinstance(val, Exception):
                raise val
            raise requests.exceptions.Timeout(f"Request failed for {url}")
        resp = val  # type: ignore[assignment]
    else:
        resp = session.get(url, params=params, timeout=(ct, rt))
    _increment_session_use(session)
    try:
        if str(os.getenv("RESPONSE_LOGS", "0")).lower() in {"1", "true", "yes", "on"}:
            dur_ms = int((_time.monotonic() - start) * 1000)
            plen = int(resp.headers.get("Content-Length", "0") or 0)
            logger.info("HTTP %s %s params=%s status=%s dur_ms=%s len=%s", "GET", url, params or {}, resp.status_code, dur_ms, plen)
            try:
                if str(os.getenv("RESPONSE_BODY", "0")).lower() in {"1","true","yes","on"}:
                    ctype = resp.headers.get("Content-Type", "") or ""
                    allow = ("json" in ctype.lower()) or ("text" in ctype.lower())
                    maxb = int(os.getenv("RESPONSE_MAX_BYTES", "2000") or 2000)
                    body = ""
                    if allow:
                        try:
                            body = resp.text
                        except Exception:
                            body = "<non-text-body>"
                    if body:
                        if len(body) > maxb:
                            body = body[:maxb] + "...<truncated>"
                        logger.info("HTTP RESPONSE %s %s body=%s", "GET", url, body)
            except Exception:
                pass
    except Exception:
        pass
    return resp

