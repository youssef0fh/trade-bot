"""Port of the Precision Sniper entry / TP / SL logic from
tv_scipts/pricision_sniper_tv.txt. Only the headless-bot–relevant pieces are
ported: plotting, dashboard, watermark, backtest tracker, and trailing-stop
tracking inside open trades are out of scope (the bot tracks open trades in
state and emits TP/SL events independently).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import indicators as ind
from .presets import PresetParams


GRADE_THRESHOLDS = (
    (8.0, "A+"),
    (6.5, "A"),
    (5.0, "B"),
)


def get_grade(score: float) -> str:
    """Pine `getGrade` — line 269-270."""
    for thresh, name in GRADE_THRESHOLDS:
        if score >= thresh:
            return name
    return "C"


def passes_grade_filter(score: float, grade_filter: str, hide_c: bool) -> bool:
    """Pine `passesGradeFilter` — lines 272-279."""
    if grade_filter == "A+ Only":
        grade_ok = score >= 8.0
    elif grade_filter == "A+ and A":
        grade_ok = score >= 6.5
    else:  # "All"
        grade_ok = True
    c_ok = (score >= 5.0) if hide_c else True
    return grade_ok and c_ok


@dataclass
class SignalRow:
    """One bar's evaluated state. Times are UTC pandas Timestamps."""
    bar_ts: pd.Timestamp
    close: float
    high: float
    low: float
    bull_score: float
    bear_score: float
    buy: bool      # raw confirmed buy (passes all filters)
    sell: bool     # raw confirmed sell


@dataclass
class TradePlan:
    direction: str        # "long" | "short"
    entry: float
    sl: float
    tp1: float
    tp2: float
    tp3: float


@dataclass
class IndicatorConfig:
    preset_params: PresetParams
    grade_filter: str = "All"
    hide_c_grade: bool = True
    tp1_rr: float = 1.0
    tp2_rr: float = 2.0
    tp3_rr: float = 3.0
    use_structure_sl: bool = True
    swing_lookback: int = 10


def _compute_frame(
    df: pd.DataFrame,
    htf_df: pd.DataFrame | None,
    cfg: IndicatorConfig,
) -> pd.DataFrame:
    """Compute every indicator and score column for the entire OHLCV frame.

    `df` must have a UTC DatetimeIndex and columns: open, high, low, close, volume.
    `htf_df` (optional) is the higher-timeframe OHLCV used for the HTF bias score.
    """
    p = cfg.preset_params
    out = df.copy()

    out["ema_fast"]  = ind.ema(df["close"], p.ema_fast)
    out["ema_slow"]  = ind.ema(df["close"], p.ema_slow)
    out["ema_trend"] = ind.ema(df["close"], p.ema_trend)
    out["atr"]       = ind.atr(df, p.atr_len)
    out["rsi"]       = ind.rsi(df["close"], p.rsi_len)
    macd_line, signal_line, hist = ind.macd(df["close"], 12, 26, 9)
    out["macd"]      = macd_line
    out["macd_sig"]  = signal_line
    out["macd_hist"] = hist
    out["vwap"]      = ind.vwap_daily(df)

    vol_sma = ind.sma(df["volume"], 20)
    has_volume = df["volume"] > 0
    out["vol_above_avg"] = ((df["volume"] > vol_sma * 1.2) & has_volume).fillna(False)
    # Pine: when no volume series available, treat as True (line 310).
    out.loc[~has_volume, "vol_above_avg"] = True

    plus_di, minus_di, adx = ind.dmi(df, 14, 14)
    out["di_plus"] = plus_di
    out["di_minus"] = minus_di
    out["adx"] = adx
    out["strong_trend"] = adx > 20

    # HTF bias (line 327-332). Pine pulls the *previous* HTF EMA value with
    # lookahead_on, which equals "the last fully-closed HTF candle". We mirror
    # by computing EMAs on htf_df and forward-filling onto df's index, shifted
    # by one HTF bar so we never use the in-progress HTF bar.
    if htf_df is not None and len(htf_df) > 0:
        htf_ema_fast = ind.ema(htf_df["close"], p.ema_fast).shift(1)
        htf_ema_slow = ind.ema(htf_df["close"], p.ema_slow).shift(1)
        out["htf_ema_fast"] = htf_ema_fast.reindex(df.index, method="ffill")
        out["htf_ema_slow"] = htf_ema_slow.reindex(df.index, method="ffill")
    else:
        out["htf_ema_fast"] = out["ema_fast"].shift(1)
        out["htf_ema_slow"] = out["ema_slow"].shift(1)

    out["htf_bias"] = 0
    out.loc[out["htf_ema_fast"] > out["htf_ema_slow"], "htf_bias"] = 1
    out.loc[out["htf_ema_fast"] < out["htf_ema_slow"], "htf_bias"] = -1

    # Confluence score (lines 342-364).
    out["bull_score"] = (
        (out["ema_fast"] > out["ema_slow"]).astype(float)
        + (out["close"] > out["ema_trend"]).astype(float)
        + ((out["rsi"] > 50) & (out["rsi"] < 75)).astype(float)
        + (out["macd_hist"] > 0).astype(float)
        + (out["macd"] > out["macd_sig"]).astype(float)
        + (out["close"] > out["vwap"]).astype(float)
        + out["vol_above_avg"].astype(float)
        + (out["strong_trend"] & (out["di_plus"] > out["di_minus"])).astype(float)
        + (out["htf_bias"] == 1).astype(float) * 1.5
        + (out["close"] > out["ema_fast"]).astype(float) * 0.5
    )
    out["bear_score"] = (
        (out["ema_fast"] < out["ema_slow"]).astype(float)
        + (out["close"] < out["ema_trend"]).astype(float)
        + ((out["rsi"] < 50) & (out["rsi"] > 25)).astype(float)
        + (out["macd_hist"] < 0).astype(float)
        + (out["macd"] < out["macd_sig"]).astype(float)
        + (out["close"] < out["vwap"]).astype(float)
        + out["vol_above_avg"].astype(float)
        + (out["strong_trend"] & (out["di_minus"] > out["di_plus"])).astype(float)
        + (out["htf_bias"] == -1).astype(float) * 1.5
        + (out["close"] < out["ema_fast"]).astype(float) * 0.5
    )

    # Entry triggers (lines 370-380).
    out["ema_bull_cross"] = ind.crossover(out["ema_fast"], out["ema_slow"])
    out["ema_bear_cross"] = ind.crossunder(out["ema_fast"], out["ema_slow"])
    out["bull_momentum"] = (out["close"] > out["ema_fast"]) & (out["close"] > out["ema_slow"])
    out["bear_momentum"] = (out["close"] < out["ema_fast"]) & (out["close"] < out["ema_slow"])
    out["rsi_not_ob"] = out["rsi"] < 75
    out["rsi_not_os"] = out["rsi"] > 25

    return out


def _state_machine_signals(
    frame: pd.DataFrame, cfg: IndicatorConfig
) -> pd.DataFrame:
    """Apply Pine's `lastDirection` state machine (lines 382-395) and
    grade/score filters to produce final BUY/SELL flags per bar.
    """
    p = cfg.preset_params
    score_threshold = p.min_score

    bull_pass = (
        frame["bull_score"] >= score_threshold
    ) & frame["bull_score"].apply(
        lambda s: passes_grade_filter(float(s), cfg.grade_filter, cfg.hide_c_grade)
    )
    bear_pass = (
        frame["bear_score"] >= score_threshold
    ) & frame["bear_score"].apply(
        lambda s: passes_grade_filter(float(s), cfg.grade_filter, cfg.hide_c_grade)
    )

    raw_buy = frame["ema_bull_cross"] & frame["bull_momentum"] & frame["rsi_not_ob"] & bull_pass
    raw_sell = frame["ema_bear_cross"] & frame["bear_momentum"] & frame["rsi_not_os"] & bear_pass

    # last_direction state machine: 0 = no trade, 1 = long, -1 = short.
    # SL hit elsewhere will reset to 0, but that's a runtime/state concern (not
    # vectorizable here). For the historical evaluation we approximate by
    # alternating directions, which matches Pine when there is no SL reset —
    # the bot only reports the latest-bar signal anyway and dedupes via state.
    last_dir = 0
    buy = [False] * len(frame)
    sell = [False] * len(frame)
    rb = raw_buy.to_numpy()
    rs = raw_sell.to_numpy()
    for i in range(len(frame)):
        if rb[i] and last_dir != 1:
            buy[i] = True
            last_dir = 1
        elif rs[i] and last_dir != -1:
            sell[i] = True
            last_dir = -1
    frame = frame.copy()
    frame["buy"] = buy
    frame["sell"] = sell
    return frame


def evaluate(
    df: pd.DataFrame,
    cfg: IndicatorConfig,
    htf_df: pd.DataFrame | None = None,
    last_direction: int = 0,
) -> pd.DataFrame:
    """Compute the full indicator state for ``df``. The last row corresponds
    to the most recent closed candle (caller is responsible for dropping the
    in-progress bar). Returns the frame with score and buy/sell columns.

    ``last_direction`` lets the caller seed the state machine from persisted
    state — when the last open trade was long, we won't re-emit BUY signals
    until a SELL or SL reset occurs.
    """
    frame = _compute_frame(df, htf_df, cfg)
    frame = _state_machine_signals(frame, cfg)
    if last_direction != 0:
        # Suppress immediate same-direction signals at the very tail; the
        # in-frame state machine assumed last_dir=0 at the start. We only
        # need to correct the *last* row for the bot's purposes.
        last_idx = frame.index[-1]
        if last_direction == 1 and frame.at[last_idx, "buy"]:
            frame.at[last_idx, "buy"] = False
        if last_direction == -1 and frame.at[last_idx, "sell"]:
            frame.at[last_idx, "sell"] = False
    return frame


def build_trade_plan(
    frame: pd.DataFrame,
    bar_idx: int,
    direction: str,
    cfg: IndicatorConfig,
) -> TradePlan:
    """Replicates Pine TP/SL setup at the signal bar (lines 414-456)."""
    row = frame.iloc[bar_idx]
    entry = float(row["close"])
    atr_val = float(row["atr"])
    risk_atr = atr_val * cfg.preset_params.sl_mult
    is_long = direction == "long"

    atr_stop = entry - risk_atr if is_long else entry + risk_atr
    if cfg.use_structure_sl:
        lookback = cfg.swing_lookback
        # Pine: getSwingLow/High over current bar + lookback prior bars (line 240/247).
        window_lo = frame["low"].iloc[max(0, bar_idx - lookback): bar_idx + 1].min()
        window_hi = frame["high"].iloc[max(0, bar_idx - lookback): bar_idx + 1].max()
        if is_long:
            struct_stop = float(window_lo) - atr_val * 0.2
            final_stop = max(atr_stop, struct_stop)
        else:
            struct_stop = float(window_hi) + atr_val * 0.2
            final_stop = min(atr_stop, struct_stop)
        min_dist = atr_val * 0.5
        if abs(entry - final_stop) < min_dist:
            final_stop = entry - min_dist if is_long else entry + min_dist
        sl = final_stop
    else:
        sl = atr_stop

    trade_risk = abs(entry - sl)
    sign = 1.0 if is_long else -1.0
    return TradePlan(
        direction=direction,
        entry=entry,
        sl=sl,
        tp1=entry + sign * trade_risk * cfg.tp1_rr,
        tp2=entry + sign * trade_risk * cfg.tp2_rr,
        tp3=entry + sign * trade_risk * cfg.tp3_rr,
    )


def detect_tp_sl_hits(
    candle: pd.Series,
    trade: dict,
) -> list[str]:
    """Inspect a single closed candle and return any newly-hit events for an
    open trade. Mirrors Pine TP/SL detection (lines 461-493) but operates on a
    persisted trade record from the bot's state file.

    `trade` keys: dir ("long"/"short"), tp1, tp2, tp3, sl, tp1_hit, tp2_hit,
    tp3_hit.
    """
    events: list[str] = []
    high = float(candle["high"])
    low = float(candle["low"])
    is_long = trade["dir"] == "long"

    if is_long:
        if not trade.get("tp1_hit") and high >= trade["tp1"]:
            events.append("tp1")
        if not trade.get("tp2_hit") and high >= trade["tp2"]:
            events.append("tp2")
        if not trade.get("tp3_hit") and high >= trade["tp3"]:
            events.append("tp3")
        if low <= trade["sl"]:
            events.append("sl")
    else:
        if not trade.get("tp1_hit") and low <= trade["tp1"]:
            events.append("tp1")
        if not trade.get("tp2_hit") and low <= trade["tp2"]:
            events.append("tp2")
        if not trade.get("tp3_hit") and low <= trade["tp3"]:
            events.append("tp3")
        if high >= trade["sl"]:
            events.append("sl")

    return events
