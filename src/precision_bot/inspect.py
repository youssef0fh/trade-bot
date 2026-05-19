"""`precision-bot inspect` — dump the full indicator state of recent closed
candles for a single (symbol, timeframe). Use this to compare values against
TradingView side-by-side.

The output mirrors the variables in tv_scipts/pricision_sniper_tv.txt so you
can pin TradingView on the same bar and check each row.
"""

from __future__ import annotations

import argparse

import pandas as pd

from .data import exchange
from .indicator import precision_sniper as ps
from .indicator.presets import resolve_preset, resolved_name


def _fmt(v: float, digits: int = 4) -> str:
    if pd.isna(v):
        return "—"
    return f"{v:.{digits}f}"


def _print_bar(row: pd.Series, idx: pd.Timestamp, score_threshold: int) -> None:
    bull = float(row["bull_score"])
    bear = float(row["bear_score"])
    print(f"\n┌─ {idx}  (close = {_fmt(row['close'], 4)})")
    print(f"│  EMA fast/slow/trend : {_fmt(row['ema_fast'])}  {_fmt(row['ema_slow'])}  {_fmt(row['ema_trend'])}")
    print(f"│  RSI                  : {_fmt(row['rsi'], 2)}")
    print(f"│  MACD / signal / hist : {_fmt(row['macd'])}  {_fmt(row['macd_sig'])}  {_fmt(row['macd_hist'])}")
    print(f"│  VWAP                 : {_fmt(row['vwap'])}")
    print(f"│  ATR                  : {_fmt(row['atr'])}")
    print(f"│  ADX  +DI  -DI        : {_fmt(row['adx'], 2)}  {_fmt(row['di_plus'], 2)}  {_fmt(row['di_minus'], 2)}")
    print(f"│  HTF bias             : {int(row['htf_bias']):+d}")
    print(f"│  Volume > 1.2×SMA20   : {bool(row['vol_above_avg'])}")
    print(f"│")
    print(f"│  Bull score           : {bull:.1f}   grade={ps.get_grade(bull)}")
    print(f"│  Bear score           : {bear:.1f}   grade={ps.get_grade(bear)}")
    print(f"│  Min score (preset)   : {score_threshold}")
    print(f"│  ema_bull_cross / momentum / rsi_not_ob : "
          f"{bool(row['ema_bull_cross'])} / {bool(row['bull_momentum'])} / {bool(row['rsi_not_ob'])}")
    print(f"│  ema_bear_cross / momentum / rsi_not_os : "
          f"{bool(row['ema_bear_cross'])} / {bool(row['bear_momentum'])} / {bool(row['rsi_not_os'])}")
    print(f"│  → BUY  : {bool(row['buy'])}")
    print(f"│  → SELL : {bool(row['sell'])}")
    print(f"└─")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="precision-bot inspect",
        description="Print Precision Sniper indicator values for the last N closed bars (for TradingView parity checks).",
    )
    parser.add_argument("symbol", help="e.g. BTC/USDT")
    parser.add_argument("timeframe", help="e.g. 1h, 15m, 4h")
    parser.add_argument("--preset", default="Auto",
                        help="Auto | Conservative | Default | Aggressive | Scalping | Swing | Crypto 24/7 | Custom")
    parser.add_argument("--grade-filter", default="All", help='"All" | "A+ and A" | "A+ Only"')
    parser.add_argument("--no-hide-c", action="store_true", help="don't filter out C-grade signals")
    parser.add_argument("--htf", default=None, help='HTF for bias; default = auto from TF; "off" disables')
    parser.add_argument("--bars", type=int, default=3, help="how many recent closed bars to print")
    parser.add_argument("--limit", type=int, default=500, help="how many candles to fetch for warmup")
    args = parser.parse_args(argv)

    tf_minutes = exchange.tf_to_minutes(args.timeframe)
    params = resolve_preset(args.preset, tf_minutes)
    cfg = ps.IndicatorConfig(
        preset_params=params,
        grade_filter=args.grade_filter,
        hide_c_grade=not args.no_hide_c,
    )

    df = exchange.fetch_ohlcv(args.symbol, args.timeframe, limit=args.limit)
    if df.empty:
        print("No closed candles returned.")
        return 1

    if args.htf == "off":
        htf_df = None
        htf_label = "off"
    else:
        htf = args.htf or exchange.suggest_htf(args.timeframe)
        htf_df = exchange.fetch_ohlcv(args.symbol, htf, limit=args.limit) if htf else None
        htf_label = htf or "—"

    frame = ps.evaluate(df, cfg, htf_df=htf_df, last_direction=0)

    print(f"Symbol   : {args.symbol}")
    print(f"TF       : {args.timeframe}   (HTF: {htf_label})")
    print(f"Preset   : {args.preset} → resolved={resolved_name(args.preset, tf_minutes)}")
    print(f"Params   : ema={params.ema_fast}/{params.ema_slow}/{params.ema_trend}  "
          f"rsi={params.rsi_len}  atr={params.atr_len}  min_score={params.min_score}  sl_mult={params.sl_mult}")
    print(f"Bars     : last {args.bars} of {len(frame)} fetched")

    for i in range(-args.bars, 0):
        _print_bar(frame.iloc[i], frame.index[i], params.min_score)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
