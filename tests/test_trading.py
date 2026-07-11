from decimal import Decimal
from unittest.mock import Mock

import pytest

from crypto_bot import trading
from crypto_bot.orders import OrderResult
from crypto_bot.positions import OpenPosition


def make_order_result(status="FILLED", filled_qty="0.000152726", filled_avg_price="64180.6"):
    return OrderResult(
        status=status,
        order_id="order-1",
        symbol="BTC/USD",
        side="buy",
        filled_qty=Decimal(filled_qty) if filled_qty else None,
        filled_avg_price=Decimal(filled_avg_price) if filled_avg_price else None,
    )


def make_position(symbol="BTCUSD", qty="0.000152344"):
    return OpenPosition(
        symbol=symbol,
        qty=Decimal(qty),
        side="long",
        avg_entry_price=Decimal("64180.6"),
        unrealized_pl=Decimal("0"),
    )


def test_open_protected_position_uses_real_position_qty_not_filled_qty(monkeypatch):
    """The core bug fix: order.filled_qty (0.000152726) and the actual
    position qty (0.000152344) differ due to Alpaca's crypto fee --
    attach_protective_orders must be called with the real position qty.
    """
    monkeypatch.setattr(trading, "place_market_order", Mock(return_value=make_order_result()))
    monkeypatch.setattr(trading, "get_open_positions", Mock(return_value=[make_position()]))
    attach_mock = Mock(return_value=Mock())
    monkeypatch.setattr(trading, "attach_protective_orders", attach_mock)

    trading.open_protected_position(Mock(), Mock(), "BTC/USD", Decimal("10"), "moderate")

    attach_mock.assert_called_once()
    call_args = attach_mock.call_args.args
    # (client, data_client, symbol, qty, entry_price, tier)
    assert call_args[3] == Decimal("0.000152344")
    assert call_args[3] != Decimal("0.000152726")


def test_open_protected_position_returns_order_and_protective_orders(monkeypatch):
    order_result = make_order_result()
    protective = Mock()
    monkeypatch.setattr(trading, "place_market_order", Mock(return_value=order_result))
    monkeypatch.setattr(trading, "get_open_positions", Mock(return_value=[make_position()]))
    monkeypatch.setattr(trading, "attach_protective_orders", Mock(return_value=protective))

    result = trading.open_protected_position(Mock(), Mock(), "BTC/USD", Decimal("10"), "moderate")

    assert result.order == order_result
    assert result.protective_orders == protective


def test_open_protected_position_raises_when_order_not_filled(monkeypatch):
    monkeypatch.setattr(
        trading, "place_market_order", Mock(return_value=make_order_result(status="REJECTED"))
    )
    attach_mock = Mock()
    monkeypatch.setattr(trading, "attach_protective_orders", attach_mock)

    with pytest.raises(trading.TradingError, match="did not fill"):
        trading.open_protected_position(Mock(), Mock(), "BTC/USD", Decimal("10"), "moderate")

    attach_mock.assert_not_called()


def test_open_protected_position_raises_when_position_not_found(monkeypatch):
    monkeypatch.setattr(trading, "place_market_order", Mock(return_value=make_order_result()))
    monkeypatch.setattr(trading, "get_open_positions", Mock(return_value=[]))
    attach_mock = Mock()
    monkeypatch.setattr(trading, "attach_protective_orders", attach_mock)

    with pytest.raises(trading.TradingError, match="no open position found"):
        trading.open_protected_position(Mock(), Mock(), "BTC/USD", Decimal("10"), "moderate")

    attach_mock.assert_not_called()


def test_open_protected_position_matches_position_by_no_slash_symbol(monkeypatch):
    monkeypatch.setattr(trading, "place_market_order", Mock(return_value=make_order_result()))
    monkeypatch.setattr(
        trading,
        "get_open_positions",
        Mock(return_value=[make_position(symbol="ETHUSD"), make_position(symbol="BTCUSD")]),
    )
    attach_mock = Mock(return_value=Mock())
    monkeypatch.setattr(trading, "attach_protective_orders", attach_mock)

    trading.open_protected_position(Mock(), Mock(), "BTC/USD", Decimal("10"), "moderate")

    attach_mock.assert_called_once()
