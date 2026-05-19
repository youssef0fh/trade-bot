"""YAML config loader + validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class EventFlags(BaseModel):
    entry: bool = True
    tp1: bool = True
    tp2: bool = True
    tp3: bool = True
    sl: bool = True


class TelegramConfig(BaseModel):
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"


class Defaults(BaseModel):
    exchange: str = "binance"
    preset: str = "Auto"
    grade_filter: str = "All"  # "All" | "A+ and A" | "A+ Only"
    hide_c_grade: bool = True
    use_structure_sl: bool = True
    swing_lookback: int = 10
    tp1_rr: float = 1.0
    tp2_rr: float = 2.0
    tp3_rr: float = 3.0
    htf: str | None = None  # None = auto-select per data/binance.DEFAULT_HTF; "off" = disable
    events: EventFlags = Field(default_factory=EventFlags)


class WatchlistRow(BaseModel):
    symbol: str
    timeframe: str
    preset: str | None = None
    grade_filter: str | None = None
    hide_c_grade: bool | None = None
    use_structure_sl: bool | None = None
    swing_lookback: int | None = None
    tp1_rr: float | None = None
    tp2_rr: float | None = None
    tp3_rr: float | None = None
    htf: str | None = None
    events: dict[str, bool] | None = None


class BotConfig(BaseModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    defaults: Defaults = Field(default_factory=Defaults)
    watchlist: list[WatchlistRow]


def load_config(path: Path) -> BotConfig:
    raw = yaml.safe_load(path.read_text())
    return BotConfig.model_validate(raw)


def merge_row(defaults: Defaults, row: WatchlistRow) -> dict[str, Any]:
    """Resolve a watchlist row's effective settings, applying per-row overrides
    on top of defaults. Returns a plain dict for ergonomic access in the runner.
    """
    out = defaults.model_dump()
    for field in (
        "preset",
        "grade_filter",
        "hide_c_grade",
        "use_structure_sl",
        "swing_lookback",
        "tp1_rr",
        "tp2_rr",
        "tp3_rr",
        "htf",
    ):
        val = getattr(row, field)
        if val is not None:
            out[field] = val
    if row.events:
        events = out["events"]
        events.update(row.events)
        out["events"] = events
    out["symbol"] = row.symbol
    out["timeframe"] = row.timeframe
    return out
