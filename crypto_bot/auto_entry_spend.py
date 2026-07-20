"""Tracks cumulative dollars spent by auto-entry, for the optional
total/daily spending caps (see ADR 0006) -- a deliberate, scoped
exception to this project's "no preset dollar ceiling" constraint,
limited to auto-entry only. Mirrors exit_state.py's minimal gitignored
JSON state-file pattern.

Only auto-entry spend is tracked here -- manual trades are never gated
by either cap and never touch this file.
"""

import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

STATE_PATH = Path("auto_entry_spend_state.json")


@dataclass(frozen=True)
class SpendState:
    total_spent: Decimal
    daily_spent: Decimal
    daily_date: date
    # Whether a Telegram notification has already been sent for the
    # *current* capped episode (feature 11) -- reset to False the moment
    # the corresponding cap stops blocking, so the next time it blocks
    # again counts as a new episode and notifies again.
    total_cap_notified: bool = False
    daily_cap_notified: bool = False


def load_state() -> SpendState:
    if not STATE_PATH.exists():
        return SpendState(total_spent=Decimal("0"), daily_spent=Decimal("0"), daily_date=date.min)
    data = json.loads(STATE_PATH.read_text())
    return SpendState(
        total_spent=Decimal(data["total_spent"]),
        daily_spent=Decimal(data["daily_spent"]),
        daily_date=date.fromisoformat(data["daily_date"]),
        total_cap_notified=data.get("total_cap_notified", False),
        daily_cap_notified=data.get("daily_cap_notified", False),
    )


def save_state(state: SpendState) -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "total_spent": str(state.total_spent),
                "daily_spent": str(state.daily_spent),
                "daily_date": state.daily_date.isoformat(),
                "total_cap_notified": state.total_cap_notified,
                "daily_cap_notified": state.daily_cap_notified,
            }
        )
    )


def effective_daily_spent(state: SpendState, today: date) -> Decimal:
    """`daily_spent` only counts if it belongs to `today` (UTC) -- a
    stale date means the day rolled over and today's spend is really 0,
    without needing to write that rollover to disk until a trade
    actually happens.
    """
    return state.daily_spent if state.daily_date == today else Decimal("0")


def record_spend(state: SpendState, amount: Decimal, today: date) -> SpendState:
    daily_spent = effective_daily_spent(state, today) + amount
    return replace(
        state,
        total_spent=state.total_spent + amount,
        daily_spent=daily_spent,
        daily_date=today,
    )
