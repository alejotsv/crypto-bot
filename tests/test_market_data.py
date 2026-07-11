from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from alpaca.common.exceptions import APIError

from crypto_bot import market_data


def make_quote(bid_price, ask_price, timestamp=None):
    return Mock(
        bid_price=bid_price,
        ask_price=ask_price,
        timestamp=timestamp or datetime(2026, 7, 10, 23, 9, 16, tzinfo=timezone.utc),
    )


def test_get_price_parses_response():
    client = Mock()
    client.get_crypto_latest_quote.return_value = {
        "BTC/USD": make_quote(bid_price=63958.996, ask_price=64009.4)
    }

    quote = market_data.get_price(client, "BTC/USD")

    assert quote.symbol == "BTC/USD"
    assert quote.bid == Decimal("63958.996")
    assert quote.ask == Decimal("64009.4")
    assert quote.spread == Decimal("64009.4") - Decimal("63958.996")


def test_get_price_defaults_to_btc_usd():
    client = Mock()
    client.get_crypto_latest_quote.return_value = {
        "BTC/USD": make_quote(bid_price=100, ask_price=101)
    }

    quote = market_data.get_price(client)

    assert quote.symbol == "BTC/USD"
    client.get_crypto_latest_quote.assert_called_once()


def test_api_error_wrapped_in_market_data_error_without_leaking_secret():
    client = Mock()
    client.get_crypto_latest_quote.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(market_data.MarketDataError) as exc_info:
        market_data.get_price(client, "BTC/USD")

    assert "dummy-secret" not in str(exc_info.value)
