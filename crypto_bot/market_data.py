"""Fetches a current bid/ask price snapshot for a crypto pair from
Alpaca's crypto market data API. One-shot poll, not a streaming
connection.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestQuoteRequest


class MarketDataError(Exception):
    """Raised when Alpaca rejects or fails a market data request."""


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    time: datetime
    bid: Decimal
    ask: Decimal

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


def get_price(client: CryptoHistoricalDataClient, symbol: str = "BTC/USD") -> PriceQuote:
    request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
    try:
        quotes = client.get_crypto_latest_quote(request)
    except APIError as exc:
        raise MarketDataError(f"Failed to fetch price for {symbol}") from exc

    quote = quotes[symbol]
    return PriceQuote(
        symbol=symbol,
        time=quote.timestamp,
        bid=Decimal(str(quote.bid_price)),
        ask=Decimal(str(quote.ask_price)),
    )


if __name__ == "__main__":
    import logging

    from crypto_bot.config import load_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = load_settings()
    client = CryptoHistoricalDataClient(
        api_key=settings.alpaca_api_key, secret_key=settings.alpaca_secret_key
    )
    quote = get_price(client)

    print(f"{quote.symbol}  bid={quote.bid}  ask={quote.ask}  spread={quote.spread}")
