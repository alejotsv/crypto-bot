from datetime import date
from decimal import Decimal

import pytest

from crypto_bot import auto_entry_spend as spend


@pytest.fixture(autouse=True)
def temp_state_path(tmp_path, monkeypatch):
    monkeypatch.setattr(spend, "STATE_PATH", tmp_path / "auto_entry_spend_state.json")


def test_load_state_returns_zeroed_state_when_no_file():
    state = spend.load_state()

    assert state.total_spent == Decimal("0")
    assert state.daily_spent == Decimal("0")
    assert state.daily_date == date.min


def test_save_and_load_state_round_trips():
    state = spend.SpendState(
        total_spent=Decimal("150"), daily_spent=Decimal("50"), daily_date=date(2026, 7, 11)
    )
    spend.save_state(state)

    loaded = spend.load_state()

    assert loaded == state


def test_effective_daily_spent_returns_zero_for_stale_date():
    state = spend.SpendState(
        total_spent=Decimal("150"), daily_spent=Decimal("50"), daily_date=date(2026, 7, 10)
    )

    assert spend.effective_daily_spent(state, date(2026, 7, 11)) == Decimal("0")


def test_effective_daily_spent_returns_stored_value_for_current_date():
    state = spend.SpendState(
        total_spent=Decimal("150"), daily_spent=Decimal("50"), daily_date=date(2026, 7, 11)
    )

    assert spend.effective_daily_spent(state, date(2026, 7, 11)) == Decimal("50")


def test_record_spend_accumulates_total_and_daily_on_same_date():
    state = spend.SpendState(
        total_spent=Decimal("150"), daily_spent=Decimal("50"), daily_date=date(2026, 7, 11)
    )

    updated = spend.record_spend(state, Decimal("10"), date(2026, 7, 11))

    assert updated.total_spent == Decimal("160")
    assert updated.daily_spent == Decimal("60")
    assert updated.daily_date == date(2026, 7, 11)


def test_record_spend_rolls_over_daily_on_new_date():
    state = spend.SpendState(
        total_spent=Decimal("150"), daily_spent=Decimal("50"), daily_date=date(2026, 7, 10)
    )

    updated = spend.record_spend(state, Decimal("10"), date(2026, 7, 11))

    assert updated.total_spent == Decimal("160")
    assert updated.daily_spent == Decimal("10")
    assert updated.daily_date == date(2026, 7, 11)
