# Precision Sniper → Telegram Alert Bot

A free crypto-alert bot. Ports the [Precision Sniper](tv_scipts/pricision_sniper_tv.txt) Pine v6 indicator to Python, pulls OHLCV from Binance's public REST API (no API key needed), evaluates on every closed candle, and pushes BUY / SELL / TP / SL events to a Telegram channel.

Designed to run on a GitHub Actions cron for free; migrates to any cloud cron unchanged.

## Setup

### 1. Telegram bot

1. On Telegram, message [@BotFather](https://t.me/BotFather), `/newbot`, follow prompts. Save the token.
2. Get your chat id:
   - Personal chat: message the bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and grab `chat.id`.
   - Channel: add the bot as an admin; use the channel `@username` (string) or its numeric id.

### 2. Configure watchlist

Edit [config/symbols.yaml](config/symbols.yaml). Defaults apply to every row; each row may override.

```yaml
defaults:
  preset: Auto            # Auto / Conservative / Default / Aggressive / Scalping / Swing / Crypto 24/7 / Custom
  grade_filter: All       # All / "A+ and A" / "A+ Only"
  hide_c_grade: true
  events: { entry: true, tp1: true, tp2: true, tp3: true, sl: true }

watchlist:
  - { symbol: BTC/USDT, timeframe: 1h }
  - { symbol: ETH/USDT, timeframe: 15m, preset: Scalping }
  - { symbol: SOL/USDT, timeframe: 4h, grade_filter: "A+ and A" }
```

Per-row overrides supported: `preset`, `grade_filter`, `hide_c_grade`, `htf`, `use_structure_sl`, `swing_lookback`, `tp1_rr`/`tp2_rr`/`tp3_rr`, `events`.

### 3. Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Smoke test against live data (no messages sent):
python -m precision_bot.cli --dry-run --verbose

# Real run (requires env vars):
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python -m precision_bot.cli
```

CLI flags:
- `--config PATH` — alternative YAML (default `config/symbols.yaml`)
- `--state PATH` — alternative state file (default `state/state.json`)
- `--symbol X --tf Y` — filter watchlist (repeatable; pair them)
- `--dry-run` — skip Telegram send
- `-v` — debug logging

### 4. Run on GitHub Actions (free)

1. Push this repo to GitHub.
2. Repo *Settings → Secrets and variables → Actions*: add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Repo *Settings → Actions → General → Workflow permissions*: enable *Read and write permissions* (the workflow commits state back).
4. [.github/workflows/check.yml](.github/workflows/check.yml) runs every 5 min. Trigger manually first via *Actions → precision-bot → Run workflow* to verify.

Cron granularity is 5 min, so this works cleanly for ≥5m timeframes. For 1m/3m, move to a VPS.

## How it works

```
config/symbols.yaml ──┐
                       ├─►  cli.py
state/state.json    ──┘        │
                               ├─► data/binance.py        (ccxt OHLCV)
                               ├─► indicator/precision_sniper.py   (port of Pine logic)
                               ├─► state.py               (JSON dedup + open trades)
                               └─► notifier/telegram.py   (Bot API)
```

Per `(symbol, tf)` the bot tracks `last_closed_bar_ts` and any `open_trade` so:
- An entry alert fires at most once per closed bar.
- TP1/2/3/SL alerts fire once each, as new bars cross those levels.
- A new opposing entry silently closes the prior trade.

### Score components (10 max)

The bull and bear scores each sum to ≤ 10. Components ([source](src/precision_bot/indicator/precision_sniper.py)):

| Component | Weight |
|---|---|
| EMA fast vs slow | 1.0 |
| Close vs EMA trend | 1.0 |
| RSI in bullish/bearish band (50-75 / 25-50) | 1.0 |
| MACD histogram sign | 1.0 |
| MACD line vs signal | 1.0 |
| Close vs VWAP | 1.0 |
| Volume > 1.2× SMA(20) | 1.0 |
| ADX > 20 and DI direction | 1.0 |
| HTF bias | 1.5 |
| Close vs EMA fast | 0.5 |

Grades: `A+ ≥ 8.0`, `A ≥ 6.5`, `B ≥ 5.0`, else `C` (suppressed by default).

## Migration off GitHub Actions

The bot is a plain Python CLI that reads YAML + writes JSON. To run on a VPS:

```bash
# Crontab line, every 5 minutes:
*/5 * * * * cd /opt/precision-bot && /opt/precision-bot/.venv/bin/python -m precision_bot.cli >> logs/bot.log 2>&1
```

No code changes required.

## Tests

```bash
pytest
```

Covers indicator math, preset resolution, grade boundaries, TP/SL detection, and state persistence.

## Roadmap

- v1 (this MVP): entry / TP / SL alerts.
- v2: chained checks — e.g. only emit BUY if RSI on 4h is also bullish.
- v2+: signal-history dashboard, multi-exchange data sources.
