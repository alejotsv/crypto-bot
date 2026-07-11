from decimal import Decimal
from unittest.mock import Mock

import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.enums import PositionSide

from crypto_bot import positions


def make_position(symbol, qty, side, avg_entry_price, unrealized_pl):
    return Mock(symbol=symbol, qty=qty, side=side, avg_entry_price=avg_entry_price, unrealized_pl=unrealized_pl)


def test_get_open_positions_parses_response():
    client = Mock()
    client.get_all_positions.return_value = [
        make_position("BTCUSD", "0.000152643", PositionSide.LONG, "64047.47", "-0.0001"),
    ]

    result = positions.get_open_positions(client)

    assert len(result) == 1
    assert result[0].symbol == "BTCUSD"
    assert result[0].qty == Decimal("0.000152643")
    assert result[0].side == "long"
    assert result[0].avg_entry_price == Decimal("64047.47")
    assert result[0].unrealized_pl == Decimal("-0.0001")


def test_get_open_positions_returns_empty_list_when_none_open():
    client = Mock()
    client.get_all_positions.return_value = []

    assert positions.get_open_positions(client) == []


def test_short_side_parsed_correctly():
    client = Mock()
    client.get_all_positions.return_value = [
        make_position("ETHUSD", "1", PositionSide.SHORT, "3000", "10"),
    ]

    result = positions.get_open_positions(client)

    assert result[0].side == "short"


def test_api_error_wrapped_in_position_error_without_leaking_secret():
    client = Mock()
    client.get_all_positions.side_effect = APIError({"message": "forbidden"})

    with pytest.raises(positions.PositionError) as exc_info:
        positions.get_open_positions(client)

    assert "dummy-secret" not in str(exc_info.value)
