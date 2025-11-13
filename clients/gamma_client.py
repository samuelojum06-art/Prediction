"""
Polymarket Gamma API client.

Extended with markets pagination to support the Polymarket processor.
"""

from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional
import os
import logging
import json
from clients.http import get_session, reset_session_pool
from clients.perf import _bump_api_call
from clients.ratelimit import throttled_get
from datetime import datetime
from typing import Union

class StallTimeout(Exception):
    """Raised when rate-limit acquisition exceeds the configured timeout."""
    pass


class PolymarketGammaClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or os.getenv("POLYMARKET_GAMMA_BASE") or "https://gamma-api.polymarket.com").rstrip("/")
        self._log = logging.getLogger("Polymarket")
        try:
            self._gamma_timeout = float(os.getenv("POLYMARKET_GAMMA_HTTP_TIMEOUT_SEC", "15") or 15)
        except Exception:
            self._gamma_timeout = 15.0

    def get_market(self, market_id: str) -> Optional[Any]:
        url = f"{self.base_url}/markets/{market_id}"
        _bump_api_call(url)
        try:
            resp = throttled_get(get_session(), url, params=None, timeout=self._gamma_timeout, bucket="gamma_markets")
        except TimeoutError as _e:
            raise StallTimeout("acquire timeout in get_market")
        try:
            return resp.json()
        except Exception:
            return None

    def fetch_markets(self, limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch a page of markets.

        Mirrors legacy params: order by endDate ascending and include_tag.
        """
        url = f"{self.base_url}/markets"
        params = {
            "limit": int(limit),
            "offset": int(offset),
            "order": "endDate",
            "ascending": "true",
            "include_tag": "true",
        }
        only_open = str(os.getenv("POLYMARKET_GAMMA_ONLY_OPEN", "0")).lower() in {"1", "true", "yes", "on"}
        only_closed = str(os.getenv("POLYMARKET_GAMMA_ONLY_CLOSED", "0")).lower() in {"1", "true", "yes", "on"}
        if only_closed:
            params["closed"] = "true"
        elif only_open:
            params["closed"] = "false"
        _bump_api_call(url)
        sess = get_session()
        try:
            resp = throttled_get(sess, url, params=params, timeout=self._gamma_timeout, bucket="gamma_markets")
        except TimeoutError as _e:
            raise StallTimeout("acquire timeout in fetch_markets")
        try:
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("data", []) or []
            return []
        except Exception:
            return []

    def iter_markets(self, limit: int = 500, start_offset: int = 0) -> Iterable[Dict[str, Any]]:
        offset = int(start_offset or 0)
        empty_runs = 0
        while True:
            try:
                batch = self.fetch_markets(limit=limit, offset=offset)
                self._log.info(f"Called markets with offset {offset}")
            except StallTimeout:
                try:
                    reset_session_pool()
                except Exception:
                    pass
                self._log.warning("Gamma markets acquire timeout; retrying same offset=%s", offset)
                continue
            if not batch:
                empty_runs += 1
                if empty_runs >= 2:
                    break
                continue
            empty_runs = 0
            for m in batch:
                yield m
            offset += limit

    def iter_markets_concurrent(
        self,
        *,
        limit: int = 500,
        start_offset: int = 0,
        workers: int = 4,
        window_pages: int = 8,
    ) -> Iterable[Dict[str, Any]]:
        """Concurrent pager that fetches multiple offsets per cycle.

        Yields results in offset order. If a page times out on rate-limit acquire,
        it retries on the next cycle starting from the first missing offset, so we
        never skip an offset. Stops after two fully empty windows.
        """
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
        except Exception:
            # Fallback to sequential
            yield from self.iter_markets(limit=limit, start_offset=start_offset)
            return

        base = int(start_offset or 0)
        w = max(1, int(workers or 1))
        win = max(1, int(window_pages or 1))
        empty_windows = 0
        # Optional hard bounds and termination overrides via env
        try:
            _max_offset = int(os.getenv("POLYMARKET_GAMMA_MAX_OFFSET", "0") or 0)
        except Exception:
            _max_offset = 0
        try:
            _max_pages = int(os.getenv("POLYMARKET_GAMMA_MAX_PAGES", "0") or 0)
        except Exception:
            _max_pages = 0
        try:
            _never_stop_on_empty = str(os.getenv("POLYMARKET_GAMMA_NEVER_STOP_ON_EMPTY", "0")).lower() in {"1", "true", "yes", "on"}
        except Exception:
            _never_stop_on_empty = False
        pages_advanced_total = 0

        while True:
            if _max_offset and base >= _max_offset:
                self._log.info("Gamma pager: reached POLYMARKET_GAMMA_MAX_OFFSET=%s; stopping", _max_offset)
                break
            if _max_pages and pages_advanced_total >= _max_pages:
                self._log.info("Gamma pager: reached POLYMARKET_GAMMA_MAX_PAGES=%s; stopping", _max_pages)
                break
            offsets = [base + i * int(limit) for i in range(win)]
            results: dict[int, Optional[List[Dict[str, Any]]]] = {}
            had_any_data = False

            def _fetch(off: int) -> tuple[int, Optional[List[Dict[str, Any]]]]:
                try:
                    data = self.fetch_markets(limit=limit, offset=off)
                    self._log.info(f"Called markets with offset {off} (concurrent)")
                    return off, data
                except StallTimeout:
                    return off, None

            ex = None
            try:
                ex = ThreadPoolExecutor(max_workers=w)
                futs = [ex.submit(_fetch, off) for off in offsets]
                for fut in as_completed(futs):
                    off, data = fut.result()
                    results[off] = data
            except KeyboardInterrupt:
                # Cancel outstanding futures and avoid waiting on thread joins
                try:
                    if ex is not None:
                        ex.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                raise
            except Exception:
                # Fallback to sequential for this window
                for off in offsets:
                    try:
                        results[off] = self.fetch_markets(limit=limit, offset=off)
                    except StallTimeout:
                        results[off] = None
            finally:
                try:
                    if ex is not None:
                        ex.shutdown(wait=True)
                except Exception:
                    pass

            # Advance through longest contiguous successful prefix
            advanced_pages = 0
            for off in offsets:
                data = results.get(off, None)
                if data is None:
                    break  # retry this offset next cycle
                if not data:
                    advanced_pages += 1
                    continue
                had_any_data = True
                for m in data:
                    yield m
                advanced_pages += 1

            if had_any_data:
                empty_windows = 0
            else:
                if _never_stop_on_empty:
                    # Force-scan mode: advance past this window even if empty
                    empty_windows = 0
                    advanced_pages = win  # pretend full window advanced
                else:
                    empty_windows += 1
                    if empty_windows >= 2:
                        break

            base = base + (advanced_pages * int(limit))
            pages_advanced_total += advanced_pages

