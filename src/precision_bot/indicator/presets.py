"""Preset profiles ported from tv_scipts/pricision_sniper_tv.txt lines 107-192."""

from __future__ import annotations

from dataclasses import dataclass

# Timeframes the Pine "Auto" preset would resolve to. Pine resolves on
# `timeframe.in_seconds() / 60.0` brackets; we mirror exactly the same brackets.
AUTO_BRACKETS_MINUTES = (
    (5, "Scalping"),
    (60, "Default"),
    (240, "Aggressive"),
)
AUTO_FALLBACK = "Swing"

PRESET_NAMES = (
    "Auto",
    "Conservative",
    "Default",
    "Aggressive",
    "Scalping",
    "Swing",
    "Crypto 24/7",
    "Custom",
)


@dataclass(frozen=True)
class PresetParams:
    ema_fast: int
    ema_slow: int
    ema_trend: int
    rsi_len: int
    atr_len: int
    min_score: int
    sl_mult: float


# Custom input defaults (from Pine input declarations, lines 42-67).
CUSTOM_DEFAULTS = PresetParams(
    ema_fast=9,
    ema_slow=21,
    ema_trend=55,
    rsi_len=13,
    atr_len=14,
    min_score=5,
    sl_mult=1.5,
)

_PRESETS: dict[str, PresetParams] = {
    "Scalping":     PresetParams(5,  13, 34, 8,  10, 4, 0.8),
    "Aggressive":   PresetParams(8,  18, 50, 11, 12, 3, 1.2),
    "Default":      PresetParams(9,  21, 55, 13, 14, 5, 1.5),
    "Conservative": PresetParams(12, 26, 89, 14, 14, 7, 2.0),
    "Swing":        PresetParams(13, 34, 89, 21, 20, 6, 2.5),
    "Crypto 24/7":  PresetParams(9,  21, 55, 14, 20, 5, 2.0),
}


def resolve_auto(tf_minutes: float) -> str:
    """Pine `Auto` preset selector — line 110-119."""
    for upper, name in AUTO_BRACKETS_MINUTES:
        if tf_minutes <= upper:
            return name
    return AUTO_FALLBACK


def resolve_preset(preset: str, tf_minutes: float, custom: PresetParams | None = None) -> PresetParams:
    if preset == "Auto":
        preset = resolve_auto(tf_minutes)
    if preset == "Custom":
        return custom or CUSTOM_DEFAULTS
    if preset not in _PRESETS:
        raise ValueError(f"unknown preset: {preset!r}")
    return _PRESETS[preset]


def resolved_name(preset: str, tf_minutes: float) -> str:
    return resolve_auto(tf_minutes) if preset == "Auto" else preset
