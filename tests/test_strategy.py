from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crypto_bot import strategy
from crypto_bot.auto_entry_spend import SpendState
from crypto_bot.positions import OpenPosition
from crypto_bot.trading import OpenedPosition, TradingError


def make_bar(close, timestamp, high=None, low=None):
    high = close if high is None else high
    low = close if low is None else low
    return SimpleNamespace(close=close, high=high, low=low, timestamp=timestamp)


def make_position(symbol="BTCUSD"):
    return OpenPosition(
        symbol=symbol,
        qty=Decimal("0.001"),
        side="long",
        avg_entry_price=Decimal("64000"),
        unrealized_pl=Decimal("0"),
    )


@pytest.fixture(autouse=True)
def stub_spend_state(monkeypatch):
    """Prevent real filesystem I/O in tests that don't care about
    spend-cap tracking; individual tests override as needed.
    """
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("0"), Decimal("0"), date.min)),
    )
    monkeypatch.setattr(strategy, "save_state", Mock())


def _flat_bars(count, price=Decimal("100"), spread=Decimal("0.1"), start=None):
    """`count` hourly bars with a constant close and a small, constant
    high/low spread around it -- a deterministic low-volatility squeeze
    (near-zero Bollinger std, small but nonzero ATR)."""
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        make_bar(price, start + timedelta(hours=i), high=price + spread, low=price - spread)
        for i in range(count)
    ]


# --- check_entry_signal (Bollinger squeeze breakout) ---


def test_check_entry_signal_true_on_release_with_price_above_middle():
    # 20 flat bars (squeeze ON: near-zero BB std, small ATR keeps Keltner
    # just outside the tight bands) followed by one sharp breakout bar --
    # bands expand well past the Keltner channel, releasing the squeeze.
    bars = _flat_bars(20) + [
        make_bar(Decimal("110"), datetime(2026, 1, 1, 20, tzinfo=timezone.utc), high=Decimal("111"), low=Decimal("109"))
    ]
    assert strategy.check_entry_signal(bars, Decimal("110")) is True


def test_check_entry_signal_false_when_price_below_middle_on_release():
    bars = _flat_bars(20) + [
        make_bar(Decimal("110"), datetime(2026, 1, 1, 20, tzinfo=timezone.utc), high=Decimal("111"), low=Decimal("109"))
    ]
    # Squeeze still releases (bands still expand), but the live price used
    # for the direction check has since dropped back below the basis line.
    assert strategy.check_entry_signal(bars, Decimal("90")) is False


def test_check_entry_signal_false_when_squeeze_never_releases():
    bars = _flat_bars(21)
    assert strategy.check_entry_signal(bars, Decimal("100")) is False


def test_check_entry_signal_false_with_too_few_bars():
    bars = _flat_bars(strategy.MIN_HOURLY_BARS - 1)
    assert strategy.check_entry_signal(bars, Decimal("100")) is False


# --- get_recent_hourly_bars ---


def test_get_recent_hourly_bars_drops_still_forming_trailing_bar():
    now = datetime.now(timezone.utc)
    bars = [
        make_bar(Decimal(str(100 + i)), now - timedelta(hours=(21 - i)))
        for i in range(20)
    ]
    # Still-forming current bar -- its hour hasn't elapsed yet.
    bars.append(make_bar(Decimal("999"), now - timedelta(minutes=5)))

    data_client = Mock()
    data_client.get_crypto_bars.return_value = SimpleNamespace(data={"BTC/USD": bars})

    hourly_bars = strategy.get_recent_hourly_bars(data_client, "BTC/USD", count=20)

    assert all(b.close != Decimal("999") for b in hourly_bars)
    assert len(hourly_bars) == 20


def test_get_recent_hourly_bars_returns_empty_list_for_missing_symbol():
    data_client = Mock()
    data_client.get_crypto_bars.return_value = SimpleNamespace(data={})

    hourly_bars = strategy.get_recent_hourly_bars(data_client, "BTC/USD")

    assert hourly_bars == []


# --- _latest_price ---


def test_latest_price_uses_bid_price():
    data_client = Mock()
    data_client.get_crypto_latest_quote.return_value = {
        "BTC/USD": SimpleNamespace(bid_price="64000.12")
    }

    price = strategy._latest_price(data_client, "BTC/USD")

    assert price == Decimal("64000.12")


# --- run_auto_entry_check ---


def test_run_auto_entry_check_skips_when_already_open(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[make_position()]))
    signal_mock = Mock()
    monkeypatch.setattr(strategy, "check_entry_signal", signal_mock)

    result = strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    assert result.action == "SKIPPED_ALREADY_OPEN"
    signal_mock.assert_not_called()


def test_run_auto_entry_check_skips_when_no_signal(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=False))
    buying_power_mock = Mock()
    monkeypatch.setattr(strategy, "_crypto_buying_power", buying_power_mock)

    result = strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    assert result.action == "SKIPPED_NO_SIGNAL"
    buying_power_mock.assert_not_called()


def test_run_auto_entry_check_skips_when_insufficient_funds(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=True))
    monkeypatch.setattr(strategy, "_crypto_buying_power", Mock(return_value=Decimal("5")))
    open_mock = Mock()
    monkeypatch.setattr(strategy, "open_protected_position", open_mock)

    result = strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    assert result.action == "SKIPPED_INSUFFICIENT_FUNDS"
    assert "available=$5" in result.detail
    assert "required=$10" in result.detail
    open_mock.assert_not_called()


def test_run_auto_entry_check_enters_when_signal_and_funds_ok(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=True))
    monkeypatch.setattr(strategy, "_crypto_buying_power", Mock(return_value=Decimal("100")))

    opened = OpenedPosition(
        order=SimpleNamespace(filled_qty=Decimal("0.001"), filled_avg_price=Decimal("64000")),
        protective_orders=Mock(),
    )
    open_mock = Mock(return_value=opened)
    monkeypatch.setattr(strategy, "open_protected_position", open_mock)

    client, data_client = Mock(), Mock()
    result = strategy.run_auto_entry_check(client, data_client, "BTC/USD", Decimal("10"))

    assert result.action == "ENTERED"
    open_mock.assert_called_once_with(client, data_client, "BTC/USD", Decimal("10"), "moderate")


def test_run_auto_entry_check_returns_order_not_filled_on_trading_error(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=True))
    monkeypatch.setattr(strategy, "_crypto_buying_power", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(
        strategy, "open_protected_position", Mock(side_effect=TradingError("did not fill"))
    )

    result = strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    assert result.action == "ORDER_NOT_FILLED"
    assert "did not fill" in result.detail


# --- run_auto_entry_cycle ---


def test_run_auto_entry_cycle_checks_every_symbol(monkeypatch):
    check_mock = Mock(
        side_effect=lambda client, dc, symbol, notional, total_cap, daily_cap: strategy.AutoEntryResult(
            symbol, "SKIPPED_NO_SIGNAL", ""
        )
    )
    monkeypatch.setattr(strategy, "run_auto_entry_check", check_mock)

    settings = SimpleNamespace(
        auto_entry_notional=Decimal("10"),
        auto_entry_total_cap=Decimal("1000"),
        auto_entry_daily_cap=Decimal("200"),
    )
    client, data_client = Mock(), Mock()
    results = strategy.run_auto_entry_cycle(client, data_client, settings)

    assert [r.symbol for r in results] == strategy.AUTO_ENTRY_SYMBOLS
    assert check_mock.call_count == len(strategy.AUTO_ENTRY_SYMBOLS)
    check_mock.assert_any_call(
        client, data_client, "BTC/USD", Decimal("10"), Decimal("1000"), Decimal("200")
    )


# --- run_auto_entry_check: spending caps (ADR 0006) ---


def test_run_auto_entry_check_skips_when_total_cap_reached(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("995"), Decimal("0"), date.min)),
    )
    signal_mock = Mock()
    monkeypatch.setattr(strategy, "check_entry_signal", signal_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("1000")
    )

    assert result.action == "SKIPPED_TOTAL_CAP_REACHED"
    assert "total_spent=$995" in result.detail
    assert "cap=$1,000" in result.detail
    signal_mock.assert_not_called()


def test_run_auto_entry_check_total_cap_disabled_when_zero(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("999999"), Decimal("0"), date.min)),
    )
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=False))

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0")
    )

    assert result.action == "SKIPPED_NO_SIGNAL"


def test_run_auto_entry_check_skips_when_daily_cap_reached(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("50"), Decimal("195"), today)),
    )
    signal_mock = Mock()
    monkeypatch.setattr(strategy, "check_entry_signal", signal_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0"), daily_cap=Decimal("200")
    )

    assert result.action == "SKIPPED_DAILY_CAP_REACHED"
    assert "daily_spent=$195" in result.detail
    assert "cap=$200" in result.detail
    signal_mock.assert_not_called()


def test_run_auto_entry_check_daily_cap_uses_zero_for_stale_date(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("500"), Decimal("199"), date(2020, 1, 1))),
    )
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=False))

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0"), daily_cap=Decimal("200")
    )

    # Stale daily_date means effective daily spend is 0, not 199 -- doesn't trip the cap.
    assert result.action == "SKIPPED_NO_SIGNAL"


# --- Feature 11: notify-once-per-episode on cap reached ---


def test_run_auto_entry_check_total_cap_reached_notifies_first_time(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("995"), Decimal("0"), date.min, total_cap_notified=False
        )),
    )
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("1000")
    )

    assert result.action == "SKIPPED_TOTAL_CAP_REACHED"
    assert result.notify is True
    assert save_mock.call_args.args[0].total_cap_notified is True


def test_run_auto_entry_check_total_cap_reached_does_not_renotify(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("995"), Decimal("0"), date.min, total_cap_notified=True
        )),
    )
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("1000")
    )

    assert result.action == "SKIPPED_TOTAL_CAP_REACHED"
    assert result.notify is False
    save_mock.assert_not_called()


def test_run_auto_entry_check_total_cap_rearms_once_no_longer_capped(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("0"), Decimal("0"), date.min, total_cap_notified=True
        )),
    )
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=False))
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("1000")
    )

    # No longer capped (spend reset/cap raised past current spend) -- this
    # cycle doesn't notify, but the flag re-arms so a future capping does.
    assert result.action == "SKIPPED_NO_SIGNAL"
    assert save_mock.call_args.args[0].total_cap_notified is False


def test_run_auto_entry_check_daily_cap_reached_notifies_first_time(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("50"), Decimal("195"), today, daily_cap_notified=False
        )),
    )
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0"), daily_cap=Decimal("200")
    )

    assert result.action == "SKIPPED_DAILY_CAP_REACHED"
    assert result.notify is True
    assert save_mock.call_args.args[0].daily_cap_notified is True


def test_run_auto_entry_check_daily_cap_reached_does_not_renotify(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    today = datetime.now(timezone.utc).date()
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("50"), Decimal("195"), today, daily_cap_notified=True
        )),
    )
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0"), daily_cap=Decimal("200")
    )

    assert result.action == "SKIPPED_DAILY_CAP_REACHED"
    assert result.notify is False
    save_mock.assert_not_called()


def test_run_auto_entry_check_daily_cap_rearms_on_utc_rollover(monkeypatch):
    """A daily_cap_notified=True flag from a prior day re-arms purely as a
    side effect of the existing not-capped-transition rule, once the
    stale daily_date makes effective_daily_spent 0 again -- no
    special-cased rollover handling needed (see spec 011's design note).
    """
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(
            Decimal("500"), Decimal("199"), date(2020, 1, 1), daily_cap_notified=True
        )),
    )
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=False))
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    result = strategy.run_auto_entry_check(
        Mock(), Mock(), "BTC/USD", Decimal("10"), total_cap=Decimal("0"), daily_cap=Decimal("200")
    )

    assert result.action == "SKIPPED_NO_SIGNAL"
    assert save_mock.call_args.args[0].daily_cap_notified is False


def test_run_auto_entry_check_records_spend_on_entry(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[]))
    monkeypatch.setattr(
        strategy,
        "load_state",
        Mock(return_value=SpendState(Decimal("50"), Decimal("20"), date.min)),
    )
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)
    monkeypatch.setattr(strategy, "get_recent_hourly_bars", Mock(return_value=[]))
    monkeypatch.setattr(strategy, "_latest_price", Mock(return_value=Decimal("100")))
    monkeypatch.setattr(strategy, "check_entry_signal", Mock(return_value=True))
    monkeypatch.setattr(strategy, "_crypto_buying_power", Mock(return_value=Decimal("100")))
    opened = OpenedPosition(
        order=SimpleNamespace(filled_qty=Decimal("0.001"), filled_avg_price=Decimal("64000")),
        protective_orders=Mock(),
    )
    monkeypatch.setattr(strategy, "open_protected_position", Mock(return_value=opened))

    result = strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    assert result.action == "ENTERED"
    save_mock.assert_called_once()
    saved_state = save_mock.call_args.args[0]
    assert saved_state.total_spent == Decimal("60")


def test_run_auto_entry_check_does_not_record_spend_on_skip(monkeypatch):
    monkeypatch.setattr(strategy, "get_open_positions", Mock(return_value=[make_position()]))
    save_mock = Mock()
    monkeypatch.setattr(strategy, "save_state", save_mock)

    strategy.run_auto_entry_check(Mock(), Mock(), "BTC/USD", Decimal("10"))

    save_mock.assert_not_called()


# --- _crypto_buying_power ---


def test_crypto_buying_power_uses_non_marginable_field():
    client = Mock()
    client.get_account.return_value = SimpleNamespace(
        cash="99999.65",
        buying_power="399998.60",
        non_marginable_buying_power="99999.65",
    )

    available = strategy._crypto_buying_power(client)

    assert available == Decimal("99999.65")
