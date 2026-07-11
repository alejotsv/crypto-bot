"""Tracks the live stop-loss order and take-profit target for each
position with protective orders attached.

Only the stop-loss is ever a live Alpaca order (see exits.py's module
docstring for why -- Alpaca locks the entire position quantity against
one sell order, so a second concurrent sell order isn't possible). The
take-profit target is just a tracked price, checked by the
reconciliation cron. Alpaca's Position model has no tagging field for
arbitrary metadata (confirmed), so this project tracks all of it itself
in a small gitignored JSON file, mirroring the OANDA sibling project's
minimal state-file pattern.
"""

import json
from pathlib import Path

STATE_PATH = Path("exit_state.json")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state))


def record_protective_orders(
    symbol: str, stop_loss_order_id: str, target_price: str, tier: str
) -> None:
    state = load_state()
    state[symbol] = {
        "stop_loss_order_id": stop_loss_order_id,
        "target_price": target_price,
        "tier": tier,
    }
    save_state(state)


def remove_protective_orders(symbol: str) -> None:
    state = load_state()
    state.pop(symbol, None)
    save_state(state)
