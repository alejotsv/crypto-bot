# Feature: Alpaca API authentication

Status: Done
Depends on: [001-project-structure-and-dependencies](001-project-structure-and-dependencies.md)
Related ADRs: [0002-use-alpaca-py](../adr/0002-use-alpaca-py.md), [0003-paper-account-until-explicit-go-live](../adr/0003-paper-account-until-explicit-go-live.md)

## Summary

Alpaca's API doesn't have a "login" step that returns a session — every
request carries your API key/secret as headers. So "authentication" here
means: build a correctly configured `alpaca.trading.client.TradingClient`
from `config.Settings`, and prove the key/secret pair actually works by
making one safe, read-only call against Alpaca's paper API (account
info). This feature also establishes the pattern (client construction,
environment selection, error handling) that every later feature (market
data, orders, positions) will reuse.

## Goals

- A single place (`crypto_bot/alpaca_client.py`) that builds an
  authenticated `TradingClient` from config, using
  `Settings.alpaca_paper` and `Settings.alpaca_base_url` (already
  cross-validated against each other in `config.py` — this feature
  doesn't re-check that, just consumes the result).
- A simple, explicit way to verify credentials work: call Alpaca's
  account endpoint and confirm a response comes back (status, currency,
  cash, buying power) — the manual "do my keys work" check the user runs
  once they've filled in real values.
- Clear, non-leaking error handling: on bad key/secret, raise a clear
  application-level error rather than letting a raw stack trace (or the
  secret itself) leak into logs.
- Make the active environment (paper/live) impossible to miss — always
  surfaced to the user when a client is built.

## Non-Goals

- No market data fetching logic — that's feature 3.
- No order placement or position logic — features 4–5.
- No retry/backoff, connection pooling, or rate-limit handling — out of
  scope for a learning project; add later only if it actually becomes a
  problem.
- No CLI framework — a single runnable check is enough for now.

## Requirements

1. `crypto_bot/alpaca_client.py` exposes `get_client(settings: Settings)
   -> TradingClient` that constructs a `TradingClient` using
   `settings.alpaca_api_key`, `settings.alpaca_secret_key`,
   `settings.alpaca_paper`, and `settings.alpaca_base_url` (passed as
   `url_override`).
2. Building a client never makes a network call by itself — construction
   is just configuration; the actual request happens in step 3.
3. `alpaca_client.py` also exposes a verification call, e.g.
   `verify_connection(client) -> dict`, that hits Alpaca's account
   endpoint (`client.get_account()`) and returns the relevant fields
   (status, currency, cash, buying power). Running `python -m
   crypto_bot.alpaca_client` performs this check against the values in
   `.env` and prints (to stdout) those fields — nothing else, and never
   the API key/secret.
4. On authentication failure (`alpaca.common.exceptions.APIError` for
   bad key/secret), catch it and raise a small custom exception (e.g.
   `AlpacaAuthError`) with a clear message (e.g. "Alpaca authentication
   failed — check ALPACA_API_KEY and ALPACA_SECRET_KEY"). The secret
   itself must never appear in the exception message, logs, or stdout
   (confirmed empirically: Alpaca's own error response for bad
   credentials is just `{"message": "unauthorized."}`, no echo of what
   was sent).
5. Whenever a client is built, log/print which environment it's
   targeting (`paper`/`live`, from `settings.alpaca_paper`) at INFO
   level, so it is never ambiguous which environment a run is hitting.
   Per ADR 0003, this feature does not add any new way to reach `live`
   — it only reads whatever `settings.alpaca_paper`/`alpaca_base_url`
   already resolved to (and `config.py` already refuses to load if they
   disagree).

## Design / Approach

```python
# crypto_bot/alpaca_client.py
import logging

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient

from crypto_bot.config import Settings

logger = logging.getLogger(__name__)


class AlpacaAuthError(Exception):
    ...


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
            "Alpaca authentication failed -- check ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY"
        ) from exc

    return {
        "status": str(account.status),
        "currency": account.currency,
        "cash": account.cash,
        "buying_power": account.buying_power,
    }


if __name__ == "__main__":
    # load Settings, build client, call verify_connection, print
    # status/currency/cash/buying_power only
    ...
```

Using `get_account()` for verification is deliberate: it's a lightweight,
read-only call that validates the key/secret pair directly (Alpaca
returns a 401/`unauthorized` `APIError` for a bad pair), matching the
manual check already run by hand while building feature 1
(`account.status`, `.currency`, `.cash`, `.buying_power` — the exact
fields confirmed working against the real paper account already).

## Environment Variables / Config

No new variables — this feature only consumes `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`, `ALPACA_PAPER`, and `ALPACA_BASE_URL`, already
defined and validated in feature 1.

## Acceptance Criteria

- [ ] `get_client(settings)` returns a `TradingClient` instance
      configured with `settings.alpaca_paper`/`settings.alpaca_base_url`,
      with no network call made during construction.
- [ ] Unit test (no network, no real credentials) confirms `get_client`
      passes `paper` and `url_override` through correctly for both paper
      and live settings, using fake/dummy keys.
- [ ] `verify_connection` / `python -m crypto_bot.alpaca_client`, when
      run with real paper credentials in `.env`, successfully prints
      account status, currency, cash, and buying power.
- [ ] Running the same check with a deliberately wrong key/secret raises
      `AlpacaAuthError` with a clear message, and the secret value never
      appears in the error, logs, or stdout.
- [ ] The active environment (`paper`/`live`) is always logged/printed
      when a client is built.
- [ ] README updated with: how to run the verification check (getting
      Alpaca credentials is already documented from feature 1).

## Open Questions

None. The `python -m crypto_bot.alpaca_client` entry point in this spec
is a **development/debugging convenience only** — a way to manually
confirm your keys work while building this feature. It has no bearing
on `get_client`/`verify_connection` themselves (identical either way)
and no bearing on how the bot actually operates day-to-day. No reason to
build `main.py`/CLI plumbing for a one-off smoke test, so this stays a
plain module script.

## Out of Scope / Future Work

- Market data fetching (feature 3) will reuse `get_client` but is
  specced separately.
- Any retry logic for transient network errors — revisit only if it
  actually causes friction in practice.
