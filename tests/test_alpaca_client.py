from decimal import Decimal
from unittest.mock import Mock

import pytest
from alpaca.common.exceptions import APIError

from crypto_bot import alpaca_client
from crypto_bot.config import PAPER_BASE_URL, LIVE_BASE_URL, Settings


def make_settings(paper=True):
    return Settings(
        alpaca_api_key="test-key",
        alpaca_secret_key="test-secret",
        alpaca_paper=paper,
        alpaca_base_url=PAPER_BASE_URL if paper else LIVE_BASE_URL,
        auto_entry_enabled=False,
        auto_entry_notional=Decimal("10"),
        auto_entry_total_cap=Decimal("1000"),
        auto_entry_daily_cap=Decimal("200"),
        telegram_bot_token="test-bot-token",
        telegram_chat_id="12345",
        default_order_notional=Decimal("10"),
        default_order_symbol="BTC/USD",
    )


def test_get_client_uses_paper_base_url_for_paper_settings():
    client = alpaca_client.get_client(make_settings(paper=True))

    assert client._base_url == PAPER_BASE_URL


def test_get_client_uses_live_base_url_for_live_settings():
    client = alpaca_client.get_client(make_settings(paper=False))

    assert client._base_url == LIVE_BASE_URL


def test_verify_connection_returns_account_fields():
    account = Mock(status="AccountStatus.ACTIVE", currency="USD", cash="100000", buying_power="400000")
    client = Mock()
    client.get_account.return_value = account

    info = alpaca_client.verify_connection(client)

    assert info == {
        "status": "AccountStatus.ACTIVE",
        "currency": "USD",
        "cash": "100000",
        "buying_power": "400000",
    }


def test_verify_connection_wraps_api_error_without_leaking_secret():
    client = Mock()
    client.get_account.side_effect = APIError({"message": "unauthorized."})

    with pytest.raises(alpaca_client.AlpacaAuthError) as exc_info:
        alpaca_client.verify_connection(client)

    assert "test-secret" not in str(exc_info.value)
