from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from crypto_bot import telegram_bot
from crypto_bot.config import Settings

SETTINGS = Settings(
    alpaca_api_key="dummy-key",
    alpaca_secret_key="dummy-secret",
    alpaca_paper=True,
    alpaca_base_url="https://paper-api.alpaca.markets",
    auto_entry_enabled=False,
    auto_entry_notional=Decimal("10"),
    auto_entry_total_cap=Decimal("1000"),
    auto_entry_daily_cap=Decimal("200"),
    telegram_bot_token="bot-token",
    telegram_chat_id="12345",
    default_order_notional=Decimal("10"),
    default_order_symbol="BTC/USD",
)


def test_send_message_posts_to_correct_url_and_payload():
    with patch("crypto_bot.telegram_bot.requests.post") as mock_post:
        mock_post.return_value = Mock(ok=True)

        telegram_bot.send_message(SETTINGS, "hello")

        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.telegram.org/botbot-token/sendMessage"
        assert kwargs["json"] == {"chat_id": "12345", "text": "hello"}


def test_send_message_includes_reply_markup_when_given():
    with patch("crypto_bot.telegram_bot.requests.post") as mock_post:
        mock_post.return_value = Mock(ok=True)
        keyboard = {"keyboard": [["/positions"]], "resize_keyboard": True}

        telegram_bot.send_message(SETTINGS, "hello", reply_markup=keyboard)

        args, kwargs = mock_post.call_args
        assert kwargs["json"]["reply_markup"] == keyboard


def test_send_message_omits_reply_markup_when_not_given():
    with patch("crypto_bot.telegram_bot.requests.post") as mock_post:
        mock_post.return_value = Mock(ok=True)

        telegram_bot.send_message(SETTINGS, "hello")

        args, kwargs = mock_post.call_args
        assert "reply_markup" not in kwargs["json"]


def test_send_message_raises_telegram_error_on_failure():
    with patch("crypto_bot.telegram_bot.requests.post") as mock_post:
        mock_post.return_value = Mock(ok=False, status_code=403)

        with pytest.raises(telegram_bot.TelegramError):
            telegram_bot.send_message(SETTINGS, "hello")


def test_send_message_error_does_not_leak_bot_token():
    with patch("crypto_bot.telegram_bot.requests.post") as mock_post:
        mock_post.return_value = Mock(ok=False, status_code=403)

        with pytest.raises(telegram_bot.TelegramError) as exc_info:
            telegram_bot.send_message(SETTINGS, "hello")

        assert "bot-token" not in str(exc_info.value)


def test_get_updates_returns_result_list():
    with patch("crypto_bot.telegram_bot.requests.get") as mock_get:
        mock_get.return_value = Mock(ok=True, json=lambda: {"result": [{"update_id": 1}]})

        result = telegram_bot.get_updates(SETTINGS, offset=1)

        assert result == [{"update_id": 1}]
        args, kwargs = mock_get.call_args
        assert args[0] == "https://api.telegram.org/botbot-token/getUpdates"
        assert kwargs["params"]["offset"] == 1


def test_get_updates_raises_telegram_error_on_failure():
    with patch("crypto_bot.telegram_bot.requests.get") as mock_get:
        mock_get.return_value = Mock(ok=False, status_code=500)

        with pytest.raises(telegram_bot.TelegramError):
            telegram_bot.get_updates(SETTINGS, offset=0)
