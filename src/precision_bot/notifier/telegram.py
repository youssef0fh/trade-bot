"""Minimal Telegram Bot API client.

Setup:
  1. Talk to @BotFather on Telegram, /newbot, get the token.
  2. Get your chat id: send any message to the bot, then GET
     https://api.telegram.org/bot<TOKEN>/getUpdates and read chat.id.
     For a channel: add the bot as an admin and use the channel @username or its numeric id.
"""

from __future__ import annotations

import logging

import httpx


log = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self._http = httpx.Client(timeout=timeout)

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        resp = self._http.post(url, json=payload)
        if resp.status_code != 200:
            log.error("telegram sendMessage failed: %s %s", resp.status_code, resp.text)
            resp.raise_for_status()

    def close(self) -> None:
        self._http.close()


def format_entry(
    direction: str,  # "BUY" | "SELL"
    grade: str,
    ticker: str,
    tf: str,
    price: float,
    sl: float,
    tp1: float,
    tp2: float,
    tp3: float,
    score: float,
) -> str:
    """Mirrors the Pine `textMsg` format (line 873/885)."""
    arrow = "🟢" if direction == "BUY" else "🔴"
    return (
        f"{arrow} {direction} {grade} | {ticker} | TF: {tf} | "
        f"Price: {price:g} | SL: {sl:g} | "
        f"TP1: {tp1:g} | TP2: {tp2:g} | TP3: {tp3:g} | "
        f"Score: {score:.1f}"
    )


def format_event(event: str, ticker: str, tf: str, price: float) -> str:
    """Mirrors the Pine TP/SL alert format (lines 890-905)."""
    icons = {"tp1": "🎯 TP1 HIT", "tp2": "🎯 TP2 HIT", "tp3": "🏆 TP3 HIT", "sl": "🛑 SL HIT"}
    label = icons.get(event, event.upper())
    return f"{label} | {ticker} | TF: {tf} | Price: {price:g}"
