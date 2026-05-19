"""Public OHLCV fetcher via ccxt (Kraken).

Originally built around Binance; switched to Kraken because Binance returns
HTTP 451 for US-hosted IPs, which is what GitHub Actions runners use. All
ccxt exchanges share the same fetch_ohlcv interface, so callers are
unaffected. The module name remains ``binance`` to avoid churn elsewhere.
"""

from __future__ import annotations

import time

import ccxt
import pandas as pd


# Map a TradingView-style timeframe string to its duration in minutes.
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440, "3d": 4320, "1w": 10080,
}

# Default HTF mapping for the trend bias when none is configured. Matches the
# tooltip recommendation in pricision_sniper_tv.txt line 35.
DEFAULT_HTF: dict[str, str] = {
    "1m": "1h", "3m": "1h", "5m": "1h", "15m": "1h", "30m": "1h",
    "1h": "4h", "2h": "4h", "4h": "1d", "6h": "1d", "8h": "1d", "12h": "1d",
    "1d": "1w",
}


def tf_to_minutes(tf: str) -> int:
    if tf not in TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported timeframe: {tf!r}")
    return TIMEFRAME_MINUTES[tf]


def suggest_htf(tf: str) -> str | None:
    return DEFAULT_HTF.get(tf)


def _client() -> ccxt.kraken:
    return ccxt.kraken({"enableRateLimit": True})


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = 500,
    client: ccxt.kraken | None = None,
) -> pd.DataFrame:
    """Fetch the most recent ``limit`` candles, drop the in-progress one, and
    return a UTC-indexed DataFrame with columns: open/high/low/close/volume.

    ccxt returns rows whose timestamp is the *open* time of the candle. A
    candle is considered closed when ``open_ts + tf_duration <= now``.
    """
    ex = client or _client()
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.set_index("ts").drop(columns=["ts_ms"])

    tf_ms = tf_to_minutes(timeframe) * 60_000
    now_ms = int(time.time() * 1000)
    # Keep only candles whose close time is in the past.
    closed_mask = (df.index.astype("int64") // 10**6 + tf_ms) <= now_ms
    return df.loc[closed_mask].astype(float)
