"""
Minimal, robust Polymarket CLOB client for public order books.

Env:
- POLYMARKET_CLOB_BASE or POLY_CLOB_BASE to override base URL
- POLYMARKET_API_KEY or POLY_API_KEY optional header
"""

from __future__ import annotations
import os
import typing as t
import requests
from clients.ratelimit import throttled_get


class ClobError(RuntimeError):
    pass


def _default_headers() -> dict:
    hdr = {
        "User-Agent": "PredictionMarkets/first-trade (python-requests)",
        "Accept": "application/json",
    }
    api_key = os.getenv("POLYMARKET_API_KEY") or os.getenv("POLY_API_KEY")
    if api_key:
        hdr["X-API-Key"] = api_key
    return hdr


def _clob_base() -> str:
    return (
        os.getenv("POLYMARKET_CLOB_BASE")
        or os.getenv("POLY_CLOB_BASE")
        or "https://clob.polymarket.com"
    ).rstrip("/")


def _normalize_token_id(x: t.Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip().strip('"').strip("'")
    if not s:
        return None
    return s


class PolymarketCLOB:
    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or _clob_base()).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(_default_headers())

    def get_prices_history(
        self,
        *,
        market: str,
        start_ts: int,
        end_ts: int,
        fidelity: int = 60,
        timeout: int = 20,
    ) -> list[dict]:
        """Fetch price history points for a market in a time window.

        Wraps the public CLOB endpoint `/prices-history` and returns a list of
        point objects. Accepts flexible response shapes by checking common keys
        ("history", "data", "prices"). Raises ClobError on non-2xx or
        non-JSON responses.
        """
        mk = _normalize_token_id(market)
        if not mk:
            raise ClobError("Missing/invalid market (token) id")
        url = f"{self.base_url}/prices-history"
        params = {
            "market": mk,
            "startTs": int(start_ts),
            "endTs": int(end_ts),
            "fidelity": int(fidelity),
        }
        try:
            resp = throttled_get(self.session, url, params=params, timeout=timeout, bucket="clob_prices_history")
        except requests.RequestException as e:
            raise ClobError(f"request failed: {e}")
        if not (200 <= int(getattr(resp, "status_code", 0)) < 300):
            snippet = ""
            try:
                snippet = (resp.text or "")[:300].replace("\n", " ")
            except Exception:
                pass
            raise ClobError(f"HTTP {resp.status_code} GET {url} :: {snippet}")
        try:
            data = resp.json() or {}
        except ValueError:
            raise ClobError("Non-JSON response from prices-history")
        if isinstance(data, list):
            return list(data)
        for key in ("history", "data", "prices"):
            pts = data.get(key)
            if isinstance(pts, list):
                return list(pts)
        # No recognizable payload, return empty for resilience
        return []

