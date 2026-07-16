from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crypto_bot import run_cycle
from crypto_bot.exits import ReconcileAction
from crypto_bot.strategy import AutoEntryResult
from crypto_bot.telegram_bot import TelegramError


def _stub_settings(auto_entry_enabled=False):
    return SimpleNamespace(
        alpaca_api_key="test-key",
        alpaca_secret_key="test-secret",
        auto_entry_enabled=auto_entry_enabled,
        auto_entry_notional=Decimal("10"),
        auto_entry_total_cap=Decimal("1000"),
        auto_entry_daily_cap=Decimal("200"),
        telegram_bot_token="test-bot-token",
        telegram_chat_id="12345",
        default_order_notional=Decimal("10"),
        default_order_symbol="BTC/USD",
    )


def make_update(update_id, chat_id="12345", text="/positions"):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


@pytest.fixture(autouse=True)
def stub_settings_and_clients(monkeypatch):
    monkeypatch.setattr(run_cycle, "load_settings", Mock(return_value=_stub_settings()))
    monkeypatch.setattr(run_cycle, "get_client", Mock())
    monkeypatch.setattr(run_cycle, "CryptoHistoricalDataClient", Mock())
    monkeypatch.setattr(run_cycle, "load_last_update_id", Mock(return_value=0))
    monkeypatch.setattr(run_cycle, "save_last_update_id", Mock())
    monkeypatch.setattr(run_cycle, "get_updates", Mock(return_value=[]))
    monkeypatch.setattr(run_cycle, "send_message", Mock())
    monkeypatch.setattr(run_cycle, "check_and_reconcile_exits", Mock(return_value=[]))


def test_run_reconcile_cycle_logs_no_action_when_none_taken(caplog):
    with caplog.at_level("INFO"):
        run_cycle.run_reconcile_cycle()

    assert "no action needed" in caplog.text


def test_run_reconcile_cycle_logs_and_notifies_each_action(monkeypatch, caplog):
    monkeypatch.setattr(
        run_cycle,
        "check_and_reconcile_exits",
        Mock(return_value=[
            ReconcileAction(symbol="BTC/USD", action="TAKE_PROFIT_REALIZED", detail="hit target"),
        ]),
    )
    send_mock = Mock()
    monkeypatch.setattr(run_cycle, "send_message", send_mock)

    with caplog.at_level("INFO"):
        run_cycle.run_reconcile_cycle()

    assert "BTC/USD" in caplog.text
    assert "TAKE_PROFIT_REALIZED" in caplog.text
    assert "hit target" in caplog.text
    send_mock.assert_called_once()
    notified_text = send_mock.call_args.args[1]
    assert "BTC/USD" in notified_text
    assert "Take-profit hit" in notified_text


def test_run_reconcile_cycle_skips_auto_entry_when_disabled(monkeypatch):
    monkeypatch.setattr(run_cycle, "load_settings", Mock(return_value=_stub_settings(False)))
    entry_mock = Mock()
    monkeypatch.setattr(run_cycle, "run_auto_entry_cycle", entry_mock)

    run_cycle.run_reconcile_cycle()

    entry_mock.assert_not_called()


def test_run_reconcile_cycle_runs_auto_entry_and_notifies_when_enabled(monkeypatch, caplog):
    monkeypatch.setattr(run_cycle, "load_settings", Mock(return_value=_stub_settings(True)))
    monkeypatch.setattr(
        run_cycle,
        "run_auto_entry_cycle",
        Mock(return_value=[
            AutoEntryResult(symbol="BTC/USD", action="ENTERED", detail="filled 0.001 @ 64000"),
            AutoEntryResult(symbol="ETH/USD", action="SKIPPED_NO_SIGNAL", detail=""),
        ]),
    )
    send_mock = Mock()
    monkeypatch.setattr(run_cycle, "send_message", send_mock)

    with caplog.at_level("INFO"):
        run_cycle.run_reconcile_cycle()

    assert "BTC/USD" in caplog.text
    assert "ENTERED" in caplog.text
    assert "ETH/USD" not in caplog.text
    send_mock.assert_called_once()
    assert "BTC/USD" in send_mock.call_args.args[1]
    assert "Entered" in send_mock.call_args.args[1]


# --- Telegram command processing ---


def test_run_reconcile_cycle_processes_command_from_matching_chat(monkeypatch):
    monkeypatch.setattr(run_cycle, "get_updates", Mock(return_value=[make_update(5)]))
    handle_mock = Mock(return_value=("No open positions.", None))
    monkeypatch.setattr(run_cycle, "handle_command", handle_mock)
    send_mock = Mock()
    monkeypatch.setattr(run_cycle, "send_message", send_mock)
    save_mock = Mock()
    monkeypatch.setattr(run_cycle, "save_last_update_id", save_mock)

    run_cycle.run_reconcile_cycle()

    handle_mock.assert_called_once()
    assert handle_mock.call_args.args[3] == "/positions"
    send_mock.assert_any_call(run_cycle.load_settings(), "No open positions.", None)
    save_mock.assert_called_with(6)


def test_run_reconcile_cycle_ignores_update_from_other_chat(monkeypatch):
    monkeypatch.setattr(
        run_cycle, "get_updates", Mock(return_value=[make_update(5, chat_id="99999")])
    )
    handle_mock = Mock()
    monkeypatch.setattr(run_cycle, "handle_command", handle_mock)
    send_mock = Mock()
    monkeypatch.setattr(run_cycle, "send_message", send_mock)

    run_cycle.run_reconcile_cycle()

    handle_mock.assert_not_called()
    send_mock.assert_not_called()


def test_run_reconcile_cycle_skips_updates_without_a_message(monkeypatch):
    monkeypatch.setattr(
        run_cycle, "get_updates", Mock(return_value=[{"update_id": 7, "edited_message": {}}])
    )
    handle_mock = Mock()
    monkeypatch.setattr(run_cycle, "handle_command", handle_mock)
    save_mock = Mock()
    monkeypatch.setattr(run_cycle, "save_last_update_id", save_mock)

    run_cycle.run_reconcile_cycle()

    handle_mock.assert_not_called()
    save_mock.assert_called_with(8)


def test_run_reconcile_cycle_continues_past_telegram_error(monkeypatch, caplog):
    monkeypatch.setattr(run_cycle, "get_updates", Mock(side_effect=TelegramError("timeout")))
    monkeypatch.setattr(
        run_cycle,
        "check_and_reconcile_exits",
        Mock(return_value=[
            ReconcileAction(symbol="BTC/USD", action="TAKE_PROFIT_REALIZED", detail="hit target"),
        ]),
    )

    with caplog.at_level("INFO"):
        run_cycle.run_reconcile_cycle()

    assert "Telegram command processing failed" in caplog.text
    assert "TAKE_PROFIT_REALIZED" in caplog.text
