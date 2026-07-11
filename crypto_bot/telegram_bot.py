"""Low-level Telegram Bot API calls: sending messages and polling for
inbound updates. No business logic here -- see telegram_commands.py for
command parsing/dispatch.
"""

import requests

from crypto_bot.config import Settings

TELEGRAM_API = "https://api.telegram.org"


class TelegramError(Exception):
    """Raised when a Telegram API call fails. Never includes the bot
    token in its message, even though the token is part of the URL.
    """


def send_message(settings: Settings, text: str, reply_markup: dict | None = None) -> None:
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    resp = requests.post(url, json=payload)
    if not resp.ok:
        raise TelegramError(f"sendMessage failed: {resp.status_code}")


def get_updates(settings: Settings, offset: int) -> list[dict]:
    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": 0})
    if not resp.ok:
        raise TelegramError(f"getUpdates failed: {resp.status_code}")
    return resp.json()["result"]
