import numpy as np
import pandas as pd
import pytest

from precision_bot.indicator import indicators as ind
from precision_bot.indicator import precision_sniper as ps
from precision_bot.indicator.presets import (
    CUSTOM_DEFAULTS,
    resolve_auto,
    resolve_preset,
)


# ---------- grade boundaries ----------

@pytest.mark.parametrize(
    "score, expected",
    [
        (8.0, "A+"),
        (7.99, "A"),
        (6.5, "A"),
        (6.49, "B"),
        (5.0, "B"),
        (4.99, "C"),
        (0.0, "C"),
    ],
)
def test_grade_boundaries(score, expected):
    assert ps.get_grade(score) == expected


@pytest.mark.parametrize(
    "score, gf, hide_c, expected",
    [
        (8.0, "A+ Only", True, True),
        (7.99, "A+ Only", True, False),
        (6.5, "A+ and A", True, True),
        (5.0, "All", True, True),
        (4.99, "All", True, False),
        (4.99, "All", False, True),  # hide_c=False allows sub-5 scores through
    ],
)
def test_grade_filter(score, gf, hide_c, expected):
    assert ps.passes_grade_filter(score, gf, hide_c) is expected


# ---------- preset resolver ----------

def test_auto_preset_brackets():
    assert resolve_auto(1) == "Scalping"
    assert resolve_auto(5) == "Scalping"
    assert resolve_auto(15) == "Default"
    assert resolve_auto(60) == "Default"
    assert resolve_auto(240) == "Aggressive"
    assert resolve_auto(1440) == "Swing"


def test_resolve_preset_returns_params():
    p = resolve_preset("Default", 60)
    assert p.ema_fast == 9 and p.ema_slow == 21 and p.min_score == 5


def test_custom_preset_returns_custom_defaults():
    p = resolve_preset("Custom", 60)
    assert p == CUSTOM_DEFAULTS


# ---------- indicator parity sanity ----------

def _toy_frame(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Trending series with noise → ensures EMAs/RSI move meaningfully.
    base = np.cumsum(rng.normal(0.5, 1.0, n)) + 100
    high = base + rng.uniform(0.5, 2.0, n)
    low = base - rng.uniform(0.5, 2.0, n)
    close = base + rng.normal(0, 0.3, n)
    vol = rng.uniform(100, 200, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": base, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def test_ema_matches_ewm_formula():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    expected = s.ewm(span=3, adjust=False).mean()
    pd.testing.assert_series_equal(ind.ema(s, 3), expected, check_names=False)


def test_rsi_within_bounds():
    df = _toy_frame(300)
    r = ind.rsi(df["close"], 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_atr_positive():
    df = _toy_frame(300)
    a = ind.atr(df, 14).dropna()
    assert (a > 0).all()


def test_score_within_max():
    """bull_score + bear_score should never each exceed 10 (max possible)."""
    df = _toy_frame(400)
    cfg = ps.IndicatorConfig(preset_params=resolve_preset("Default", 60))
    frame = ps.evaluate(df, cfg)
    assert frame["bull_score"].max() <= 10.001
    assert frame["bear_score"].max() <= 10.001
    assert frame["bull_score"].min() >= 0.0


def test_buy_and_sell_never_simultaneous():
    df = _toy_frame(400)
    cfg = ps.IndicatorConfig(preset_params=resolve_preset("Default", 60))
    frame = ps.evaluate(df, cfg)
    both = frame["buy"] & frame["sell"]
    assert not both.any()


def test_tp_sl_detector_long_full_path():
    candle = pd.Series({"high": 110.0, "low": 95.0, "close": 105.0})
    trade = {
        "dir": "long",
        "entry": 100.0, "sl": 95.0,
        "tp1": 102.0, "tp2": 104.0, "tp3": 108.0,
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
    }
    events = ps.detect_tp_sl_hits(candle, trade)
    assert events == ["tp1", "tp2", "tp3", "sl"]


def test_tp_sl_detector_short_sl():
    # Wide-range short candle that pierces tp3 and then stops out.
    candle = pd.Series({"high": 105.0, "low": 93.0, "close": 100.0})
    trade = {
        "dir": "short",
        "entry": 100.0, "sl": 104.0,
        "tp1": 98.0, "tp2": 96.0, "tp3": 94.0,
        "tp1_hit": True, "tp2_hit": True, "tp3_hit": False,
    }
    events = ps.detect_tp_sl_hits(candle, trade)
    assert "tp3" in events
    assert "sl" in events
    assert "tp1" not in events  # already hit


def test_build_trade_plan_long_orderings():
    df = _toy_frame(400)
    cfg = ps.IndicatorConfig(preset_params=resolve_preset("Default", 60))
    frame = ps.evaluate(df, cfg)
    plan = ps.build_trade_plan(frame, len(frame) - 1, "long", cfg)
    assert plan.sl < plan.entry < plan.tp1 < plan.tp2 < plan.tp3


def test_build_trade_plan_short_orderings():
    df = _toy_frame(400)
    cfg = ps.IndicatorConfig(preset_params=resolve_preset("Default", 60))
    frame = ps.evaluate(df, cfg)
    plan = ps.build_trade_plan(frame, len(frame) - 1, "short", cfg)
    assert plan.tp3 < plan.tp2 < plan.tp1 < plan.entry < plan.sl
