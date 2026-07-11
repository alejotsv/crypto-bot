from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crypto_bot import telegram_commands
from crypto_bot.exits import ExitError
from crypto_bot.orders import OrderError
from crypto_bot.positions import OpenPosition, PositionError
from crypto_bot.trading import OpenedPosition, TradingError

SETTINGS = SimpleNamespace(
    telegram_chat_id="12345",
    default_order_notional=Decimal("10"),
    default_order_symbol="BTC/USD",
)


def make_position(symbol="BTCUSD"):
    return OpenPosition(
        symbol=symbol,
        qty=Decimal("0.001"),
        side="long",
        avg_entry_price=Decimal("64000"),
        unrealized_pl=Decimal("5"),
    )


def make_opened_position():
    return OpenedPosition(
        order=SimpleNamespace(filled_qty=Decimal("0.001"), filled_avg_price=Decimal("64000")),
        protective_orders=SimpleNamespace(
            stop_loss_order_id="order-1",
            stop_price=Decimal("62000"),
            limit_price=Decimal("61900"),
            target_price=Decimal("68000"),
        ),
    )


# --- help/start/unknown ---


def test_handle_command_help_returns_welcome_and_keyboard():
    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/help")

    assert reply == telegram_commands.WELCOME_TEXT
    assert keyboard is not None
    assert "Buy BTC/USD ($10)" in keyboard["keyboard"][0][0]


def test_handle_command_empty_text_returns_help_and_keyboard():
    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "")

    assert reply == telegram_commands.HELP_TEXT
    assert keyboard is not None


def test_handle_command_unknown_returns_help_and_keyboard():
    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/frobnicate")

    assert reply == telegram_commands.HELP_TEXT
    assert keyboard is not None


# --- /positions ---


def test_handle_command_positions_lists_open_positions(monkeypatch):
    monkeypatch.setattr(
        telegram_commands, "get_open_positions", Mock(return_value=[make_position()])
    )

    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/positions")

    assert "BTCUSD" in reply
    assert keyboard is None


def test_handle_command_positions_reports_none_open(monkeypatch):
    monkeypatch.setattr(telegram_commands, "get_open_positions", Mock(return_value=[]))

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/positions")

    assert reply == "No open positions."


def test_handle_command_positions_reports_error(monkeypatch):
    monkeypatch.setattr(
        telegram_commands, "get_open_positions", Mock(side_effect=PositionError("boom"))
    )

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/positions")

    assert "Failed to fetch positions" in reply


# --- /buy ---


def test_handle_command_buy_with_no_args_returns_usage():
    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy")

    assert "Usage" in reply
    assert keyboard is None


def test_handle_command_buy_uses_defaults_when_amount_and_tier_omitted(monkeypatch):
    open_mock = Mock(return_value=make_opened_position())
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    client, data_client = Mock(), Mock()
    reply, _ = telegram_commands.handle_command(client, data_client, SETTINGS, "/buy ETH/USD")

    open_mock.assert_called_once_with(client, data_client, "ETH/USD", Decimal("10"), "moderate")
    assert "Bought" in reply


def test_handle_command_buy_normalizes_symbol_without_slash(monkeypatch):
    open_mock = Mock(return_value=make_opened_position())
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy ETHUSD")

    assert open_mock.call_args.args[2] == "ETH/USD"


def test_handle_command_buy_with_explicit_amount_and_tier(monkeypatch):
    open_mock = Mock(return_value=make_opened_position())
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    client, data_client = Mock(), Mock()
    telegram_commands.handle_command(client, data_client, SETTINGS, "/buy BTC/USD 25 aggressive")

    open_mock.assert_called_once_with(client, data_client, "BTC/USD", Decimal("25"), "aggressive")


def test_handle_command_buy_with_invalid_amount_returns_error(monkeypatch):
    open_mock = Mock()
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy BTC/USD notanumber")

    assert "amount must be a number" in reply
    open_mock.assert_not_called()


def test_handle_command_buy_with_invalid_tier_returns_error(monkeypatch):
    open_mock = Mock()
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy BTC/USD 10 yolo")

    assert "Unknown tier" in reply
    open_mock.assert_not_called()


def test_handle_command_buy_reports_trading_error(monkeypatch):
    monkeypatch.setattr(
        telegram_commands, "open_protected_position", Mock(side_effect=TradingError("no fill"))
    )

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy BTC/USD")

    assert "Buy failed" in reply
    assert "no fill" in reply


def test_handle_command_buy_reports_order_error(monkeypatch):
    monkeypatch.setattr(
        telegram_commands, "open_protected_position", Mock(side_effect=OrderError("bad symbol"))
    )

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/buy NOTREAL")

    assert "Buy failed" in reply


# --- Buy button ---


def test_handle_command_buy_button_tap_uses_default_symbol_and_amount(monkeypatch):
    open_mock = Mock(return_value=make_opened_position())
    monkeypatch.setattr(telegram_commands, "open_protected_position", open_mock)

    client, data_client = Mock(), Mock()
    reply, keyboard = telegram_commands.handle_command(
        client, data_client, SETTINGS, "Buy BTC/USD ($10)"
    )

    open_mock.assert_called_once_with(client, data_client, "BTC/USD", Decimal("10"), "moderate")
    assert keyboard is None
    assert "Bought" in reply


def test_handle_command_positions_button_tap_matches_typed_command(monkeypatch):
    monkeypatch.setattr(
        telegram_commands, "get_open_positions", Mock(return_value=[make_position()])
    )

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "Positions")

    assert "BTCUSD" in reply


# --- /close ---


def test_handle_command_close_with_no_args_returns_usage():
    reply, keyboard = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/close")

    assert "Usage" in reply
    assert keyboard is None


def test_handle_command_close_normalizes_symbol_and_reports_result(monkeypatch):
    close_mock = Mock(
        return_value=SimpleNamespace(
            order_id="o1", symbol="BTC/USD", status="FILLED",
            filled_qty=Decimal("0.001"), filled_avg_price=Decimal("64000"),
        )
    )
    monkeypatch.setattr(telegram_commands, "close_position", close_mock)

    client = Mock()
    reply, _ = telegram_commands.handle_command(client, Mock(), SETTINGS, "/close BTCUSD")

    close_mock.assert_called_once_with(client, "BTC/USD")
    assert "Closed" in reply
    assert "FILLED" in reply


def test_handle_command_close_reports_exit_error(monkeypatch):
    monkeypatch.setattr(telegram_commands, "close_position", Mock(side_effect=ExitError("stuck")))

    reply, _ = telegram_commands.handle_command(Mock(), Mock(), SETTINGS, "/close BTC/USD")

    assert "Close failed" in reply
    assert "stuck" in reply


# --- symbol normalization ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BTC/USD", "BTC/USD"),
        ("btc/usd", "BTC/USD"),
        ("BTCUSD", "BTC/USD"),
        ("btcusd", "BTC/USD"),
        ("AAVEUSD", "AAVE/USD"),
        ("ETHBTC", "ETH/BTC"),
    ],
)
def test_normalize_symbol(raw, expected):
    assert telegram_commands._normalize_symbol(raw) == expected
