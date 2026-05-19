"""JSON-file state for dedup and open-trade tracking.

State shape (per `(symbol, tf)` key, e.g. ``"BTC/USDT|1h"``)::

    {
      "last_closed_bar_ts": 1747315200,   # unix seconds, UTC
      "last_alert_bar_ts":  1747311600,
      "last_direction":     1,            # 1 long, -1 short, 0 none
      "open_trade": {
        "dir": "long",
        "entry": 65432.1,
        "sl": 64800.0,
        "tp1": 66000.0, "tp2": 66500.0, "tp3": 67100.0,
        "tp1_hit": false, "tp2_hit": false, "tp3_hit": false,
        "entry_bar_ts": 1747311600
      }
    }
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def key_for(symbol: str, tf: str) -> str:
    return f"{symbol}|{tf}"


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        return {}


def save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def entry_for(state: dict[str, Any], symbol: str, tf: str) -> dict[str, Any]:
    return state.setdefault(
        key_for(symbol, tf),
        {
            "last_closed_bar_ts": 0,
            "last_alert_bar_ts": 0,
            "last_direction": 0,
            "open_trade": None,
        },
    )
