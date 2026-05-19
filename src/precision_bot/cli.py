"""Precision Sniper alert bot — entrypoint.

Run once: ``python -m precision_bot.cli --config config/symbols.yaml``.
Designed for cron / GitHub Actions; no persistent process.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import state as state_mod
from .config import BotConfig, WatchlistRow, load_config, merge_row
from .data import exchange
from .indicator import precision_sniper as ps
from .indicator.presets import resolve_preset, resolved_name
from .notifier.telegram import TelegramClient, format_entry, format_event


log = logging.getLogger("precision_bot")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _send_ping(cfg: BotConfig) -> int:
    """Send a single diagnostic message and exit. Lets the ping-telegram
    workflow verify creds + reachability without waiting for a real signal.
    """
    token = os.environ.get(cfg.telegram.bot_token_env)
    chat_id = os.environ.get(cfg.telegram.chat_id_env)
    if not token or not chat_id:
        log.error("ping: missing %s / %s in environment", cfg.telegram.bot_token_env, cfg.telegram.chat_id_env)
        return 2

    sha = os.environ.get("GITHUB_SHA", "local")[:7]
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    text = f"🔔 trade-bot ping\nsha: {sha}\nrun: {run_id}\nutc: {now}"

    client = TelegramClient(token, chat_id)
    try:
        client.send(text)
    except Exception as e:
        log.error("ping: telegram send failed: %s", e)
        return 1
    finally:
        client.close()
    log.info("ping sent (sha=%s run=%s)", sha, run_id)
    return 0


def _build_indicator_cfg(row_settings: dict[str, Any]) -> ps.IndicatorConfig:
    tf_minutes = exchange.tf_to_minutes(row_settings["timeframe"])
    params = resolve_preset(row_settings["preset"], tf_minutes)
    return ps.IndicatorConfig(
        preset_params=params,
        grade_filter=row_settings["grade_filter"],
        hide_c_grade=row_settings["hide_c_grade"],
        tp1_rr=row_settings["tp1_rr"],
        tp2_rr=row_settings["tp2_rr"],
        tp3_rr=row_settings["tp3_rr"],
        use_structure_sl=row_settings["use_structure_sl"],
        swing_lookback=row_settings["swing_lookback"],
    )


def _fetch_for_row(row_settings: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    symbol = row_settings["symbol"]
    tf = row_settings["timeframe"]
    df = exchange.fetch_ohlcv(symbol, tf, limit=500)

    htf_setting = row_settings.get("htf")
    if htf_setting == "off":
        htf_df = None
    else:
        htf = htf_setting or exchange.suggest_htf(tf)
        htf_df = exchange.fetch_ohlcv(symbol, htf, limit=500) if htf else None
    return df, htf_df


def _process_row(
    row: WatchlistRow,
    defaults_dict: dict[str, Any],
    state: dict[str, Any],
    notifier: TelegramClient | None,
    dry_run: bool,
) -> tuple[list[str], bool]:
    """Process one (symbol, timeframe) row. Returns ``(messages, errored)``:
    ``messages`` is the list of strings sent (or that would have been sent in
    ``--dry-run``), and ``errored`` is True iff the row failed in a way that
    should surface to the workflow's exit code.
    """
    msgs: list[str] = []
    row_settings = {**defaults_dict, **{}}
    # Re-merge with proper override semantics. defaults_dict already contains
    # `events`; we then apply row overrides via merge_row by reconstructing.
    from .config import Defaults
    row_settings = merge_row(Defaults(**defaults_dict), row)

    symbol = row_settings["symbol"]
    tf = row_settings["timeframe"]
    events = row_settings["events"]

    entry_state = state_mod.entry_for(state, symbol, tf)

    try:
        df, htf_df = _fetch_for_row(row_settings)
    except Exception as e:
        log.error("[%s %s] fetch failed: %s", symbol, tf, e)
        return msgs, True

    if df.empty:
        log.warning("[%s %s] no closed candles returned", symbol, tf)
        return msgs, False

    last_bar_ts = int(df.index[-1].timestamp())
    if last_bar_ts <= entry_state["last_closed_bar_ts"]:
        log.info("[%s %s] no new closed bar (latest=%s)", symbol, tf, df.index[-1])
        return msgs, False

    cfg = _build_indicator_cfg(row_settings)
    frame = ps.evaluate(df, cfg, htf_df=htf_df, last_direction=entry_state["last_direction"])
    last = frame.iloc[-1]

    log.info(
        "[%s %s] bar=%s close=%s bull=%.1f bear=%.1f buy=%s sell=%s preset=%s",
        symbol, tf, df.index[-1], last["close"], last["bull_score"], last["bear_score"],
        bool(last["buy"]), bool(last["sell"]),
        resolved_name(row_settings["preset"], exchange.tf_to_minutes(tf)),
    )

    # 1) TP/SL events on the open trade (evaluated on the new bar).
    open_trade = entry_state.get("open_trade")
    if open_trade and any(events[k] for k in ("tp1", "tp2", "tp3", "sl")):
        hits = ps.detect_tp_sl_hits(last, open_trade)
        for ev in hits:
            if ev == "sl":
                if events["sl"]:
                    msgs.append(format_event("sl", symbol, tf, float(last["close"])))
                entry_state["open_trade"] = None
                entry_state["last_direction"] = 0
                break
            flag = f"{ev}_hit"
            if open_trade.get(flag):
                continue
            open_trade[flag] = True
            if events[ev]:
                msgs.append(format_event(ev, symbol, tf, float(last["close"])))

    # 2) Entry signal on this bar.
    if events["entry"] and (bool(last["buy"]) or bool(last["sell"])):
        direction = "long" if last["buy"] else "short"
        plan = ps.build_trade_plan(frame, len(frame) - 1, direction, cfg)
        score = float(last["bull_score"] if direction == "long" else last["bear_score"])
        grade = ps.get_grade(score)
        msgs.append(
            format_entry(
                "BUY" if direction == "long" else "SELL",
                grade, symbol, tf,
                plan.entry, plan.sl, plan.tp1, plan.tp2, plan.tp3, score,
            )
        )
        entry_state["open_trade"] = {
            "dir": direction,
            "entry": plan.entry,
            "sl": plan.sl,
            "tp1": plan.tp1, "tp2": plan.tp2, "tp3": plan.tp3,
            "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
            "entry_bar_ts": last_bar_ts,
        }
        entry_state["last_direction"] = 1 if direction == "long" else -1
        entry_state["last_alert_bar_ts"] = last_bar_ts

    entry_state["last_closed_bar_ts"] = last_bar_ts

    if notifier and not dry_run:
        for m in msgs:
            notifier.send(m)
    for m in msgs:
        log.info("[%s %s] %s", symbol, tf, m)
    return msgs, False


def run(config_path: Path, state_path: Path, dry_run: bool, only: list[tuple[str, str]] | None = None) -> int:
    cfg = load_config(config_path)
    state = state_mod.load(state_path)

    token = os.environ.get(cfg.telegram.bot_token_env)
    chat_id = os.environ.get(cfg.telegram.chat_id_env)
    notifier: TelegramClient | None = None
    if dry_run:
        log.info("dry-run: telegram disabled")
    elif not token or not chat_id:
        log.warning(
            "telegram credentials missing (env %s / %s) — running without notifications",
            cfg.telegram.bot_token_env, cfg.telegram.chat_id_env,
        )
    else:
        notifier = TelegramClient(token, chat_id)

    defaults_dict = cfg.defaults.model_dump()
    rows = cfg.watchlist
    if only:
        match = set(only)
        rows = [r for r in rows if (r.symbol, r.timeframe) in match]
        if not rows:
            log.error("no watchlist rows match --symbol/--tf filter: %s", only)
            return 2

    total = 0
    errored = 0
    for row in rows:
        sent, row_errored = _process_row(row, defaults_dict, state, notifier, dry_run)
        total += len(sent)
        if row_errored:
            errored += 1

    state_mod.save(state_path, state)
    if notifier:
        notifier.close()

    log.info("done — %d message(s) emitted across %d row(s)", total, len(rows))
    if errored:
        log.error("%d of %d row(s) failed — exiting non-zero so the workflow surfaces it", errored, len(rows))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Precision Sniper Telegram alert bot")
    parser.add_argument("--config", type=Path, default=Path("config/symbols.yaml"))
    parser.add_argument("--state", type=Path, default=Path("state/state.json"))
    parser.add_argument("--symbol", action="append", default=[], help="filter watchlist by symbol")
    parser.add_argument("--tf", action="append", default=[], help="filter watchlist by timeframe")
    parser.add_argument("--dry-run", action="store_true", help="don't send telegram messages")
    parser.add_argument("--ping", action="store_true",
                        help="send a diagnostic Telegram message and exit; skips fetch/indicator")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    if args.ping:
        return _send_ping(load_config(args.config))

    only: list[tuple[str, str]] | None = None
    if args.symbol and args.tf:
        if len(args.symbol) != len(args.tf):
            log.error("--symbol and --tf must be supplied in matched pairs")
            return 2
        only = list(zip(args.symbol, args.tf))
    elif args.symbol or args.tf:
        log.error("--symbol and --tf must both be supplied (paired)")
        return 2

    return run(args.config, args.state, args.dry_run, only)


if __name__ == "__main__":
    sys.exit(main())
