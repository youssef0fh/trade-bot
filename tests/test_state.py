import json
from pathlib import Path

from precision_bot import state as state_mod


def test_load_missing_returns_empty(tmp_path: Path):
    assert state_mod.load(tmp_path / "missing.json") == {}


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "s.json"
    data = {"BTC/USDT|1h": {"last_closed_bar_ts": 1, "last_direction": 1}}
    state_mod.save(path, data)
    assert state_mod.load(path) == data


def test_entry_for_initializes_default(tmp_path: Path):
    state = {}
    entry = state_mod.entry_for(state, "BTC/USDT", "1h")
    assert entry["last_closed_bar_ts"] == 0
    assert entry["last_direction"] == 0
    assert entry["open_trade"] is None
    assert "BTC/USDT|1h" in state


def test_save_is_atomic(tmp_path: Path):
    path = tmp_path / "s.json"
    state_mod.save(path, {"a": 1})
    state_mod.save(path, {"a": 2})
    assert json.loads(path.read_text())["a"] == 2
    # No leftover temp files.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".state-")]
    assert leftovers == []
