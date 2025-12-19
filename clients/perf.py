"""
Perf tracking and report-card helpers shared by collectors.

Lifted from Ahab (2025-10-08) without behavior changes.
"""

from __future__ import annotations
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PerfTracker:
    def __init__(self, emit_every: int = 800, path: str = "logs/report_card.jsonl"):
        self.path = path
        self.emit_every = emit_every
        self.buf: List[Dict[str, Any]] = []
        self.counts: Dict[str, List[float]] = {}
        self.codes: Dict[str, List[int]] = {}

    def record(self, endpoint: str, latency_s: float, status_code: int):
        self.counts.setdefault(endpoint, []).append(latency_s)
        self.codes.setdefault(endpoint, []).append(status_code)
        self.buf.append({"t": time.time(), "endpoint": endpoint, "latency": latency_s, "status": status_code})
        if len(self.buf) >= self.emit_every:
            self.flush()

    def snapshot(self) -> Dict[str, Any]:
        out = {"by_endpoint": {}}
        for ep, arr in self.counts.items():
            lat = sorted(arr)
            n = len(lat)
            p50 = lat[int(0.50 * n) - 1] if n else None
            p90 = lat[int(0.90 * n) - 1] if n else None
            p95 = lat[int(0.95 * n) - 1] if n else None
            codes = self.codes.get(ep, [])
            err_rate = sum(1 for c in codes if c == 429 or 500 <= c < 600) / max(1, len(codes))
            out["by_endpoint"][ep] = {
                "count": n,
                "avg": mean(arr) if n else None,
                "p50": p50,
                "p90": p90,
                "p95": p95,
                "max": (lat[-1] if n else None),
                "err_rate": err_rate,
            }
        return out

    def flush(self):
        if not self.buf:
            return
        try:
            Path("logs").mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                for row in self.buf:
                    f.write(json.dumps(row) + "\n")
        except Exception:
            pass
        finally:
            self.buf.clear()


_ENDPOINT_TIMES = defaultdict(lambda: {"n": 0, "sum": 0.0, "lat": deque(maxlen=200)})
_REPORT_LOCK = threading.Lock()


def _write_report_card() -> None:
    from datetime import datetime, timezone

    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / "report_card.log"
        parts: list[str] = []
        for ep, agg in sorted(_ENDPOINT_TIMES.items()):
            n = int(agg.get("n", 0) or 0)
            total = float(agg.get("sum", 0.0) or 0.0)
            avg = total / max(1, n)
            lat = list(agg.get("lat", []))
            p50 = p90 = mx = None
            if lat:
                lat_sorted = sorted(lat)
                m = len(lat_sorted)
                p50 = lat_sorted[int(0.50 * m) - 1] if m else None
                p90 = lat_sorted[int(0.90 * m) - 1] if m else None
                mx = lat_sorted[-1]
            if lat:
                parts.append(f"{ep} n={n} avg={avg:.2f}s p50={p50:.2f}s p90={p90:.2f}s max={mx:.2f}s")
            else:
                parts.append(f"{ep} n={n} avg={avg:.2f}s")
        line = "=== Endpoint timing === " + " ".join(parts)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
        with _REPORT_LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{ts} {line}\n")
    except Exception:
        pass


_API_CALLS = 0
try:
    _REPORT_CARD_INTERVAL_SEC = float(os.getenv("AHAB_REPORT_CARD_INTERVAL_SEC", "600"))
except Exception:
    _REPORT_CARD_INTERVAL_SEC = 600.0
_LAST_REPORT_TS: float = time.time()


def _bump_api_call(label: str) -> int:
    global _API_CALLS, _LAST_REPORT_TS
    _API_CALLS += 1
    logger.debug("API call #%d -> %s", _API_CALLS, label)
    try:
        now = time.time()
        if (now - _LAST_REPORT_TS) >= _REPORT_CARD_INTERVAL_SEC:
            with _REPORT_LOCK:
                if (now - _LAST_REPORT_TS) >= _REPORT_CARD_INTERVAL_SEC:
                    _write_report_card()
                    _LAST_REPORT_TS = now
    except Exception:
        pass
    return _API_CALLS

