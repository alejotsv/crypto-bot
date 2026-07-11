"""Consolidated cron entrypoint. Per invocation, in order: processes
pending Telegram commands (feature 10), runs the auto-entry check
(feature 9, if enabled) and notifies on it, then runs the exit
reconciliation check (feature 6) and notifies on it. Intended to be
invoked by cron every 2 minutes (feature 7) -- no persistent process,
just a repeated one-shot script, consistent with how this project's
checks are all designed.
"""

import logging

from alpaca.data.historical.crypto import CryptoHistoricalDataClient

from crypto_bot.alpaca_client import get_client
from crypto_bot.config import load_settings
from crypto_bot.exits import check_and_reconcile_exits
from crypto_bot.strategy import run_auto_entry_cycle
from crypto_bot.telegram_bot import TelegramError, get_updates, send_message
from crypto_bot.telegram_commands import handle_command
from crypto_bot.telegram_state import load_last_update_id, save_last_update_id

logger = logging.getLogger(__name__)


def _process_telegram_commands(client, data_client, settings) -> None:
    """Fetches new Telegram updates, replies to each command from the
    configured chat, and advances the stored offset -- an update from
    any other chat_id is skipped entirely (not replied to, not acted
    on). Wrapped by the caller so a Telegram outage doesn't prevent the
    safety-critical auto-entry/reconciliation steps below from running.
    """
    offset = load_last_update_id()
    updates = get_updates(settings, offset)

    for update in updates:
        next_offset = update["update_id"] + 1
        message = update.get("message")

        if message is None or str(message.get("chat", {}).get("id")) != settings.telegram_chat_id:
            save_last_update_id(next_offset)
            continue

        reply_text, reply_markup = handle_command(
            client, data_client, settings, message.get("text", "")
        )
        send_message(settings, reply_text, reply_markup)
        save_last_update_id(next_offset)


def run_reconcile_cycle() -> None:
    settings = load_settings()
    client = get_client(settings)
    data_client = CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
    )

    try:
        _process_telegram_commands(client, data_client, settings)
    except TelegramError as exc:
        logger.warning("Telegram command processing failed: %s", exc)

    if settings.auto_entry_enabled:
        entry_results = run_auto_entry_cycle(client, data_client, settings)
        for result in entry_results:
            if result.action in ("ENTERED", "SKIPPED_INSUFFICIENT_FUNDS"):
                logger.info(
                    "Auto-entry cycle: %s %s -- %s", result.symbol, result.action, result.detail
                )
                _notify(settings, f"Auto-entry {result.action}: {result.symbol} -- {result.detail}")

    actions = check_and_reconcile_exits(client, data_client)
    if not actions:
        logger.info("Reconcile cycle: no action needed.")
    for action in actions:
        logger.info("Reconcile cycle: %s %s -- %s", action.symbol, action.action, action.detail)
        _notify(settings, f"Reconcile {action.action}: {action.symbol} -- {action.detail}")


def _notify(settings, text: str) -> None:
    try:
        send_message(settings, text)
    except TelegramError as exc:
        logger.warning("Telegram notification failed: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run_reconcile_cycle()
