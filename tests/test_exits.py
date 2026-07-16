from decimal import Decimal
from unittest.mock import Mock

import pytest
from alpaca.common.exceptions import APIError

from crypto_bot import exit_state, exits


@pytest.fixture(autouse=True)
def isolated_state_path(tmp_path, monkeypatch):
    monkeypatch.setattr(exit_state, "STATE_PATH", tmp_path / "exit_state.json")


@pytest.fixture
def stub_price_increment(monkeypatch):
    monkeypatch.setattr(exits, "get_price_increment", lambda client, symbol: Decimal("0.01"))


def make_bar(high, low, close):
    return Mock(high=high, low=low, close=close)


BARS = [
    make_bar(64100, 63900, 64000),
    make_bar(64200, 64000, 64150),
    make_bar(64300, 63950, 64100),
]


def test_get_atr_computes_average_true_range():
    data_client = Mock()
    data_client.get_crypto_bars.return_value = {"BTC/USD": BARS}

    atr = exits.get_atr(data_client, "BTC/USD", period=2)

    # bar1 vs bar0: max(64200-64000=200, |64200-64000|=200, |64000-64000|=0) = 200
    # bar2 vs bar1: max(64300-63950=350, |64300-64150|=150, |63950-64150|=200) = 350
    expected = (Decimal("200") + Decimal("350")) / 2
    assert atr == expected


def test_get_atr_wraps_api_error_without_leaking_secret():
    data_client = Mock()
    data_client.get_crypto_bars.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.get_atr(data_client, "BTC/USD")

    assert "dummy-secret" not in str(exc_info.value)


def test_get_price_increment_parses_asset_response():
    client = Mock()
    client.get_asset.return_value = Mock(price_increment=1e-09)

    assert exits.get_price_increment(client, "BTC/USD") == Decimal("1e-9")


def test_get_price_increment_wraps_api_error_without_leaking_secret():
    client = Mock()
    client.get_asset.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.get_price_increment(client, "BTC/USD")

    assert "dummy-secret" not in str(exc_info.value)


def test_attach_protective_orders_quantizes_prices_to_price_increment(monkeypatch):
    # A real BTC/USD-scale ATR (~$340/hour, confirmed live 2026-07-10) --
    # large enough relative to the 0.01 quantum that the stop/limit
    # buffer survives rounding (unlike a tiny ATR, where a coarse quantum
    # can round the buffer away entirely -- a real edge case, not
    # exercised by this test).
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("340.28"))
    monkeypatch.setattr(exits, "get_price_increment", lambda client, symbol: Decimal("0.01"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    result = exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64074.21"), "moderate"
    )

    assert result.target_price == result.target_price.quantize(Decimal("0.01"))
    assert result.limit_price == result.limit_price.quantize(Decimal("0.01"))
    assert result.stop_price == result.stop_price.quantize(Decimal("0.01"))
    assert result.stop_price > result.limit_price


def test_attach_protective_orders_computes_moderate_tier_prices(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    result = exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "moderate"
    )

    # moderate: stop=3x=300, target=6x=600, buffer=0.5x=50
    assert result.target_price == Decimal("64600")
    assert result.limit_price == Decimal("63700")
    assert result.stop_price == Decimal("63750")
    assert result.stop_loss_order_id == "sl-1"


def test_attach_protective_orders_computes_conservative_tier_prices(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    result = exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "conservative"
    )

    # conservative: stop=1.5x=150, target=2.5x=250, buffer=0.25x=25
    assert result.target_price == Decimal("64250")
    assert result.limit_price == Decimal("63850")
    assert result.stop_price == Decimal("63875")


def test_attach_protective_orders_computes_aggressive_tier_prices(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    result = exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "aggressive"
    )

    # aggressive: stop=6x=600, target=15x=1500, buffer=1x=100
    assert result.target_price == Decimal("65500")
    assert result.limit_price == Decimal("63400")
    assert result.stop_price == Decimal("63500")


def test_attach_protective_orders_submits_only_stop_loss_order(monkeypatch, stub_price_increment):
    """Confirmed live (2026-07-10): a second full-quantity sell order
    for the same position fails with "insufficient balance" -- only the
    stop-loss should ever be submitted as a live order.
    """
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "moderate"
    )

    client.submit_order.assert_called_once()
    submitted = client.submit_order.call_args.args[0]
    assert submitted.side.value == "sell"
    assert submitted.stop_price is not None


def test_attach_protective_orders_records_state(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.return_value = Mock(id="sl-1")

    exits.attach_protective_orders(
        client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "moderate"
    )

    state = exit_state.load_state()
    assert state["BTC/USD"] == {
        "stop_loss_order_id": "sl-1",
        "target_price": "64600.00",
        "tier": "moderate",
    }


def test_attach_protective_orders_raises_before_submitting_if_inverted(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("0"))
    client = Mock()

    with pytest.raises(ValueError, match="must be above"):
        exits.attach_protective_orders(
            client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "moderate"
        )

    client.submit_order.assert_not_called()


def test_attach_protective_orders_wraps_api_error_without_leaking_secret(monkeypatch, stub_price_increment):
    monkeypatch.setattr(exits, "get_atr", lambda data_client, symbol, period=14: Decimal("100"))
    client = Mock()
    client.submit_order.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.attach_protective_orders(
            client, Mock(), "BTC/USD", Decimal("1"), Decimal("64000"), "moderate"
        )

    assert "dummy-secret" not in str(exc_info.value)


def make_status_order(status, stop_price=None, qty=None, filled_avg_price=None, filled_qty=None):
    return Mock(
        status=status,
        stop_price=stop_price,
        qty=qty,
        filled_avg_price=filled_avg_price,
        filled_qty=filled_qty,
    )


def test_reconcile_notifies_and_cleans_up_when_stop_loss_filled_on_its_own():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.return_value = make_status_order(
        "OrderStatus.FILLED", filled_avg_price="63750", filled_qty="0.5"
    )

    result = exits.check_and_reconcile_exits(client, Mock())

    assert len(result) == 1
    assert result[0].action == "STOP_LOSS_FILLED"
    assert "63750" in result[0].detail
    assert "0.5" in result[0].detail
    client.cancel_order_by_id.assert_not_called()
    client.submit_order.assert_not_called()
    assert exit_state.load_state() == {}


def test_reconcile_cleans_up_orphaned_canceled_stop_loss():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.return_value = make_status_order("OrderStatus.CANCELED")

    result = exits.check_and_reconcile_exits(client, Mock())

    assert result == []
    assert exit_state.load_state() == {}


def test_reconcile_does_nothing_when_price_between_stop_and_target():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.return_value = make_status_order(
        "OrderStatus.NEW", stop_price="63750", qty="1"
    )
    data_client = Mock()
    data_client.get_crypto_latest_quote.return_value = {"BTC/USD": Mock(bid_price=64000)}

    result = exits.check_and_reconcile_exits(client, data_client)

    assert result == []
    client.cancel_order_by_id.assert_not_called()
    client.submit_order.assert_not_called()
    assert "BTC/USD" in exit_state.load_state()


def test_reconcile_realizes_take_profit_when_price_reaches_target():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.return_value = make_status_order(
        "OrderStatus.NEW", stop_price="63750", qty="0.5"
    )
    data_client = Mock()
    data_client.get_crypto_latest_quote.return_value = {"BTC/USD": Mock(bid_price=65100)}

    result = exits.check_and_reconcile_exits(client, data_client)

    assert len(result) == 1
    assert result[0].action == "TAKE_PROFIT_REALIZED"
    client.cancel_order_by_id.assert_called_once_with("sl-1")
    client.submit_order.assert_called_once()
    submitted = client.submit_order.call_args.args[0]
    assert submitted.side.value == "sell"
    assert submitted.qty == Decimal("0.5")
    assert exit_state.load_state() == {}


def test_reconcile_forces_market_sell_when_stop_loss_stuck():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.return_value = make_status_order(
        "OrderStatus.NEW", stop_price="63750", qty="0.5"
    )
    data_client = Mock()
    data_client.get_crypto_latest_quote.return_value = {"BTC/USD": Mock(bid_price=63000)}

    result = exits.check_and_reconcile_exits(client, data_client)

    assert len(result) == 1
    assert result[0].action == "FORCED_MARKET_SELL"
    client.cancel_order_by_id.assert_called_once_with("sl-1")
    client.submit_order.assert_called_once()
    submitted = client.submit_order.call_args.args[0]
    assert submitted.side.value == "sell"
    assert exit_state.load_state() == {}


def test_reconcile_wraps_api_error_without_leaking_secret():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.get_order_by_id.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.check_and_reconcile_exits(client, Mock())

    assert "dummy-secret" not in str(exc_info.value)


def make_close_order(status="OrderStatus.FILLED", order_id="close-1", filled_qty="0.0001", filled_avg_price="65000"):
    return Mock(id=order_id, status=status, filled_qty=filled_qty, filled_avg_price=filled_avg_price)


def test_close_position_cancels_tracked_stop_loss_first(monkeypatch):
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    monkeypatch.setattr(exits, "poll_until_terminal", lambda client, order_id, symbol: make_close_order())
    client = Mock()
    client.close_position.return_value = Mock(id="close-1")

    result = exits.close_position(client, "BTC/USD")

    client.cancel_order_by_id.assert_called_once_with("sl-1")
    client.close_position.assert_called_once_with("BTCUSD")
    assert result.status == "FILLED"
    assert result.symbol == "BTC/USD"
    assert exit_state.load_state() == {}


def test_close_position_works_with_no_tracked_stop_loss(monkeypatch):
    monkeypatch.setattr(exits, "poll_until_terminal", lambda client, order_id, symbol: make_close_order())
    client = Mock()
    client.close_position.return_value = Mock(id="close-1")

    result = exits.close_position(client, "BTC/USD")

    client.cancel_order_by_id.assert_not_called()
    client.close_position.assert_called_once_with("BTCUSD")
    assert result.status == "FILLED"


def test_close_position_wraps_cancel_api_error_without_leaking_secret():
    exit_state.record_protective_orders("BTC/USD", "sl-1", "65000", "moderate")
    client = Mock()
    client.cancel_order_by_id.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.close_position(client, "BTC/USD")

    assert "dummy-secret" not in str(exc_info.value)
    client.close_position.assert_not_called()


def test_close_position_wraps_close_api_error_without_leaking_secret():
    client = Mock()
    client.close_position.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(exits.ExitError) as exc_info:
        exits.close_position(client, "BTC/USD")

    assert "dummy-secret" not in str(exc_info.value)
