"""Builds an authenticated Alpaca TradingClient from config, and verifies
credentials work via a lightweight read-only account call.
"""

import logging

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient

from crypto_bot.config import Settings

logger = logging.getLogger(__name__)


class AlpacaAuthError(Exception):
    """Raised when Alpaca rejects or fails an authentication check."""


def get_client(settings: Settings) -> TradingClient:
    logger.info(
        "Building Alpaca client for %s (%s)",
        "paper" if settings.alpaca_paper else "LIVE",
        settings.alpaca_base_url,
    )
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        paper=settings.alpaca_paper,
        url_override=settings.alpaca_base_url,
    )


def verify_connection(client: TradingClient) -> dict:
    try:
        account = client.get_account()
    except APIError as exc:
        raise AlpacaAuthError(
            "Alpaca authentication failed -- check ALPACA_API_KEY and ALPACA_SECRET_KEY"
        ) from exc

    return {
        "status": str(account.status),
        "currency": account.currency,
        "cash": account.cash,
        "buying_power": account.buying_power,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from crypto_bot.config import load_settings

    settings = load_settings()
    client = get_client(settings)
    info = verify_connection(client)

    print(
        f"status={info['status']}  currency={info['currency']}  "
        f"cash={info['cash']}  buying_power={info['buying_power']}"
    )
