import os
import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from clients.gamma_client import PolymarketGammaClient
from clients.clob_client import PolymarketCLOB, ClobError


THRESHOLD = float(os.getenv("PM_THRESHOLD", "-0.10"))     # 10% drop in prob
FIDELITY = int(os.getenv("PM_FIDELITY", "60"))            # seconds per point (60 = 1-min)
N_MARKETS = int(os.getenv("PM_N_MARKETS", "10"))          # how many markets to test
WINDOW_HOURS = float(os.getenv("PM_WINDOW_HOURS", "1"))   # history window size
SLEEP_BETWEEN = float(os.getenv("PM_SLEEP_BETWEEN", "0.05"))

SIMULATE_RESOLUTION = str(os.getenv("PM_SIM_RESOLUTION", "1")).lower() in {"1", "true", "yes", "on"}

np.random.seed(42)

# Helpers

def now_epoch() -> int:
    return int(time.time())

def build_time_window(hours: float) -> tuple[int, int]:
    end_ts = now_epoch()
    start_ts = end_ts - int(hours * 3600)
    return start_ts, end_ts

def normalize_price_to_prob(price: float) -> float:
    """
    Polymarket price is generally already in [0,1] and can be interpreted as probability.
    Keep it clipped for resilience.
    """
    try:
        p = float(price)
    except Exception:
        return np.nan
    return float(np.clip(p, 0.0001, 0.9999))

def market_id_from_gamma_row(m: dict) -> str | None:
    # Gamma, verying names; handle common variants
    return (
        m.get("conditionId")
        or m.get("condition_id")
        or m.get("marketId")
        or m.get("market_id")
        or m.get("id")
    )

def pick_yes_token(m: dict) -> str | None:
    """
    If you later want to backtest YES vs NO specifically, you can map token IDs here.
    For now, we treat 'market id' as the identifier used by /prices-history in your client.
    """
    return market_id_from_gamma_row(m)

def simulate_winner(prob0: float) -> int:
    """Simulate resolution: 1 = YES wins, 0 = NO wins (biased by initial prob)."""
    p = float(np.clip(prob0, 0.05, 0.95))
    return int(np.random.rand() < p)

def pm_bet_return(entry_price: float, resolves_yes: int) -> float:
    """
    Prediction-market payoff if you BUY YES at price p (cost = p):
      - If YES resolves: receive $1 -> profit = 1 - p
      - If NO resolves: receive $0 -> profit = -p
    """
    p = normalize_price_to_prob(entry_price)
    if np.isnan(p):
        return 0.0
    return (1.0 - p) if resolves_yes == 1 else (-p)

# Data
gamma = PolymarketGammaClient()
clob = PolymarketCLOB()

print("Fetching markets from Gamma...")
markets = gamma.fetch_markets(limit=max(N_MARKETS, 50), offset=0)  # pull a page; filter after
if not isinstance(markets, list) or not markets:
    raise RuntimeError("No markets returned from Gamma. Check connectivity / base URL env vars.")

# Basic filtering: keep markets with an ID we can use
usable = []
for m in markets:
    mid = pick_yes_token(m)
    if mid:
        usable.append(m)
    if len(usable) >= N_MARKETS:
        break

if not usable:
    raise RuntimeError("Could not find any usable markets with conditionId/marketId in Gamma results.")

start_ts, end_ts = build_time_window(WINDOW_HOURS)

rows = []
print(f"Pulling price history for {len(usable)} markets (window={WINDOW_HOURS}h, fidelity={FIDELITY}s)...")
for i, m in enumerate(usable, start=1):
    market_id = pick_yes_token(m)
    title = m.get("question") or m.get("title") or m.get("name") or f"Market {market_id}"
    try:
        pts = clob.get_prices_history(
            market=market_id,
            start_ts=start_ts,
            end_ts=end_ts,
            fidelity=FIDELITY,
            timeout=20
        )
    except ClobError as e:
        print(f"[skip] {market_id}: {e}")
        continue

    if not pts:
        print(f"[skip] {market_id}: empty history")
        continue

    # Normalize response points. 
    for p in pts:
        ts = p.get("t") or p.get("timestamp") or p.get("ts")
        price = p.get("p") or p.get("price") or p.get("mid") or p.get("value")
        if ts is None or price is None:
            continue
        rows.append({
            "market_id": str(market_id),
            "title": str(title)[:120],
            "ts": int(ts),
            "price": float(price),
        })

    time.sleep(SLEEP_BETWEEN)

df = pd.DataFrame(rows)
if df.empty:
    raise RuntimeError("No price history collected. Increase PM_WINDOW_HOURS or check market IDs.")

# minute index for plotting
df = df.sort_values(["market_id", "ts"]).reset_index(drop=True)
df["minute"] = df.groupby("market_id").cumcount() + 1
df["prob"] = df["price"].apply(normalize_price_to_prob)

# initial baseline probability 
p0 = df.groupby("market_id")["prob"].first().rename("P0")
df = df.merge(p0, on="market_id")
df["pct_change"] = (df["prob"] - df["P0"]) / df["P0"]

# Signal: buy YES when probability drops by threshold or more
df["signal"] = np.where(df["pct_change"] <= THRESHOLD, 1, 0)

# Resolution 
if SIMULATE_RESOLUTION:
    res = df.groupby("market_id")["P0"].first().apply(simulate_winner).rename("resolves_yes")
    df = df.merge(res, on="market_id")
else:
    df["resolves_yes"] = 0

# P&L when theu place bet only when signal triggers; otherwise 0
def row_return(r):
    if int(r["signal"]) != 1:
        return 0.0
    return pm_bet_return(r["prob"], int(r["resolves_yes"]))

df["return"] = df.apply(row_return, axis=1)

# Market Summary
summary = df.groupby(["market_id", "title"], as_index=False).agg(
    bets_made=("signal", "sum"),
    total_return=("return", "sum"),
    p0=("P0", "first"),
    resolves_yes=("resolves_yes", "first"),
)
total_bets = int(summary["bets_made"].sum())
total_pnl = float(summary["total_return"].sum())
avg_return = (total_pnl / total_bets) if total_bets > 0 else 0.0

# Cumulative P&L 
df["cumulative_PnL"] = df.groupby("market_id")["return"].cumsum()

# plot
plt.figure(figsize=(11, 5))
for mid, g in df.groupby("market_id"):
    plt.plot(g["minute"], g["cumulative_PnL"], alpha=0.7)
plt.axhline(0, linestyle="--")
plt.title("Cumulative P&L per Polymarket Market (Behavioral Drop Strategy)")
plt.xlabel("Minute index (within fetched window)")
plt.ylabel("Cumulative P&L ($ per $1 notional YES buys)")
plt.tight_layout()
plt.show()

# summary
print("\n========== BACKTEST SUMMARY (POLYMARKET) ==========")
print(f"Markets tested: {summary.shape[0]}")
print(f"Total bets made: {total_bets}")
print(f"Total P&L: {total_pnl:.3f}")
print(f"Average return per bet: {avg_return:.4f}")
print(f"Threshold (pct drop): {THRESHOLD:.2%}")
print(f"Window (hours): {WINDOW_HOURS}, Fidelity (sec): {FIDELITY}")
print("==================================================\n")

# for showing how top/bottom markets by P&L (couldve been an if/else i think)
summary_sorted = summary.sort_values("total_return", ascending=False)
print("Top markets:")
print(summary_sorted.head(5)[["market_id", "bets_made", "total_return", "p0", "resolves_yes", "title"]])

print("\nBottom markets:")
print(summary_sorted.tail(5)[["market_id", "bets_made", "total_return", "p0", "resolves_yes", "title"]])

