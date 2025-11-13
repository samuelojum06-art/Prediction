# Polymarket Clients

This folder provides lightweight, production-ready Python clients for interacting with the **Polymarket** APIs (Gamma and CLOB), including built-in **rate limiting**, **HTTP session pooling**, and **performance tracking**.

---

## 📦 Contents

| File | Description |
|------|--------------|
| `gamma_client.py` | Fetches market listings and metadata from the Polymarket **Gamma API**. Includes concurrent pagination support. |
| `clob_client.py` | Pulls price history and other order-book data from the **CLOB API**. Handles JSON variations automatically. |
| `http.py` | Shared HTTP session pool with retries, backoff, and total timeout enforcement. |
| `ratelimit.py` | Token-bucket rate limiter with multi-window support, 429 handling, and a live heartbeat logger. |
| `perf.py` | Tracks API latency and writes periodic performance summaries. |
| `__init__.py` | Allows all clients to be imported via `from clients import ...` |

---

## ⚙️ Features

- ✅ **Thread-safe session pooling** — reuses a `requests.Session` per thread for efficiency.
- ✅ **Rate limiting** — automatically throttles requests to stay under Polymarket’s limits (see `API_RATE_LIMITS.md`).
- ✅ **429 backoff** — exponentially increases delay after rate-limit responses.
- ✅ **Heartbeat logging** — prints live bucket status every 30s (`[rate-limit] tokens [...]`).
- ✅ **Performance metrics** — logs latency and response rates in `logs/report_card.log`.
- ✅ **Graceful error handling** — raises clear `ClobError` or `StallTimeout` exceptions.

---

## 🧠 Quick Start Example

```python
from clients.gamma_client import PolymarketGammaClient
from clients.clob_client import PolymarketCLOB

gamma = PolymarketGammaClient()
clob = PolymarketCLOB()

# Fetch first 100 markets
markets = gamma.fetch_markets(limit=100, offset=0)
print("Fetched markets:", len(markets))

# Get price history for one market
if markets:
    m = markets[0]
    cond_id = m.get("conditionId") or m.get("condition_id")
    prices = clob.get_prices_history(
        market=cond_id,
        start_ts=1720000000,
        end_ts=1720003600,
        fidelity=60
    )
    print("Price history points:", len(prices))
```

---

## 🌐 Environment Variables

| Variable | Default | Description |
|-----------|----------|--------------|
| `POLYMARKET_GAMMA_BASE` | `https://gamma-api.polymarket.com` | Gamma API base URL |
| `POLYMARKET_CLOB_BASE` | `https://clob.polymarket.com` | CLOB API base URL |
| `POLYMARKET_API_KEY` | *(optional)* | Adds `X-API-Key` header for authenticated calls |
| `RL_*` | see `API_RATE_LIMITS.md` | Customize rate-limit buckets |
| `AHAB_*` | advanced settings for retries and timeouts |

---

## 🧪 Testing

Run a smoke test after install:

```bash
pip install -e .
python -m clients.gamma_client
python -m clients.clob_client
```

Or include a lightweight test:

```python
from clients.gamma_client import PolymarketGammaClient
g = PolymarketGammaClient()
data = g.fetch_markets(limit=1, offset=0)
assert isinstance(data, list)
```

---

## 🧩 Integration with MongoDB

See `mongodb_setup.md` for instructions on how to:
- Store market documents in a `markets` collection.
- Filter documents by `gameStartTime`.
- Convert ISO timestamps to epochs.
- Retrieve 1-minute price history using the CLOB client.

---

## 🧾 License

MIT License © 2025 Ryder Rhoads

---

These clients are the same foundation used in Ryder’s internal **Prediction Markets** collectors. They are safe for educational use and light research scraping under rate limits.
