"""Tracks the last processed Telegram update_id so re-running the cron
cycle doesn't re-process the same message twice.
"""

import json
from pathlib import Path

STATE_PATH = Path("telegram_state.json")


def load_last_update_id() -> int:
    if not STATE_PATH.exists():
        return 0
    return json.loads(STATE_PATH.read_text())["last_update_id"]


def save_last_update_id(update_id: int) -> None:
    STATE_PATH.write_text(json.dumps({"last_update_id": update_id}))
