"""
Rate limiter for Polymarket client wrappers (gamma_client, data_client, clob_client).
For other modules, use common/rate_limiter.py.
TODO: Consolidate both limiters post-v1 launch.
"""

import os
import threading
import time
from typing import Dict, Optional, List, Tuple

import requests



__all__ = [
    "throttled_get",
    "acquire",
    "start_heartbeat",
    "bump_429",
]


def _env_int(k: str, d: str) -> int:
    try:
        return int(os.getenv(k, d))
    except Exception:
        return int(d)


def _env_float(k: str, d: str) -> float:
    try:
        return float(os.getenv(k, d))
    except Exception:
        return float(d)


SAFETY = _env_float("RL_SAFETY_PCT", "0.8")

LIMITS = {
    # CLOB
    "clob_book": int(SAFETY * _env_int("RL_CLOB_BOOK_PER_10S", "50")),
    "clob_prices_history": int(
        SAFETY * _env_int("RL_CLOB_PRICES_HISTORY_PER_10S", "40")
    ),
    # Gamma
    "gamma_markets": int(SAFETY * _env_int("RL_GAMMA_MARKETS_PER_10S", "125")),
    # Data API
    "data_activity": int(SAFETY * _env_int("RL_DATA_ACTIVITY_PER_10S", "40")),
    "data_holders": int(SAFETY * _env_int("RL_DATA_HOLDERS_PER_10S", "40")),
    "data_closed_positions": int(
        SAFETY * _env_int("RL_DATA_CLOSED_POS_PER_10S", "40")
    ),
    "data_positions": int(SAFETY * _env_int("RL_DATA_POSITIONS_PER_10S", "40")),
}

# Optional richer configuration for multi-window buckets, adaptive behavior, etc.
# Keys mirror bucket names; when a name exists here with "windows", a MultiWindowBucket is used.
BUCKET_CONFIGS: Dict[str, Dict[str, object]] = {
    # Example for trading endpoints (not actively used by current read-only clients):
    # "clob_order_post": {"windows": [(2400, 10), (24000, 600)], "adaptive": True},
}

# Optional: enable multi-window throttling for data_activity to match Cloudflare sliding windows
try:
    _per_min = int(os.getenv("RL_DATA_ACTIVITY_PER_60S", "0") or 0)
except Exception:
    _per_min = 0
if _per_min > 0:
    try:
        per10 = int(LIMITS.get("data_activity", 40))
    except Exception:
        per10 = 40
    # Apply safety to minute window as well
    per60 = int(SAFETY * _per_min)
    if per60 <= 0:
        per60 = _per_min
    BUCKET_CONFIGS["data_activity"] = {"windows": [(per10, 10), (per60, 60)]}


class Bucket:
    __slots__ = ("cap", "tokens", "last", "lock", "backoff_until", "backoff_multiplier", "_refill_per_sec")

    def __init__(self, cap: Optional[int] = None, *, capacity: Optional[int] = None, refill_per_sec: float = 0.0):
        # Backward compatible: allow positional cap, or named capacity
        chosen_cap = capacity if capacity is not None else cap
        self.cap = max(1, int(chosen_cap if chosen_cap is not None else 1))
        self.tokens = float(self.cap)
        self.last = time.time()
        self.lock = threading.Lock()
        self.backoff_until = 0.0
        self.backoff_multiplier = 1.0
        # If provided, use explicit refill rate (tokens per second); otherwise default to 10s window behavior
        try:
            self._refill_per_sec = float(refill_per_sec) if refill_per_sec and refill_per_sec > 0 else (self.cap / 10.0)
        except Exception:
            self._refill_per_sec = self.cap / 10.0

    def acquire(self, max_wait: Optional[float] = None) -> None:
        start = time.time()
        with self.lock:
            while True:
                # Timeout guard
                if max_wait is not None and (time.time() - start) >= float(max_wait):
                    raise TimeoutError("rate-limit acquire timeout")
                now = time.time()
                # honor backoff if active
                if now < self.backoff_until:
                    sleep_time = max(0.0, self.backoff_until - now)
                    # Cap sleep by remaining budget, if provided
                    if max_wait is not None:
                        rem = float(max_wait) - (time.time() - start)
                        if rem <= 0:
                            raise TimeoutError("rate-limit acquire timeout")
                        sleep_time = max(0.01, min(sleep_time, rem))
                    time.sleep(sleep_time)
                    now = time.time()
                dt = now - self.last
                self.last = now
                # Refill tokens according to configured rate (tokens per second)
                self.tokens = min(self.cap, self.tokens + (self._refill_per_sec * dt))
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                # sleep until next token fraction
                need = (1.0 - self.tokens) / max(1e-9, self._refill_per_sec)
                sl = max(0.01, need)
                if max_wait is not None:
                    rem = float(max_wait) - (time.time() - start)
                    if rem <= 0:
                        raise TimeoutError("rate-limit acquire timeout")
                    sl = max(0.01, min(sl, rem))
                time.sleep(sl)

    def record_429(self, retry_after: Optional[float] = None) -> None:
        self.backoff_multiplier = min(8.0, self.backoff_multiplier * 2.0)
        base = 5.0 * self.backoff_multiplier
        bo = float(retry_after) if retry_after is not None else base
        self.backoff_until = max(self.backoff_until, time.time() + bo)

    def record_success(self) -> None:
        # Gradually reduce backoff multiplier; does not change backoff_until retroactively
        self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)

    def snapshot(self) -> Dict[str, float]:
        now = time.time()
        backoff_rem = max(0.0, self.backoff_until - now)
        return {"tokens": float(self.tokens), "cap": float(self.cap), "backoff": backoff_rem}


class MultiWindowBucket:
    def __init__(self, windows: List[Tuple[int, int]]):
        # windows: list of (limit, seconds)
        # Treat the first window as the burst bucket; initialize all windows with the burst capacity for immediate bursting
        burst_cap = int(windows[0][0]) if windows else 1
        now = time.time()
        self.windows = [
            {"cap": int(limit), "tokens": float(burst_cap), "seconds": float(sec), "last": now}
            for limit, sec in windows
        ]
        self.lock = threading.Lock()
        self.backoff_until = 0.0
        self.backoff_multiplier = 1.0

    def acquire(self, max_wait: Optional[float] = None) -> None:
        start = time.time()
        with self.lock:
            while True:
                # Timeout guard
                if max_wait is not None and (time.time() - start) >= float(max_wait):
                    raise TimeoutError("rate-limit acquire timeout")
                now = time.time()
                if now < self.backoff_until:
                    sl = max(0.0, self.backoff_until - now)
                    if max_wait is not None:
                        rem = float(max_wait) - (time.time() - start)
                        if rem <= 0:
                            raise TimeoutError("rate-limit acquire timeout")
                        sl = max(0.01, min(sl, rem))
                    time.sleep(sl)
                    now = time.time()
                can_proceed = True
                min_sleep = None
                for w in self.windows:
                    dt = now - w["last"]
                    # Preserve preloaded burst tokens above cap; only consume them, don't clamp down.
                    if w["tokens"] <= w["cap"]:
                        w["tokens"] = min(w["cap"], w["tokens"] + (w["cap"] * dt / w["seconds"]))
                    # else: keep tokens as-is (no refill growth beyond cap)
                    w["last"] = now
                    if w["tokens"] < 1.0:
                        can_proceed = False
                        need = (1.0 - w["tokens"]) / (w["cap"] / w["seconds"]) if w["cap"] > 0 else 0.1
                        min_sleep = need if (min_sleep is None or need < min_sleep) else min_sleep
                if can_proceed:
                    for w in self.windows:
                        w["tokens"] -= 1.0
                    return
                sl = max(0.01, float(min_sleep or 0.05))
                if max_wait is not None:
                    rem = float(max_wait) - (time.time() - start)
                    if rem <= 0:
                        raise TimeoutError("rate-limit acquire timeout")
                    sl = max(0.01, min(sl, rem))
                time.sleep(sl)

    def record_429(self, retry_after: Optional[float] = None) -> None:
        self.backoff_multiplier = min(8.0, self.backoff_multiplier * 2.0)
        base = 5.0 * self.backoff_multiplier
        bo = float(retry_after) if retry_after is not None else base
        self.backoff_until = max(self.backoff_until, time.time() + bo)

    def record_success(self) -> None:
        self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)

    # Provide a snapshot similar to Bucket for heartbeat
    @property
    def cap(self) -> int:
        try:
            return int(self.windows[0]["cap"]) if self.windows else 1
        except Exception:
            return 1

    @property
    def tokens(self) -> float:
        try:
            return float(self.windows[0]["tokens"]) if self.windows else 0.0
        except Exception:
            return 0.0

    def snapshot(self) -> Dict[str, float]:
        now = time.time()
        backoff_rem = max(0.0, self.backoff_until - now)
        try:
            t0 = float(self.windows[0]["tokens"]) if self.windows else 0.0
            c0 = float(self.windows[0]["cap"]) if self.windows else 1.0
        except Exception:
            t0, c0 = 0.0, 1.0
        return {"tokens": t0, "cap": c0, "backoff": backoff_rem, "windows": float(len(self.windows or []))}


def _make_bucket(name: str) -> object:
    cfg = BUCKET_CONFIGS.get(name) or {}
    wins = cfg.get("windows") if isinstance(cfg, dict) else None
    if isinstance(wins, list) and wins:
        # windows items expected as tuple/list (limit, seconds)
        pairs: List[Tuple[int, int]] = []
        for it in wins:
            try:
                limit, sec = int(it[0]), int(it[1])  # type: ignore[index]
                pairs.append((limit, sec))
            except Exception:
                continue
        if pairs:
            return MultiWindowBucket(pairs)
    cap = int(LIMITS.get(name, int(max(1, SAFETY * 10))))
    return Bucket(cap)


_BUCKETS: Dict[str, object] = {name: _make_bucket(name) for name in set(list(LIMITS.keys()) + list(BUCKET_CONFIGS.keys()))}
_429 = 0
_HB_ONCE = False
_HB_INTERVAL = _env_int("RL_HEARTBEAT_SECS", "30")


def bump_429(bucket: Optional[str] = None, retry_after: Optional[float] = None) -> None:
    global _429
    _429 += 1
    try:
        if bucket:
            b = _BUCKETS.get(bucket)
            if b and hasattr(b, "record_429"):
                getattr(b, "record_429")(retry_after)
    except Exception:
        pass


def start_heartbeat() -> None:
    global _HB_ONCE
    if _HB_ONCE:
        return
    _HB_ONCE = True

    def _beat() -> None:
        while True:
            try:
                parts = []
                for k, b in _BUCKETS.items():
                    try:
                        snap = b.snapshot() if hasattr(b, "snapshot") else {}
                        tok = int(snap.get("tokens", getattr(b, "tokens", 0)))
                        cap = int(snap.get("cap", getattr(b, "cap", 1)))
                        back = snap.get("backoff", 0.0)
                        parts.append(f"{k}:{tok}/{cap}{' b' if back else ''}")
                    except Exception:
                        parts.append(f"{k}:-/-")
                caps = ", ".join(parts)
                print(f"[rate-limit] tokens [{caps}] 429s={_429}")
            except Exception:
                pass
            time.sleep(max(1, int(_HB_INTERVAL)))

    t = threading.Thread(target=_beat, daemon=True)
    t.start()


def acquire(bucket: str, *, max_wait: Optional[float] = None) -> None:
    b = _BUCKETS.get(bucket)
    if not b:
        _BUCKETS[bucket] = b = _make_bucket(bucket)
    # type: ignore[attr-defined]
    try:
        b.acquire(max_wait=max_wait) if hasattr(b, "acquire") else None
    except TypeError:
        # Backward compat if Bucket.acquire signature is old
        b.acquire()  # type: ignore[misc]


def throttled_get(
    session: requests.Session,
    url: str,
    *,
    params=None,
    timeout: float = 15.0,
    bucket: str,
):
    start_heartbeat()
    # Guard on token acquisition to avoid long stalls
    try:
        acquire_timeout = _env_float("RL_ACQUIRE_TIMEOUT_SEC", "60")
    except Exception:
        acquire_timeout = 60.0
    acquire(bucket, max_wait=acquire_timeout)
    resp = session.get(url, params=params, timeout=timeout)
    try:
        status = int(getattr(resp, "status_code", 200) or 200)
        if status == 429:
            try:
                ra = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
                ra_f = float(ra) if ra is not None else None
            except Exception:
                ra_f = None
            bump_429(bucket, ra_f)
        elif 200 <= status < 400:
            b = _BUCKETS.get(bucket)
            if b and hasattr(b, "record_success"):
                try:
                    getattr(b, "record_success")()
                except Exception:
                    pass
    except Exception:
        pass
    return resp
