"""Vector indicator implementations matching TradingView Pine v6 semantics.

We intentionally use simple pandas/numpy primitives rather than `pandas-ta` —
pandas-ta has been unmaintained and breaks on recent numpy. The formulas below
mirror Pine v6 (`ta.ema`, `ta.rsi`, `ta.macd`, `ta.atr`, `ta.dmi`, `ta.vwap`,
`ta.sma`). Wilder-smoothed indicators (RSI/ATR/ADX) use ``ewm(alpha=1/n,
adjust=False)``; over a few hundred bars of warmup the difference vs. Pine's
SMA-seeded RMA is well below tick precision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def _rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1.0 / length, adjust=False).mean()


def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = _rma(up, length)
    avg_down = _rma(down, length)
    rs = avg_up / avg_down.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(100.0).where(avg_down != 0, 100.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal_len: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal_len)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    return _rma(true_range(df), length)


def dmi(df: pd.DataFrame, di_len: int = 14, adx_len: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (+DI, -DI, ADX). Matches Pine `ta.dmi`."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    tr_rma = _rma(true_range(df), di_len)
    plus_di = 100.0 * _rma(plus_dm, di_len) / tr_rma.replace(0.0, np.nan)
    minus_di = 100.0 * _rma(minus_dm, di_len) / tr_rma.replace(0.0, np.nan)
    plus_di = plus_di.fillna(0.0)
    minus_di = minus_di.fillna(0.0)

    sum_di = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / sum_di.replace(0.0, np.nan)
    dx = dx.fillna(0.0)
    adx = _rma(dx, adx_len)
    return plus_di, minus_di, adx


def hlc3(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"] + df["close"]) / 3.0


def vwap_daily(df: pd.DataFrame) -> pd.Series:
    """Anchored daily VWAP using HLC3 — Pine's `ta.vwap` default for crypto.

    Assumes the index is a UTC ``DatetimeIndex``; resets at each UTC midnight.
    """
    src = hlc3(df) * df["volume"]
    day = df.index.floor("1D")
    cum_src = src.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    out = cum_src / cum_vol.replace(0.0, np.nan)
    return out.ffill().fillna(df["close"])


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def swing_low(low: pd.Series, lookback: int) -> pd.Series:
    """Min of low over the last `lookback+1` bars (current bar + lookback prior). Pine getSwingLow."""
    return low.rolling(window=lookback + 1, min_periods=1).min()


def swing_high(high: pd.Series, lookback: int) -> pd.Series:
    return high.rolling(window=lookback + 1, min_periods=1).max()
