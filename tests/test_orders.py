from decimal import Decimal
from unittest.mock import Mock

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderStatus

from crypto_bot import orders


def make_order(status, order_id="1", filled_qty=None, filled_avg_price=None):
    return Mock(id=order_id, status=status, filled_qty=filled_qty, filled_avg_price=filled_avg_price)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(orders.time, "sleep", lambda seconds: None)


def test_place_market_order_polls_until_filled():
    client = Mock()
    client.submit_order.return_value = make_order(OrderStatus.PENDING_NEW)
    client.get_order_by_id.side_effect = [
        make_order(OrderStatus.PENDING_NEW),
        make_order(OrderStatus.FILLED, filled_qty="0.000153026", filled_avg_price="64047.47"),
    ]

    result = orders.place_market_order(client, "BTC/USD", "buy", Decimal("10"))

    assert result.status == "FILLED"
    assert result.symbol == "BTC/USD"
    assert result.side == "buy"
    assert result.filled_qty == Decimal("0.000153026")
    assert result.filled_avg_price == Decimal("64047.47")


def test_place_market_order_returns_rejected_without_raising():
    client = Mock()
    client.submit_order.return_value = make_order(OrderStatus.PENDING_NEW)
    client.get_order_by_id.return_value = make_order(OrderStatus.REJECTED)

    result = orders.place_market_order(client, "BTC/USD", "buy", Decimal("10"))

    assert result.status == "REJECTED"


def test_place_market_order_sends_correct_side(monkeypatch):
    captured = {}
    client = Mock()

    def fake_submit(order_data):
        captured["order_data"] = order_data
        return make_order(OrderStatus.FILLED, filled_qty="1", filled_avg_price="100")

    client.submit_order.side_effect = fake_submit
    client.get_order_by_id.return_value = make_order(
        OrderStatus.FILLED, filled_qty="1", filled_avg_price="100"
    )

    orders.place_market_order(client, "ETH/USD", "sell", Decimal("10"))

    assert captured["order_data"].side.value == "sell"


def test_notional_below_minimum_raises_value_error_before_request():
    client = Mock()

    with pytest.raises(ValueError, match="notional must be"):
        orders.place_market_order(client, "BTC/USD", "buy", Decimal("5"))

    client.submit_order.assert_not_called()


def test_invalid_side_raises_value_error_before_request():
    client = Mock()

    with pytest.raises(ValueError, match="side must be"):
        orders.place_market_order(client, "BTC/USD", "hold", Decimal("10"))

    client.submit_order.assert_not_called()


def test_api_error_on_submit_wrapped_in_order_error_without_leaking_secret():
    client = Mock()
    client.submit_order.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(orders.OrderError) as exc_info:
        orders.place_market_order(client, "BTC/USD", "buy", Decimal("10"))

    assert "dummy-secret" not in str(exc_info.value)


def test_api_error_on_status_poll_wrapped_in_order_error():
    client = Mock()
    client.submit_order.return_value = make_order(OrderStatus.PENDING_NEW)
    client.get_order_by_id.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(orders.OrderError):
        orders.place_market_order(client, "BTC/USD", "buy", Decimal("10"))


def test_never_reaching_terminal_status_raises_order_error():
    client = Mock()
    client.submit_order.return_value = make_order(OrderStatus.PENDING_NEW)
    client.get_order_by_id.return_value = make_order(OrderStatus.PENDING_NEW)

    with pytest.raises(orders.OrderError, match="did not reach a terminal status"):
        orders.place_market_order(client, "BTC/USD", "buy", Decimal("10"))

    assert client.get_order_by_id.call_count == orders.MAX_POLL_ATTEMPTS
